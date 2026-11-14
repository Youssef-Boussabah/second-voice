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
from app.learning.demo_seed import LEARNED_TAG


# DECISION: the LLM and the guard's keyword net tag "health" and "medication" independently
# (guard/enforce.py keeps them apart on purpose), so a card tagged only "health" that is rejected
# as too personal would leave "The meds are doing their job" unblocked for the same person.
# Measured live 2026-11-14 with Mike. A too_personal rejection on either topic learns both.
TOPIC_FAMILIES: tuple[frozenset[str], ...] = (frozenset({"health", "medication"}),)


def _learnable_topics(topics: list[str]) -> set[str]:
    out = set(topics) & SENSITIVE_TOPICS
    for family in TOPIC_FAMILIES:
        if out & family:
            out |= family
    return out


async def propose_and_validate(evt: Event) -> Boundary | None:
    """Learn a narrow rule only after checking the user's prior replies."""
    wanted = _learnable_topics(list(evt.topics))
    if evt.reason != "too_personal" or not wanted or not evt.relationship:
        return None
    database = db()
    existing = await database[BOUNDARIES].find({
        "user_id": evt.user_id,
        "status": "active",
        "topics": {"$in": sorted(wanted)},
        "$or": [
            {"scope": {"type": "global", "value": None}},
            {"scope": {"type": "relationship", "value": evt.relationship}},
            {"scope": {"type": "person", "value": evt.person_id}},
        ],
    }).to_list(length=500)
    covered = {topic for record in existing for topic in record.get("topics", [])}
    topics = sorted(wanted - covered)   # only learn what no active rule already blocks
    if not topics:
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
    await database[BOUNDARIES].insert_one(boundary.to_mongo() | LEARNED_TAG)
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
