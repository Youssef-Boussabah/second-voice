"""Lane D: phrases are learned and surfaced strictly per partner (Dana never sees Mike's)."""
import json
import os
from pathlib import Path

os.environ.setdefault("MOCK_EMBED", "true")
os.environ.setdefault("MOCK_LLM", "true")

import pytest  # noqa: E402

from app.contracts import Event, EventType  # noqa: E402
from app.learning import boundaries as boundaries_mod, memory as memory_mod, phrasebook  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
USER = "usr_maya"


@pytest.fixture()
def fake_db(monkeypatch):
    database = FakeDB()
    for module in (phrasebook, memory_mod, boundaries_mod):
        monkeypatch.setattr(module, "db", lambda: database)
    return database


async def test_mike_phrase_is_not_learned_or_shown_for_dana(fake_db):
    for person_id, relationship in (("per_mike", "acquaintance"), ("per_dana", "clinician")):
        await fake_db["people"].insert_one({"_id": person_id, "user_id": USER, "name": person_id,
                                             "relationship": relationship})
    mike_text = "Living the glamorous elevator-lobby life, obviously."
    await phrasebook.learn_phrase(Event(user_id=USER, type=EventType.reply_typed, person_id="per_mike",
                                        relationship="acquaintance", text=mike_text))
    # same words later typed to Dana must create Dana's own phrase, not bump Mike's
    await phrasebook.learn_phrase(Event(user_id=USER, type=EventType.reply_typed, person_id="per_dana",
                                        relationship="clinician", text="Thanks Dana, see you Friday"))
    phrases = fake_db["memories"].docs
    assert {(p["person_id"], p["text"]) for p in phrases} == {
        ("per_mike", mike_text), ("per_dana", "Thanks Dana, see you Friday")}
    assert all(p["person_id"] != "global" for p in phrases)

    dana = await memory_mod.retrieve_person_context(USER, "per_dana", "clinician")
    mike = await memory_mod.retrieve_person_context(USER, "per_mike", "acquaintance")
    assert [p.text for p in dana.phrases] == ["Thanks Dana, see you Friday"]
    assert [p.text for p in mike.phrases] == [mike_text]


async def test_repeat_phrase_bumps_uses_within_same_person_only(fake_db):
    evt = dict(user_id=USER, type=EventType.reply_typed, text="See you Friday")
    first = await phrasebook.learn_phrase(Event(person_id="per_dana", **evt))
    again = await phrasebook.learn_phrase(Event(person_id="per_dana", **evt))
    other = await phrasebook.learn_phrase(Event(person_id="per_mike", **evt))
    assert first == again != other
    docs = {d["_id"]: d for d in fake_db["memories"].docs}
    assert docs[first]["uses"] == 2 and docs[other]["uses"] == 1


async def test_suggestion_set_person_wins_and_global_is_never_learned(fake_db):
    await fake_db["suggestion_sets"].insert_one({
        "_id": "sug_x", "user_id": USER, "person_id": "per_mike",
        "candidates": [{"id": "cand_1", "text": "How's the dog?"}]})
    learned = await phrasebook.learn_phrase(Event(
        user_id=USER, type=EventType.suggestion_selected, person_id="per_dana",
        suggestion_set_id="sug_x", candidate_id="cand_1"))
    assert fake_db["memories"].docs[0]["person_id"] == "per_mike" and learned
    assert await phrasebook.learn_phrase(Event(user_id=USER, type=EventType.reply_typed,
                                               person_id="global", text="hi")) is None
    assert await phrasebook.learn_phrase(Event(user_id=USER, type=EventType.reply_typed, text="hi")) is None


def test_seed_global_phrases_are_partner_neutral():
    memories = json.loads((ROOT / "seed/memories.json").read_text())
    global_phrases = [m["text"].lower() for m in memories if m["kind"] == "phrase" and m["person_id"] == "global"]
    for marker in ("dana", "sam", "mike", "bud", "elevator", "dog", "refill", "leafs"):
        assert not any(marker in text for text in global_phrases), marker
