"""Persist and validate learned privacy boundaries."""
from datetime import datetime, timezone

from app.contracts import (
    SENSITIVE_TOPICS,
    Boundary,
    BoundaryEvidence,
    BoundaryScope,
    BoundaryValidation,
    Event,
    new_id,
)
from app.db import BOUNDARIES, EVENTS, db


async def propose_and_validate(evt: Event) -> Boundary | None:
    """Learn a narrow rule only after checking the user's prior replies."""
    topics = sorted(set(evt.topics) & SENSITIVE_TOPICS)
    if evt.reason != "too_personal" or not topics or not evt.relationship:
        return None
    database = db()
    existing = await database[BOUNDARIES].find_one({
        "user_id": evt.user_id,
        "status": "active",
        "topics": {"$in": topics},
        "$or": [
            {"scope": {"type": "global", "value": None}},
            {"scope": {"type": "relationship", "value": evt.relationship}},
            {"scope": {"type": "person", "value": evt.person_id}},
        ],
    })
    if existing:
        return None

    history = await database[EVENTS].find({
        "user_id": evt.user_id,
        "type": {"$in": ["suggestion_selected", "suggestion_edited", "reply_typed"]},
        "relationship": evt.relationship,
    }).to_list(length=10000)
    conflicts = [record for record in history if set(record.get("topics", [])) & set(topics)]
    scope = BoundaryScope(type="relationship", value=evt.relationship)
    narrowed_from = None
    chosen_conflicts = conflicts
    if conflicts:
        scope = BoundaryScope(type="person", value=evt.person_id)
        narrowed_from = "relationship"
        chosen_conflicts = [record for record in conflicts if record.get("person_id") == evt.person_id]

    status = "active" if not chosen_conflicts else "proposed"
    now = datetime.now(timezone.utc)
    boundary = Boundary(
        id=new_id("bnd"), user_id=evt.user_id, scope=scope, topics=topics,
        status=status, origin="learned",
        evidence=BoundaryEvidence(trigger_event_id=evt.id, rejected_text=evt.text, person_id=evt.person_id),
        validation=BoundaryValidation(
            replayed=len(history) if narrowed_from is None else len([h for h in history if h.get("person_id") == evt.person_id]),
            conflicts=len(chosen_conflicts),
            conflict_event_ids=[record["_id"] for record in chosen_conflicts],
            passed=not chosen_conflicts,
            narrowed_from=narrowed_from,
        ),
        created_at=now,
        activated_at=now if status == "active" else None,
    )
    await database[BOUNDARIES].insert_one(boundary.to_mongo())
    return boundary


async def get_active_boundaries(user_id: str, relationship: str, person_id: str | None) -> list[Boundary]:
    """Enforcement hook for Lane A: fetch active global, relationship, and person rules."""
    records = await db()[BOUNDARIES].find({
        "user_id": user_id,
        "status": "active",
        "$or": [
            {"scope.type": "global"},
            {"scope.type": "relationship", "scope.value": relationship},
            {"scope.type": "person", "scope.value": person_id},
        ],
    }).to_list(length=500)
    return [Boundary.model_validate(record) for record in records]
