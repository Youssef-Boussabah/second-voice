"""Lane D: reset-demo only removes lane-d learned docs + demo sessions/events, then re-seeds."""
import os

os.environ.setdefault("MOCK_EMBED", "true")
os.environ.setdefault("MOCK_LLM", "true")

from app.contracts import Event, EventType, RejectReason  # noqa: E402
from app.learning import boundaries as boundaries_mod, demo_seed, phrasebook  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402

DEMO = "usr_maya"


async def _state(monkeypatch):
    database = FakeDB()
    for module in (phrasebook, boundaries_mod):
        monkeypatch.setattr(module, "db", lambda: database)
    await demo_seed.apply_seed(database, dry_run=False)
    # runtime learning on the demo user
    await phrasebook.learn_phrase(Event(user_id=DEMO, type=EventType.reply_typed, person_id="per_dana",
                                        text="Thanks Dana, see you Friday"))
    await phrasebook.learn_phrase(Event(user_id=DEMO, type=EventType.reply_typed, person_id="per_sam",
                                        text="Proud of you, bud."))  # bumps the seed phrase's uses
    learned = await boundaries_mod.propose_and_validate(Event(
        user_id=DEMO, type=EventType.suggestion_rejected, person_id="per_mike", relationship="acquaintance",
        text="The new meds are rough.", topics=["medication"], reason=RejectReason.too_personal))
    assert learned and learned.status == "active"
    await database["sessions"].insert_one({"_id": "ses_demo1", "user_id": DEMO})
    await database["events"].insert_one({"_id": "evt_demo1", "user_id": DEMO, "type": "session_started"})
    # legacy (pre-tag) lane-d learned docs are still cleared by provenance
    await database["boundaries"].insert_one({"_id": "bnd_legacy", "user_id": DEMO, "origin": "learned",
                                             "status": "active", "scope": {"type": "relationship", "value": "acquaintance"}})
    await database["memories"].insert_one({"_id": "mem_legacy", "user_id": DEMO, "person_id": "per_dana",
                                           "kind": "phrase", "origin": "reply_typed", "text": "legacy"})
    # things reset must never touch
    await database["memories"].insert_one({"_id": "mem_laneA", "user_id": DEMO, "person_id": "per_dana",
                                           "kind": "episode", "text": "written by someone else"})
    await database["memories"].insert_one({"_id": "mem_other", "user_id": "usr_other", "written_by": "lane-d",
                                           "kind": "phrase", "text": "other user"})
    await database["sessions"].insert_one({"_id": "ses_other", "user_id": "usr_other"})
    await database["events"].insert_one({"_id": "evt_other", "user_id": "usr_other", "type": "session_started"})
    # runtime fields on seed docs that must survive
    await database["memories"].update_one({"_id": "mem_ph_sam_bud"}, {"$set": {"embedding": [0.1, 0.2]}})
    await database["people"].update_one({"_id": "per_sam"}, {"$set": {"consent": {"voice": True}}})
    return database


async def test_dry_run_reports_and_writes_nothing(monkeypatch):
    database = await _state(monkeypatch)
    before = {name: [dict(d) for d in coll.docs] for name, coll in database.items()}
    result = await demo_seed.reset_demo(database, dry_run=True, user_id=DEMO)
    assert result["ok"] and result["dry_run"]
    assert result["deleted"] == {"memories": 2, "boundaries": 2, "events": 1, "sessions": 1}
    assert {name: coll.docs for name, coll in database.items()} == before


async def test_reset_deletes_only_learned_and_demo_docs_then_restores_seed(monkeypatch):
    database = await _state(monkeypatch)
    result = await demo_seed.reset_demo(database, dry_run=False, user_id=DEMO)
    assert result["deleted"] == {"memories": 2, "boundaries": 2, "events": 1, "sessions": 1}
    memory_ids = {d["_id"] for d in database["memories"].docs}
    assert {"mem_laneA", "mem_other", "mem_ph_sam_bud"} <= memory_ids
    assert {d["_id"] for d in database["sessions"].docs} == {"ses_other"}
    assert "evt_other" in {d["_id"] for d in database["events"].docs}
    assert all(d.get("origin") == "seed" for d in database["boundaries"].docs)
    bud = next(d for d in database["memories"].docs if d["_id"] == "mem_ph_sam_bud")
    assert bud["uses"] == 7 and bud["embedding"] == [0.1, 0.2] and "last_used" not in bud
    sam = next(d for d in database["people"].docs if d["_id"] == "per_sam")
    assert sam["consent"] == {"voice": True}
    seeded_events = [d for d in database["events"].docs if d["user_id"] == DEMO]
    assert len(seeded_events) == 25 and all(d["seed_source"] == "lane-d" for d in seeded_events)

    again = await demo_seed.reset_demo(database, dry_run=False, user_id=DEMO)
    assert again["deleted"] == {"memories": 0, "boundaries": 0, "events": 0, "sessions": 0}
    assert all(counts["insert"] == 0 for counts in again["seed"].values())


async def test_seed_never_overwrites_a_document_owned_by_another_lane():
    database = FakeDB()
    await database["people"].insert_one({"_id": "per_dana", "user_id": DEMO, "name": "Lane B Dana"})
    report = await demo_seed.apply_seed(database, dry_run=False)
    assert report["people"]["skip_not_owned"] == 1
    assert database["people"].docs[0]["name"] == "Lane B Dana"
