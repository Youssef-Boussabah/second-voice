"""Relationship-scoped episode writes and context reads for Lane D."""
from datetime import datetime, timezone

from app.contracts import EpisodeSummary, Memory, OpenThread, RetrievedContext, new_id
from app.db import MEMORIES, PEOPLE, db
from app.embeddings import embed
from app.learning.boundaries import get_active_boundaries


async def save_episode(user_id: str, person_id: str, session_id: str, summary: EpisodeSummary) -> str:
    now = datetime.now(timezone.utc)
    await db()[MEMORIES].update_many(
        {"user_id": user_id, "person_id": person_id, "kind": "episode", "status": "active"},
        {"$pull": {"open_threads": {"id": {"$in": summary.threads_resolved_ids}}}},
    ) if summary.threads_resolved_ids else None
    memory = Memory(
        id=new_id("mem"), user_id=user_id, person_id=person_id, kind="episode",
        text=summary.summary, topics=summary.topics, open_threads=summary.open_threads_new,
        session_id=session_id, embedding=(await embed([summary.summary], "document"))[0], created_at=now,
    )
    await db()[MEMORIES].insert_one(memory.to_mongo())
    return memory.id


async def retrieve_person_context(user_id: str, person_id: str, relationship: str) -> RetrievedContext:
    database = db()
    person_record = await database[PEOPLE].find_one({"_id": person_id, "user_id": user_id})
    person_out = None
    if person_record:
        from app.contracts import PersonOut
        person_out = PersonOut(
            id=person_record["_id"], name=person_record["name"],
            relationship=person_record["relationship"], label=person_record.get("label", ""),
            enrolled=bool(person_record.get("consent", {}).get("voice")), last_seen=person_record.get("last_seen"),
        )
    memories = await database[MEMORIES].find({
        "user_id": user_id, "status": "active", "person_id": {"$in": [person_id, "global"]},
    }).sort("created_at", -1).to_list(length=200)
    episodes = [Memory.model_validate(item) for item in memories if item.get("kind") == "episode" and item.get("person_id") == person_id]
    # "Your usual phrases with them" is per partner only; global seed phrases are not theirs.
    phrases = sorted(
        (Memory.model_validate(item) for item in memories
         if item.get("kind") == "phrase" and item.get("person_id") == person_id),
        key=lambda memory: memory.uses, reverse=True,
    )
    facts = [Memory.model_validate(item) for item in memories if item.get("kind") == "fact"]
    open_threads: list[OpenThread] = []
    for episode in episodes:
        open_threads.extend(thread for thread in episode.open_threads if thread.status == "open")
    active_rules = await get_active_boundaries(user_id, relationship, person_id)
    return RetrievedContext(
        person=person_out, recent_episodes=episodes[:5], relevant_episodes=episodes[:5],
        open_threads=open_threads, phrases=phrases[:12], facts=facts[:12], boundaries=active_rules,
    )
