"""Summarize an ended session into one episode memory (Lane D).

Idempotent: the episode id is derived from the session id (`mem_ep_<session_id>`), so a
re-delivered `session_ended` event (change-stream resume, double tap on End) never creates a
second episode or re-resolves threads.
"""
import logging
import time

from app.config import settings
from app.contracts import EpisodeSummary, Event
from app.db import MEMORIES, SESSIONS, UTTERANCES, db
from app.llm import complete_json
from app.learning.memory import save_episode

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
    if await database[MEMORIES].find_one({"_id": memory_id}, {"_id": 1}):
        log.info("episode exists for session %s (%s); skipping re-delivery", evt.session_id, memory_id)
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
    if not utterances:
        log.info("episode skipped session=%s: no utterances", evt.session_id)
        return None

    lines = []
    for utterance in utterances:
        kind = (utterance.get("speaker") or {}).get("kind")
        lines.append(f"{'Maya' if kind == 'user' else 'Partner'}: {utterance.get('text', '').strip()}")
    open_threads = {}
    async for episode in database[MEMORIES].find({"user_id": evt.user_id, "person_id": person_id,
                                                  "kind": "episode", "status": "active"}):
        for thread in episode.get("open_threads", []):
            if thread.get("status") == "open":
                open_threads[thread["id"]] = thread["text"]
    prompt = "EXISTING OPEN THREADS:\n" + ("\n".join(f"- [{k}] {v}" for k, v in open_threads.items()) or "- none")
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
