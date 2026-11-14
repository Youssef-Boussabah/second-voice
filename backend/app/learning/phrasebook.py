"""Learn Maya's own reply wording from selection and typed-reply events."""
from datetime import datetime, timezone

import numpy as np

from app.contracts import Event, new_id
from app.db import EVENTS, MEMORIES, SUGGESTION_SETS, db
from app.embeddings import embed


async def learn_phrase(evt: Event) -> str | None:
    if evt.type not in {"suggestion_selected", "suggestion_edited", "reply_typed"}:
        return None
    text = (evt.text or "").strip()
    if evt.type == "suggestion_selected" and evt.suggestion_set_id and evt.candidate_id:
        suggestion = await db()[SUGGESTION_SETS].find_one(
            {"_id": evt.suggestion_set_id, "user_id": evt.user_id}
        )
        if suggestion:
            candidate = next((item for item in suggestion.get("candidates", []) if item.get("id") == evt.candidate_id), None)
            if candidate:
                text = candidate.get("text", text)
    if not text or not evt.person_id:
        return None

    vector = (await embed([text], "document"))[0]
    collection = db()[MEMORIES]
    existing = await collection.find({
        "user_id": evt.user_id, "person_id": evt.person_id, "kind": "phrase", "status": "active",
        "embedding": {"$exists": True},
    }).to_list(length=500)
    match = None
    for memory in existing:
        prior = memory.get("embedding") or []
        if len(prior) != len(vector):
            continue
        similarity = float(np.dot(vector, prior) / (np.linalg.norm(vector) * np.linalg.norm(prior)))
        if similarity >= 0.92:
            match = memory
            break

    now = datetime.now(timezone.utc)
    if match:
        await collection.update_one({"_id": match["_id"]}, {"$inc": {"uses": 1}, "$set": {"last_used": now}})
        return match["_id"]
    result = await collection.insert_one({
        "_id": new_id("mem"), "user_id": evt.user_id, "person_id": evt.person_id,
        "kind": "phrase", "status": "active", "text": text, "topics": [str(topic) for topic in evt.topics],
        "uses": 1, "last_used": now, "origin": evt.type, "embedding": vector, "created_at": now,
    })
    return result.inserted_id
