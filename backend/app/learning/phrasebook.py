"""Learn Maya's own reply wording from selection and typed-reply events.

Phrases are strictly per partner: a phrase learned while talking to Mike is stored with
person_id=per_mike and is only ever matched/deduped against Mike's phrases. Learning never
writes person_id="global" (globals are hand-curated seed phrases only).
"""
import logging
import time
from datetime import datetime, timezone

import numpy as np

from app.contracts import Event, new_id
from app.db import MEMORIES, SUGGESTION_SETS, db
from app.embeddings import embed

log = logging.getLogger(__name__)

PHRASE_EVENTS = {"suggestion_selected", "suggestion_edited", "reply_typed"}
SIMILARITY_THRESHOLD = 0.92
ORIGIN = {"suggestion_selected": "selected", "suggestion_edited": "edited", "reply_typed": "typed"}


def _event_type(evt: Event) -> str:
    return evt.type.value if hasattr(evt.type, "value") else str(evt.type)


async def learn_phrase(evt: Event) -> str | None:
    started = time.perf_counter()
    if _event_type(evt) not in PHRASE_EVENTS:
        return None
    text = (evt.text or "").strip()
    person_id = evt.person_id
    if evt.suggestion_set_id:
        suggestion = await db()[SUGGESTION_SETS].find_one(
            {"_id": evt.suggestion_set_id, "user_id": evt.user_id}
        )
        if suggestion:
            # DECISION: the suggestion set records who the card was generated for; it wins over
            # the event's person_id so a stale UI selection can't file Mike's phrase under Dana.
            if suggestion.get("person_id"):
                if person_id and person_id != suggestion["person_id"]:
                    log.warning("phrase event %s person %s != suggestion set person %s; using set",
                                evt.id, person_id, suggestion["person_id"])
                person_id = suggestion["person_id"]
            if _event_type(evt) == "suggestion_selected" and evt.candidate_id:
                candidate = next((item for item in suggestion.get("candidates", [])
                                  if item.get("id") == evt.candidate_id), None)
                if candidate:
                    text = candidate.get("text", text)
    if not text or not person_id or person_id == "global" or not person_id.startswith("per_"):
        log.info("phrase skipped evt=%s person=%s (no partner scope)", evt.id, person_id)
        return None

    vector = (await embed([text], "document"))[0]
    collection = db()[MEMORIES]
    existing = await collection.find({
        "user_id": evt.user_id, "person_id": person_id, "kind": "phrase", "status": "active",
    }).to_list(length=500)
    match = None
    for memory in existing:
        if memory.get("text", "").strip().lower() == text.lower():
            match = memory
            break
        prior = memory.get("embedding") or []
        if len(prior) != len(vector):
            continue
        denom = float(np.linalg.norm(vector) * np.linalg.norm(prior)) or 1.0
        if float(np.dot(vector, prior)) / denom >= SIMILARITY_THRESHOLD:
            match = memory
            break

    now = datetime.now(timezone.utc)
    if match:
        await collection.update_one({"_id": match["_id"], "person_id": person_id},
                                    {"$inc": {"uses": 1}, "$set": {"last_used": now}})
        log.info("phrase reuse mem=%s person=%s %dms", match["_id"], person_id,
                 (time.perf_counter() - started) * 1000)
        return match["_id"]
    memory_id = new_id("mem")
    await collection.insert_one({
        "_id": memory_id, "user_id": evt.user_id, "person_id": person_id,
        "kind": "phrase", "status": "active", "text": text, "topics": [str(getattr(t, "value", t)) for t in evt.topics],
        "uses": 1, "last_used": now, "origin": ORIGIN[_event_type(evt)], "source_event_id": evt.id,
        "embedding": vector, "created_at": now,
    })
    log.info("phrase new mem=%s person=%s %dms", memory_id, person_id, (time.perf_counter() - started) * 1000)
    return memory_id
