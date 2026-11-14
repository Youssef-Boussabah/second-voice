"""Lane A: suggestion pipeline. See docs/02-architecture.md.

STABLE SIGNATURE (Lane B calls this):
    async def on_partner_utterance(utt: Utterance) -> None

Stages: instant_suggest (Atlas only, ~1 round trip) → retrieve → generate → guard
(→ regenerate ≤1) → publish. Each stage is a plain async node over `PipelineState`, so the same nodes can be
wired into a LangGraph StateGraph later without changing their logic.

# DECISION: the hot path runs the nodes directly (no checkpointer round-trips) to stay under
# the 3 s budget; conversation memory across restarts comes from the `utterances` collection
# (last 10 turns are re-read every run), which gives the same crash-safety story.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import db
from app.config import settings
from app.contracts import (
    Candidate, CandidateSource, GeneratedCandidates, PersonOut, PipelineState, RetrievedContext,
    SuggestionSet, Utterance, new_id, utcnow,
)
from app.embeddings import embed_query
from app.graph import instant
from app.guard.enforce import apply_guard, blocked_topics, tag_topics_safety_net
from app.llm import complete_json
from app.memory import retrieval
from app.realtime import hub

log = logging.getLogger(__name__)

TARGET = 4
MIN_SURVIVORS = 3

# Last-resort fillers for the final stage: neutral, never sensitive, still guarded.
_FILLERS = [text for text, _topics, _cue in instant.NEUTRAL]

# Canonical persona: docs/01-product.md (Maya Chen, 58; Sam is her grandson, 16, hockey, "bud").
PERSONA = (
    "You write reply suggestions for Maya Chen, 58, from Toronto, who has ALS and speaks through "
    "a tablet. Her voice: concise, warm, dry humour, never gushing. She calls her grandson Sam "
    "'bud'. Every suggestion is something Maya would say out loud, in first person, 3 to 14 "
    "words. Never narrate, never use emojis, never invent facts that are not in the context. "
    "Ground replies in the provided memories when relevant and cite their ids in memory_ids."
)


# ───────────────────────── public entry ─────────────────────────
async def on_partner_utterance(utt: Utterance) -> None:
    """Run instant + final stages and publish SuggestionSets. Must never raise."""
    try:
        await run(utt)
    except Exception as e:  # noqa: BLE001
        log.exception("pipeline failed for %s", utt.id)
        await hub.emit("error", utt.session_id, {"message": str(e)[:300], "where": "pipeline"})


async def run(utt: Utterance) -> SuggestionSet | None:
    """Instant stage first (Atlas-only, no embeddings, no LLM), then the final stage.

    The query embedding starts immediately in the background but nothing in the instant stage
    waits for it, so a slow or rate-limited Voyage can only affect the final stage."""
    t0 = time.perf_counter()
    state = PipelineState(utterance=utt)
    qvec_task = asyncio.create_task(_embed_query(utt.text))
    await hub.emit("utterance.created", utt.session_id, utt)

    instant_set = await instant_suggest(state, t0)
    await announce_unknown_speaker(state)

    try:
        qvec = await qvec_task
        state.timings_ms["embed"] = _ms(t0)
        await retrieve(state, qvec)
        await generate(state)
        await guard(state)
        if len(state.allowed) < MIN_SURVIVORS and state.regenerations == 0:
            state.regenerations += 1
            await generate(state, regenerate=True)
            await guard(state)
    except Exception as e:  # noqa: BLE001  degrade: keep instant suggestions on screen
        log.exception("final stage failed for %s", utt.id)
        await hub.emit("error", utt.session_id, {"message": f"suggestions degraded: {str(e)[:200]}",
                                                 "where": "generate"})
        if instant_set is not None:
            return instant_set
        state.generated, state.allowed = [], []
        await guard(state)
    state.timings_ms["total"] = _ms(t0)
    state.timings_ms["final"] = state.timings_ms["total"]
    return await publish(state, "final", instant_cands=instant_set.candidates if instant_set else [])


# ───────────────────────── nodes ─────────────────────────
async def instant_suggest(state: PipelineState, t0: float) -> SuggestionSet | None:
    """Stage 1: person + active rules + saved phrases in ONE parallel Atlas round trip →
    rank (lexical + usage) → neutral top-up → deterministic guard → publish stage=instant.
    Also fills state.person for the final stage. Never raises."""
    utt = state.utterance
    t = time.perf_counter()
    pid = utt.speaker.person_id
    try:
        person, bnds, phrases = await asyncio.gather(
            retrieval.load_person(pid), retrieval.active_boundaries(utt.user_id),
            retrieval.saved_phrases(utt.user_id, pid))
        state.person = person
        state.timings_ms["instant_db"] = _ms(t)
        cands = instant.rank_quick_replies(utt.text, phrases, person.id if person else None)
        allowed, blocked = apply_guard(cands, person, bnds)
        s = SuggestionSet(
            session_id=utt.session_id, user_id=utt.user_id, utterance_id=utt.id,
            person_id=person.id if person else None, stage="instant",
            candidates=allowed[:TARGET], blocked=blocked,
            latency_ms={"instant_db": state.timings_ms["instant_db"]})
        # Persist BEFORE emit: once a card is visible, POST /select must find its set (no 404
        # race on an immediate tap). Costs one Atlas round trip (~100 ms) on the instant path.
        tp = time.perf_counter()
        await _save(s)
        persist_ms = _ms(tp)
        first_ms = _ms(t0)
        state.timings_ms["first_suggestion"] = first_ms
        s.latency_ms.update({"persist": persist_ms, "first_suggestion": first_ms,
                             "since_utterance": _since(utt)})
        await hub.emit("suggestions.ready", s.session_id, s)
        # record the final instant timings on the stored doc (off the critical path)
        await db.db()[db.SUGGESTION_SETS].update_one({"_id": s.id}, {"$set": {"latency_ms": s.latency_ms}})
        log.info("instant %s first_suggestion_ms=%d db_ms=%d persist_ms=%d phrases=%d allowed=%d "
                 "blocked=%d", s.id, first_ms, state.timings_ms["instant_db"], persist_ms,
                 len(phrases), len(s.candidates), len(blocked))
        return s
    except Exception:  # noqa: BLE001  instant stage is best-effort; final stage still runs
        log.exception("instant stage failed")
        if state.person is None and pid:
            state.person = await retrieval.load_person(pid)
        return None


async def announce_unknown_speaker(state: PipelineState) -> None:
    utt = state.utterance
    method = utt.speaker.method if isinstance(utt.speaker.method, str) else utt.speaker.method.value
    if state.person is None and method == "unknown":
        people = await retrieval.list_people(utt.user_id)
        await hub.emit("speaker.unknown", utt.session_id, {
            "utterance_id": utt.id, "candidates": [p.model_dump(mode="json") for p in people]})


async def retrieve(state: PipelineState, qvec: list[float] | None) -> None:
    t = time.perf_counter()
    utt = state.utterance
    state.context = await retrieval.get_context(
        utt.user_id, state.person.id if state.person else None, utt.text,
        session_id=utt.session_id, qvec=qvec, person=state.person, skip_embed=True)
    state.timings_ms["retrieve"] = _ms(t)


async def generate(state: PipelineState, *, regenerate: bool = False) -> None:
    t = time.perf_counter()
    ctx = state.context or RetrievedContext()
    avoid = blocked_topics(state.person, ctx.boundaries)
    if regenerate:
        # also avoid every topic that got blocked last round
        for c in state.blocked:
            for tp in c.topics:
                v = tp if isinstance(tp, str) else tp.value
                if v not in avoid:
                    avoid.append(v)
    prompt = build_prompt(state, avoid)
    out = await complete_json(PERSONA, prompt, GeneratedCandidates, model=settings.suggest_model)
    valid_ids = _context_memory_ids(ctx)
    cands: list[Candidate] = []
    seen: set[str] = set()
    for g in out.candidates[:8]:
        text = g.text.strip().strip('"')
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        cands.append(Candidate(text=text, topics=tag_topics_safety_net(text, list(g.topics)),
                               source=CandidateSource.llm,
                               memory_ids=[m for m in g.memory_ids if m in valid_ids]))
    state.generated = cands
    state.timings_ms["generate" if not regenerate else "regenerate"] = _ms(t)


async def guard(state: PipelineState) -> None:
    t = time.perf_counter()
    ctx = state.context or RetrievedContext()
    allowed, blocked = apply_guard(state.generated, state.person, ctx.boundaries)
    # keep every blocked candidate across a regenerate (the demo shows "N hidden")
    prev_blocked = {c.text for c in state.blocked}
    state.blocked = state.blocked + [c for c in blocked if c.text not in prev_blocked]
    state.allowed = allowed
    state.timings_ms["guard"] = _ms(t)


async def publish(state: PipelineState, stage: str, *, instant_cands: list[Candidate]) -> SuggestionSet:
    utt = state.utterance
    ctx = state.context or RetrievedContext()
    allowed = list(state.allowed)
    # Top up to 4 from guarded phrasebook hits, then guarded neutral fillers.
    if len(allowed) < TARGET:
        have = {c.text.lower() for c in allowed}
        extra = [c for c in instant_cands if c.text.lower() not in have]
        extra += [Candidate(text=f, topics=["small_talk"], source=CandidateSource.phrasebook)
                  for f in _FILLERS if f.lower() not in have]
        ok, _ = apply_guard(extra, state.person, ctx.boundaries)
        for c in ok:
            if len(allowed) >= TARGET:
                break
            if c.text.lower() not in have:
                allowed.append(c.model_copy(update={"id": new_id("cand")}))
                have.add(c.text.lower())
    s = SuggestionSet(session_id=utt.session_id, user_id=utt.user_id, utterance_id=utt.id,
                      person_id=state.person.id if state.person else None, stage=stage,
                      candidates=allowed[:TARGET], blocked=state.blocked,
                      latency_ms={**state.timings_ms, "since_utterance": _since(utt)})
    await _save_and_emit(s)
    await db.db()[db.UTTERANCES].update_one({"_id": utt.id}, {"$set": {"suggestion_set_id": s.id}})
    log.info("published %s stage=%s first_suggestion_ms=%s final_ms=%s allowed=%d blocked=%d latency=%s",
             s.id, stage, s.latency_ms.get("first_suggestion"), s.latency_ms.get("final"),
             len(s.candidates), len(s.blocked), s.latency_ms)
    return s


# ───────────────────────── prompt ─────────────────────────
def build_prompt(state: PipelineState, avoid: list[str]) -> str:
    ctx = state.context or RetrievedContext()
    p: PersonOut | None = state.person
    rel = (p.relationship if isinstance(p.relationship, str) else p.relationship.value) if p else "stranger"
    lines: list[str] = []
    if p:
        lines.append(f"PARTNER: {p.name} ({p.label or rel})")
    else:
        lines.append("PARTNER: unknown person. Keep replies polite, brief and non-personal.")
    lines.append(f"RELATIONSHIP: {rel}")
    if ctx.facts:
        lines.append("FACTS:")
        lines += [f"- [{m.id}] {m.text}" for m in ctx.facts[:6]]
    eps = {m.id: m for m in [*ctx.relevant_episodes, *ctx.recent_episodes]}
    if eps:
        lines.append("PAST CONVERSATIONS WITH THIS PERSON (most relevant first):")
        lines += [f"- [{m.id}] {m.created_at:%b %d}: {m.text}" for m in list(eps.values())[:5]]
    if ctx.open_threads:
        lines.append("OPEN THREADS (unresolved; good to follow up):")
        lines += [f"- ({t.owner}) {t.text}" for t in ctx.open_threads[:4]]
    if ctx.phrases:
        lines.append("PHRASES MAYA ACTUALLY USES WITH THEM (match this style):")
        lines += [f"- {m.text}" for m in ctx.phrases[:8]]
    turns = [u for u in ctx.recent_turns if u.id != state.utterance.id][-10:]
    if turns:
        lines.append("CONVERSATION SO FAR:")
        for u in turns:
            kind = u.speaker.kind if isinstance(u.speaker.kind, str) else u.speaker.kind.value
            who = "Maya" if kind == "user" else (p.name.split()[0] if p else "Them")
            lines.append(f"{who}: {u.text}")
    if avoid:
        lines.append(f"AVOID TOPICS: {', '.join(avoid)}")
        lines.append("Do not suggest anything touching those topics with this person.")
    lines.append("")
    lines.append(f'THEY JUST SAID: "{state.utterance.text}"')
    lines.append("")
    lines.append(
        "Write 6 distinct candidate replies Maya could tap, best first. Mix intents: a direct "
        "answer, a question back, a follow-up on an open thread or past memory if one fits, and a "
        "short acknowledgement. Tag each with its topics from the fixed taxonomy (be honest: tag "
        "health/medication/finances etc. whenever they apply) and cite memory ids you used."
    )
    return "\n".join(lines)


# ───────────────────────── helpers ─────────────────────────
async def _embed_query(text: str) -> list[float] | None:
    try:
        return await embed_query(text)
    except Exception as e:  # noqa: BLE001  no embeddings → skip vector stages, keep going
        log.warning("query embedding unavailable (%s); vector stages skipped", str(e)[:160])
        return None


async def _save(s: SuggestionSet) -> None:
    s.updated_at = utcnow()
    await db.db()[db.SUGGESTION_SETS].replace_one({"_id": s.id}, s.to_mongo(), upsert=True)


async def _save_and_emit(s: SuggestionSet) -> None:
    await _save(s)
    await hub.emit("suggestions.ready", s.session_id, s)


def _since(utt: Utterance) -> int:
    """ms from utterance creation (includes the HTTP insert before the pipeline started)."""
    return max(0, int((utcnow() - utt.created_at).total_seconds() * 1000))


def _context_memory_ids(ctx: RetrievedContext) -> set[str]:
    return {m.id for m in [*ctx.recent_episodes, *ctx.relevant_episodes, *ctx.phrases, *ctx.facts]}


def _ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)
