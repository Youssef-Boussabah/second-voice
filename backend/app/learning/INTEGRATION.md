# Lane A integration

Before calling `apply_guard`, fetch persisted rules with:

```python
active_boundaries = await app.learning.boundaries.get_active_boundaries(
    user_id=utterance.user_id,
    relationship=person.relationship.value if person else "stranger",
    person_id=person.id if person else None,
)
allowed, blocked = app.guard.enforce.apply_guard(candidates, person, active_boundaries)
```

The lookup includes active global, relationship, and person rules. It performs MongoDB I/O; call it in the async pipeline path. `propose_and_validate(event)` persists a learned boundary when rejection replay permits activation, or a `proposed` boundary when prior replies conflict.
