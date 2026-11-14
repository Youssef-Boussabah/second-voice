"""Summarize an ended session into one episode memory (Lane D).

Idempotent: the episode id is derived from the session id (`mem_ep_<session_id>`), so a
re-delivered `session_ended` event (change-stream resume, double tap on End) never creates a
second episode or re-resolves threads.
"""
import logging
import time

from app.config import settings
from app.contracts import EpisodeSummary, Event
from app.db import MEMORIES, PEOPLE, SESSIONS, UTTERANCES, db
from app.llm import complete_json
from app.learning.memory import resolve_threads, save_episode
from app.memory.retrieval import partner_segment

log = logging.getLogger(__name__)

SYSTEM = (
    "You summarize one conversation between Maya (an AAC user) and a partner for Maya's private "
    "memory. Reply as JSON: summary (1-2 sentences, past tense, concrete details), topics (from the "
    "allowed topic list), open_threads_new (promises or follow-ups still open: text, owner 'user' "
    "for Maya or 'partner'), threads_resolved_ids (ids from EXISTING OPEN THREADS that this "
    "conversation closed)."
)


def episode_id(session_id: str) -> str:
    return f"mem_ep_{session_id}"


async def summarize_session(evt: Event) -> str | None:
    started = time.perf_counter()
    if not evt.session_id:
        return None
    database = db()
    memory_id = episode_id(evt.session_id)
    existing = await database[MEMORIES].find_one({"_id": memory_id}, {"person_id": 1, "resolves_thread_ids": 1})
    if existing:
        # re-delivery or retry after a partial run: no second episode, no second LLM call, but
        # finish the (idempotent) thread resolution in case the first run died before it
        await resolve_threads(evt.user_id, existing.get("person_id"), existing.get("resolves_thread_ids") or [])
        log.info("episode exists for session %s (%s); completed idempotently", evt.session_id, memory_id)
        return memory_id
    person_id = evt.person_id
    if not person_id:
        session = await database[SESSIONS].find_one({"_id": evt.session_id})
        person_id = next(iter((session or {}).get("person_ids") or []), None)
    if not person_id:
        log.info("episode skipped session=%s: no partner", evt.session_id)
        return None
    utterances = await (database[UTTERANCES].find({"session_id": evt.session_id})
                        .sort("created_at", 1).to_list(200))
    # Only the stretch spoken with THIS partner: a session where Maya switched from Dana to Sam
    # must never file Dana's refill talk under Sam (found live in Atlas, 2026-11-14).
    utterances = partner_segment(utterances, person_id)
    if not any((u.get("speaker") or {}).get("kind") == "partner" for u in utterances):
        log.info("episode skipped session=%s: no partner turns with %s", evt.session_id, person_id)
        return None
    person = await database[PEOPLE].find_one({"_id": person_id}, {"name": 1, "label": 1, "relationship": 1})
    first = ((person or {}).get("name") or "Partner").split()[0]
    role = (person or {}).get("label") or (person or {}).get("relationship") or "conversation partner"

    lines = []
    for utterance in utterances:
        kind = (utterance.get("speaker") or {}).get("kind")
        lines.append(f"{'Maya' if kind == 'user' else first}: {utterance.get('text', '').strip()}")
    open_threads = {}
    async for episode in database[MEMORIES].find({"user_id": evt.user_id, "person_id": person_id,
                                                  "kind": "episode", "status": "active"}):
        for thread in episode.get("open_threads", []):
            if thread.get("status") == "open":
                open_threads[thread["id"]] = thread["text"]
    prompt = (f"PARTNER: {(person or {}).get('name', 'Partner')} ({role}). Refer to them by name, "
              f"never as 'the partner'. Only state what the transcript says.\n\n")
    prompt += "EXISTING OPEN THREADS:\n" + ("\n".join(f"- [{k}] {v}" for k, v in open_threads.items()) or "- none")
    prompt += "\n\nTRANSCRIPT:\n" + "\n".join(lines[-80:])
    try:
        summary = await complete_json(SYSTEM, prompt, EpisodeSummary, model=settings.summary_model)
    except Exception:  # noqa: BLE001  never lose the episode because the LLM is down
        log.exception("episode LLM failed session=%s; storing transcript fallback", evt.session_id)
        summary = EpisodeSummary(summary="Conversation: " + " / ".join(lines[-4:])[:400], topics=["small_talk"])
    summary.threads_resolved_ids = [tid for tid in summary.threads_resolved_ids if tid in open_threads]
    saved = await save_episode(evt.user_id, person_id, evt.session_id, summary, memory_id=memory_id)
    log.info("episode %s session=%s person=%s utterances=%d resolved=%d %dms", saved, evt.session_id,
             person_id, len(utterances), len(summary.threads_resolved_ids), (time.perf_counter() - started) * 1000)
    return saved
