"""Learn Maya's own reply wording from selection and typed-reply events.

Phrases are strictly per partner: a phrase learned while talking to Mike is stored with
person_id=per_mike and is only ever matched/deduped against Mike's phrases. Learning never
writes person_id="global" (globals are hand-curated seed phrases only).
"""
import hashlib
import logging
import time
from datetime import datetime, timezone

import numpy as np
from pymongo.errors import DuplicateKeyError

from app.contracts import Event
from app.db import MEMORIES, SUGGESTION_SETS, db
from app.learning.safe_embed import embed_document_or_none
from app.learning.demo_seed import LEARNED_TAG

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

    vector = await embed_document_or_none(text)
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
        if vector is None or len(prior) != len(vector):
            continue
        denom = float(np.linalg.norm(vector) * np.linalg.norm(prior)) or 1.0
        if float(np.dot(vector, prior)) / denom >= SIMILARITY_THRESHOLD:
            match = memory
            break

    if match:
        await _count_use(collection, match["_id"], person_id, evt.id)
        log.info("phrase reuse mem=%s person=%s %dms", match["_id"], person_id,
                 (time.perf_counter() - started) * 1000)
        return match["_id"]
    now = datetime.now(timezone.utc)
    memory_id = phrase_id(evt.user_id, person_id, text)
    document = {
        "_id": memory_id, "user_id": evt.user_id, "person_id": person_id,
        "kind": "phrase", "status": "active", "text": text, "topics": [str(getattr(t, "value", t)) for t in evt.topics],
        "uses": 1, "last_used": now, "origin": ORIGIN[_event_type(evt)], "source_event_id": evt.id,
        "learning_events": [evt.id], "embedding": vector, "created_at": now, **LEARNED_TAG,
    }
    if vector is None:
        document.pop("embedding")
    try:
        await collection.insert_one(document)
    except DuplicateKeyError:
        # same phrase inserted concurrently (another event or a retry of this one): count once
        await _count_use(collection, memory_id, person_id, evt.id)
        return memory_id
    log.info("phrase new mem=%s person=%s %dms", memory_id, person_id, (time.perf_counter() - started) * 1000)
    return memory_id


def phrase_id(user_id: str, person_id: str, text: str) -> str:
    """Deterministic id per (user, partner, normalized wording): two writers of the same new
    phrase collide on _id instead of creating duplicates."""
    key = f"{user_id}|{person_id}|{' '.join(text.lower().split())}"
    return "mem_ph_" + hashlib.sha1(key.encode()).hexdigest()[:16]


async def _count_use(collection, memory_id: str, person_id: str, event_id: str) -> bool:
    """+1 use, at most once per event (a retried event finds its id in learning_events)."""
    result = await collection.update_one(
        {"_id": memory_id, "person_id": person_id, "learning_events": {"$ne": event_id}},
        {"$inc": {"uses": 1}, "$set": {"last_used": datetime.now(timezone.utc)},
         "$push": {"learning_events": {"$each": [event_id], "$slice": -200}}},
    )
    return result.modified_count == 1
