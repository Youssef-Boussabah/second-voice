"""Lane A: core REST routes. See docs/04-api-contracts.md §1 (Lane A).

Every write that matters also inserts an `Event` (person_id, relationship, text, topics
denormalized) so Lane D's worker and the replay validator can learn from it.
Nothing here ever speaks: `select` / `replies/typed` only return `text_to_speak`; the client
calls POST /api/tts after the user's tap.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from app import db
from app.config import settings
from app.contracts import (
    AssignSpeakerIn, Candidate, Event, EventType, PersonOut, RejectIn, SelectIn, SelectOut,
    Session, SessionStartIn, SpeakerKind, SpeakerMatch, SpeakerMethod, SuggestionSet,
    TextUtteranceIn, TypedReplyIn, Utterance, UtteranceOut, UtteranceSource, utcnow,
)
from app.graph import pipeline
from app.guard.enforce import tag_topics_safety_net
from app.memory import retrieval
from app.realtime import hub

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["core"])

_bg_tasks: set[asyncio.Task] = set()


def spawn_pipeline(utt: Utterance) -> None:
    """Fire-and-forget the suggestion pipeline (keeps a strong ref so the task isn't GC'd)."""
    task = asyncio.create_task(pipeline.on_partner_utterance(utt), name=f"pipeline-{utt.id}")
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


@router.get("/health")
async def health():
    out: dict[str, Any] = {
        "ok": True,
        "mocks": {
            "llm": settings.mock_llm, "embed": settings.mock_embed, "stt": settings.mock_stt,
            "speaker": settings.mock_speaker, "tts": settings.mock_tts,
        },
        "llm_provider": settings.llm_provider,
        "change_streams": settings.use_change_streams,
        "ws_connections": hub.connection_count(),
    }
    # What THIS process actually loaded (never secrets: only presence + model ids), so a demo
    # operator can prove nothing silently fell back to mocks or to another model.
    from app import llm
    if settings.llm_provider == "nebius":
        out["models"] = {
            "suggest": llm._nebius_resolved.get(settings.nebius_model, settings.nebius_model),
            "summary": llm._nebius_resolved.get(settings.nebius_summary_model, settings.nebius_summary_model),
            "verified": settings.nebius_model in llm._nebius_resolved,
            "hedge": settings.llm_hedge_model or None,
            "hedge_after_s": settings.llm_hedge_after_s,
            "hot_path_answers": dict(llm.hedge_stats),
            "last_hot_model": llm.last_hot_model,
        }
    out["embed_model"] = settings.embed_model
    out["configured"] = {
        "nebius_key": bool(settings.nebius_api_key), "voyage_key": bool(settings.voyage_api_key),
        "elevenlabs_key": bool(settings.elevenlabs_api_key),
        "elevenlabs_voice": bool(settings.elevenlabs_voice_id),
    }
    return out


@router.get("/health/db")
async def health_db():
    """Pings Atlas and reports collection counts (proves we're on real data)."""
    t = time.perf_counter()
    try:
        await db.db().command("ping")
        d = db.db()
        counts = {}
        for c in (db.PEOPLE, db.MEMORIES, db.BOUNDARIES, db.SESSIONS, db.EVENTS):
            counts[c] = await d[c].count_documents({"user_id": settings.demo_user_id})
        return {"ok": True, "db": settings.mongodb_db, "counts": counts,
                "ping_ms": int((time.perf_counter() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"mongodb: {str(e)[:200]}") from e


# ───────────────────────── helpers ─────────────────────────
async def _get_session(session_id: str) -> Session:
    doc = await db.db()[db.SESSIONS].find_one({"_id": session_id})
    if not doc:
        raise HTTPException(404, f"session {session_id} not found")
    return Session.model_validate(doc)


async def _get_set(set_id: str) -> SuggestionSet:
    doc = await db.db()[db.SUGGESTION_SETS].find_one({"_id": set_id})
    if not doc:
        raise HTTPException(404, f"suggestion set {set_id} not found")
    return SuggestionSet.model_validate(doc)


async def record_event(evt: Event) -> bool:
    """Insert an event. Returns False if this event_id was already recorded (idempotent)."""
    try:
        await db.db()[db.EVENTS].insert_one(evt.to_mongo())
        return True
    except DuplicateKeyError:
        log.info("duplicate event %s ignored", evt.id)
        return False


def _rel(p: Optional[PersonOut]) -> Optional[str]:
    if p is None:
        return None
    return p.relationship if isinstance(p.relationship, str) else p.relationship.value


async def _session_partner(session: Session) -> Optional[str]:
    """Person the user is currently talking to: last identified partner turn, else session default."""
    doc = await (db.db()[db.UTTERANCES]
                 .find({"session_id": session.id, "speaker.kind": "partner",
                        "speaker.person_id": {"$ne": None}})
                 .sort("created_at", -1).limit(1).to_list(1))
    if doc:
        return doc[0]["speaker"]["person_id"]
    return session.person_ids[0] if session.person_ids else None


MAX_TEXT = 2000   # one conversational turn; also bounds the prompt and the TTS request


def _checked_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    if len(text) > MAX_TEXT:
        raise HTTPException(400, f"text is too long (max {MAX_TEXT} characters)")
    return text


def _user_utt_id(event_id: str) -> str:
    """Deterministic user-utterance id per event, so retried selects are idempotent."""
    return "utt_" + event_id.split("_", 1)[-1]


async def _insert_user_utterance(session: Session, text: str, source: UtteranceSource,
                                 event_id: str, set_id: Optional[str]) -> Utterance:
    utt = Utterance(id=_user_utt_id(event_id), session_id=session.id, user_id=session.user_id,
                    speaker=SpeakerMatch(kind=SpeakerKind.user, method=SpeakerMethod.manual),
                    text=text, source=source, suggestion_set_id=set_id)
    try:
        await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
        await hub.emit("utterance.created", session.id, utt)
    except DuplicateKeyError:
        existing = await db.db()[db.UTTERANCES].find_one({"_id": utt.id})
        utt = Utterance.model_validate(existing)
    return utt


# ───────────────────────── sessions ─────────────────────────
@router.post("/sessions", response_model=Session)
async def start_session(body: SessionStartIn):
    person = await retrieval.load_person(body.person_id) if body.person_id else None
    if body.person_id and person is None:
        raise HTTPException(404, f"person {body.person_id} not found")
    s = Session(user_id=settings.demo_user_id, person_ids=[body.person_id] if body.person_id else [])
    await db.db()[db.SESSIONS].insert_one(s.to_mongo())
    await record_event(Event(user_id=s.user_id, type=EventType.session_started, session_id=s.id,
                             person_id=body.person_id, relationship=_rel(person)))
    log.info("session started %s person=%s", s.id, body.person_id)
    return s


@router.post("/sessions/{session_id}/end", response_model=Session)
async def end_session(session_id: str):
    s = await _get_session(session_id)
    if s.status != "ended":
        s.status, s.ended_at = "ended", utcnow()
        await db.db()[db.SESSIONS].update_one({"_id": s.id},
                                              {"$set": {"status": "ended", "ended_at": s.ended_at}})
        pid = await _session_partner(s)
        person = await retrieval.load_person(pid)
        await record_event(Event(user_id=s.user_id, type=EventType.session_ended, session_id=s.id,
                                 person_id=pid, relationship=_rel(person)))
    return s


@router.get("/sessions/{session_id}/latest", response_model=Optional[SuggestionSet])
async def latest_set(session_id: str):
    docs = await (db.db()[db.SUGGESTION_SETS].find({"session_id": session_id})
                  .sort("created_at", -1).limit(1).to_list(1))
    return SuggestionSet.model_validate(docs[0]) if docs else None


# ───────────────────────── utterances ─────────────────────────
@router.post("/utterances/text", response_model=UtteranceOut)
async def text_utterance(body: TextUtteranceIn):
    t = time.perf_counter()
    text = _checked_text(body.text)
    session = await _get_session(body.session_id)
    if body.person_id:
        if await retrieval.load_person(body.person_id) is None:
            raise HTTPException(404, f"person {body.person_id} not found")
        speaker = SpeakerMatch(kind=SpeakerKind.partner, person_id=body.person_id,
                               method=SpeakerMethod.forced)
    elif session.person_ids:
        # DECISION: text mode without an explicit person → the session's chosen partner.
        speaker = SpeakerMatch(kind=SpeakerKind.partner, person_id=session.person_ids[-1],
                               method=SpeakerMethod.manual)
    else:
        speaker = SpeakerMatch(kind=SpeakerKind.partner, method=SpeakerMethod.unknown)
    utt = Utterance(session_id=session.id, user_id=session.user_id, speaker=speaker, text=text,
                    source=UtteranceSource.text)
    await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
    spawn_pipeline(utt)   # start the instant stage before any non-critical write
    if speaker.person_id and speaker.person_id not in session.person_ids:
        await db.db()[db.SESSIONS].update_one({"_id": session.id},
                                              {"$addToSet": {"person_ids": speaker.person_id}})
    ms = int((time.perf_counter() - t) * 1000)
    log.info("text utterance %s person=%s %dms", utt.id, speaker.person_id, ms)
    return UtteranceOut(utterance=utt, latency_ms={"insert": ms})


@router.post("/utterances/{utterance_id}/assign", response_model=UtteranceOut)
async def assign_speaker(utterance_id: str, body: AssignSpeakerIn):
    doc = await db.db()[db.UTTERANCES].find_one({"_id": utterance_id})
    if not doc:
        raise HTTPException(404, f"utterance {utterance_id} not found")
    person = await retrieval.load_person(body.person_id)
    if person is None:
        raise HTTPException(404, f"person {body.person_id} not found")
    utt = Utterance.model_validate(doc)
    utt.speaker = SpeakerMatch(kind=SpeakerKind.partner, person_id=person.id,
                               score=utt.speaker.score, method=SpeakerMethod.manual)
    await db.db()[db.UTTERANCES].update_one(
        {"_id": utt.id}, {"$set": {"speaker": utt.speaker.model_dump(mode="python")}})
    await db.db()[db.SESSIONS].update_one({"_id": utt.session_id},
                                          {"$addToSet": {"person_ids": person.id}})
    await record_event(Event(user_id=utt.user_id, type=EventType.speaker_assigned,
                             session_id=utt.session_id, person_id=person.id,
                             relationship=_rel(person), text=utt.text))
    # DECISION: add_voiceprint is Lane B's concern (they hold the audio); we just pass it through.
    spawn_pipeline(utt)
    return UtteranceOut(utterance=utt)


# ───────────────────────── suggestions ─────────────────────────
@router.post("/suggestions/{set_id}/select", response_model=SelectOut)
async def select_suggestion(set_id: str, body: SelectIn):
    s = await _get_set(set_id)
    cand: Optional[Candidate] = next((c for c in s.candidates if c.id == body.candidate_id), None)
    if cand is None:
        raise HTTPException(404, f"candidate {body.candidate_id} not in set {set_id}")
    session = await _get_session(s.session_id)
    edited = _checked_text(body.edited_text) if (body.edited_text or "").strip() else ""
    is_edit = bool(edited) and edited != cand.text
    text = edited if is_edit else cand.text
    topics = tag_topics_safety_net(text, [] if is_edit else list(cand.topics))
    person = await retrieval.load_person(s.person_id)

    fresh = await record_event(Event(
        id=body.event_id, user_id=s.user_id, session_id=s.session_id,
        type=EventType.suggestion_edited if is_edit else EventType.suggestion_selected,
        person_id=s.person_id, relationship=_rel(person), suggestion_set_id=s.id,
        candidate_id=cand.id, text=text, topics=topics))
    if fresh:
        await db.db()[db.SUGGESTION_SETS].update_one(
            {"_id": s.id}, {"$set": {"status": "chosen", "chosen_candidate_id": cand.id,
                                     "updated_at": utcnow()}})
    utt = await _insert_user_utterance(
        session, text, UtteranceSource.edited if is_edit else UtteranceSource.suggestion,
        body.event_id, s.id)
    log.info("select %s cand=%s edited=%s", s.id, cand.id, is_edit)
    return SelectOut(utterance=utt, text_to_speak=text)


@router.post("/suggestions/{set_id}/reject")
async def reject_suggestion(set_id: str, body: RejectIn):
    s = await _get_set(set_id)
    cand = next((c for c in [*s.candidates, *s.blocked] if c.id == body.candidate_id), None)
    if cand is None:
        raise HTTPException(404, f"candidate {body.candidate_id} not in set {set_id}")
    person = await retrieval.load_person(s.person_id)
    await record_event(Event(
        id=body.event_id, user_id=s.user_id, session_id=s.session_id,
        type=EventType.suggestion_rejected, person_id=s.person_id, relationship=_rel(person),
        suggestion_set_id=s.id, candidate_id=cand.id, text=cand.text,
        topics=tag_topics_safety_net(cand.text, list(cand.topics)), reason=body.reason))
    log.info("reject %s cand=%s reason=%s", s.id, cand.id, body.reason)
    return {"ok": True}


@router.post("/replies/typed", response_model=SelectOut)
async def typed_reply(body: TypedReplyIn):
    text = _checked_text(body.text)
    session = await _get_session(body.session_id)
    pid = await _session_partner(session)
    person = await retrieval.load_person(pid)
    # Mark the latest shown set (if any) as dismissed: the user wrote their own reply.
    latest = await (db.db()[db.SUGGESTION_SETS].find({"session_id": session.id, "status": "shown"})
                    .sort("created_at", -1).limit(1).to_list(1))
    set_id = latest[0]["_id"] if latest else None
    fresh = await record_event(Event(
        id=body.event_id, user_id=session.user_id, session_id=session.id,
        type=EventType.reply_typed, person_id=pid, relationship=_rel(person),
        suggestion_set_id=set_id, text=text, topics=tag_topics_safety_net(text, [])))
    if fresh and set_id:
        await db.db()[db.SUGGESTION_SETS].update_one(
            {"_id": set_id}, {"$set": {"status": "dismissed", "updated_at": utcnow()}})
    utt = await _insert_user_utterance(session, text, UtteranceSource.typed, body.event_id, set_id)
    return SelectOut(utterance=utt, text_to_speak=text)


# ───────────────────────── people ─────────────────────────
@router.get("/people", response_model=list[PersonOut])
async def get_people():
    return await retrieval.list_people(settings.demo_user_id)
