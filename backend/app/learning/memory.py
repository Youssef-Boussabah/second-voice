"""Relationship-scoped episode writes and context reads for Lane D."""
import asyncio
import logging
import time
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.contracts import EpisodeSummary, Memory, OpenThread, RetrievedContext, new_id
from app.db import MEMORIES, PEOPLE, db
from app.learning.safe_embed import embed_document_or_none
from app.learning.boundaries import get_active_boundaries
from app.learning.demo_seed import LEARNED_TAG
from app.guard.enforce import blocked_topics, tag_topics_safety_net

log = logging.getLogger(__name__)


async def save_episode(user_id: str, person_id: str, session_id: str, summary: EpisodeSummary,
                       memory_id: str | None = None) -> str:
    """Insert the episode, then mark resolved threads. A duplicate memory_id is a no-op."""
    now = datetime.now(timezone.utc)
    memory = Memory(
        id=memory_id or new_id("mem"), user_id=user_id, person_id=person_id, kind="episode",
        text=summary.summary, topics=summary.topics, open_threads=summary.open_threads_new,
        session_id=session_id, embedding=await embed_document_or_none(summary.summary), created_at=now,
    )
    record = memory.to_mongo() | LEARNED_TAG
    if record.get("embedding") is None:
        record.pop("embedding")  # missing (not null) so the backfill and $vectorSearch both skip/fill it
    try:
        await db()[MEMORIES].insert_one(record)
    except DuplicateKeyError:
        return memory.id
    resolved = set(summary.threads_resolved_ids)
    if resolved:
        async for episode in db()[MEMORIES].find({"user_id": user_id, "person_id": person_id, "kind": "episode",
                                                  "open_threads.id": {"$in": sorted(resolved)}}):
            threads = [thread | {"status": "resolved"} if thread.get("id") in resolved else thread
                       for thread in episode.get("open_threads", [])]
            await db()[MEMORIES].update_one({"_id": episode["_id"]}, {"$set": {"open_threads": threads}})
    return memory.id


async def retrieve_person_context(user_id: str, person_id: str, relationship: str) -> RetrievedContext:
    database = db()
    started = time.perf_counter()
    # Atlas is ~600 ms per round trip from the demo tablet: run the three reads concurrently and
    # leave the 1024-d vectors on the server (context display never needs them).
    person_record, memories, active_rules = await asyncio.gather(
        database[PEOPLE].find_one({"_id": person_id, "user_id": user_id}, {"voiceprints": 0, "voice_centroid": {"$slice": 1}}),
        database[MEMORIES].find(
            {"user_id": user_id, "status": "active", "person_id": {"$in": [person_id, "global"]}},
            {"embedding": 0},
        ).sort("created_at", -1).to_list(length=200),
        get_active_boundaries(user_id, relationship, person_id),
    )
    log.info("person context %s reads %dms", person_id, (time.perf_counter() - started) * 1000)
    person_out = None
    if person_record:
        from app.contracts import PersonOut
        person_out = PersonOut(
            id=person_record["_id"], name=person_record["name"],
            relationship=person_record["relationship"], label=person_record.get("label", ""),
            enrolled=bool(person_record.get("voice_centroid")), last_seen=person_record.get("last_seen"),
        )
    # DECISION: the tablet header shows this context in front of the partner, so the same
    # deterministic rule that blocks cards also hides memories on blocked topics (LLM topics plus
    # the guard's keyword net). Live 2026-11-14: Mike's header kept a medication open thread
    # after Maya taught "keep health & medication private with acquaintances".
    blocked = set(blocked_topics(person_out, active_rules)) if person_out else set()

    def visible(text: str, topics: list) -> bool:
        return not blocked or not ({str(getattr(t, "value", t)) for t in tag_topics_safety_net(text, list(topics))} & blocked)

    records = [Memory.model_validate(item) for item in memories]
    records = [memory for memory in records if visible(memory.text, memory.topics)]
    episodes = [memory for memory in records if memory.kind == "episode" and memory.person_id == person_id]
    # "Your usual phrases with them" is per partner only; global seed phrases are not theirs.
    phrases = sorted((memory for memory in records if memory.kind == "phrase" and memory.person_id == person_id),
                     key=lambda memory: memory.uses, reverse=True)
    facts = [memory for memory in records if memory.kind == "fact"]
    open_threads: list[OpenThread] = []
    for episode in episodes:
        open_threads.extend(thread for thread in episode.open_threads
                            if thread.status == "open" and visible(thread.text, []))
    return RetrievedContext(
        person=person_out, recent_episodes=episodes[:5], relevant_episodes=episodes[:5],
        open_threads=open_threads, phrases=phrases[:12], facts=facts[:12], boundaries=active_rules,
    )
