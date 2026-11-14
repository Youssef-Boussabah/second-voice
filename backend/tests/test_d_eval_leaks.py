"""Lane D: privacy leak = candidate topic blocked by a rule that applies to THAT partner."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MOCK_EMBED", "true")
os.environ.setdefault("MOCK_LLM", "true")

import pytest  # noqa: E402

from app.contracts import Candidate, Event, EventType, RejectReason  # noqa: E402
from app.learning import boundaries as boundaries_mod  # noqa: E402
from test_d_fakedb import FakeDB  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))
from leaks import blocked_topics_for, count_leaks, is_leak, load_privacy_truth  # noqa: E402

USER = "usr_maya"
MEDS = Candidate(text="The new meds are rough this week.", topics=["medication", "health"])
SMALL = Candidate(text="How's the dog?", topics=["small_talk"])


@pytest.fixture()
def fake_db(monkeypatch):
    database = FakeDB()
    monkeypatch.setattr(boundaries_mod, "db", lambda: database)
    return database


async def test_dana_medication_is_not_a_leak(fake_db):
    rules = await boundaries_mod.get_active_boundaries(USER, "clinician", "per_dana")
    blocked = blocked_topics_for("clinician", "per_dana", rules, load_privacy_truth())
    assert not is_leak(MEDS, blocked)
    assert count_leaks([MEDS, SMALL], blocked) == 0


async def test_mike_medication_after_too_personal_rejection_is_a_leak(fake_db):
    rejection = Event(user_id=USER, type=EventType.suggestion_rejected, person_id="per_mike",
                      relationship="acquaintance", text=MEDS.text, topics=["medication", "health"],
                      reason=RejectReason.too_personal)
    learned = await boundaries_mod.propose_and_validate(rejection)
    assert learned is not None and learned.status == "active"

    mike_rules = await boundaries_mod.get_active_boundaries(USER, "acquaintance", "per_mike")
    # even with no hidden ground truth, the learned rule alone makes it a leak for Mike
    assert is_leak(MEDS, blocked_topics_for("acquaintance", "per_mike", mike_rules, truth={}))
    assert count_leaks([MEDS, SMALL], blocked_topics_for("acquaintance", "per_mike", mike_rules)) == 1

    # ...and the Mike rule never turns Dana's medication talk into a leak
    dana_rules = await boundaries_mod.get_active_boundaries(USER, "clinician", "per_dana")
    assert not is_leak(MEDS, blocked_topics_for("clinician", "per_dana", dana_rules, truth={}))


def test_scope_rules_person_relationship_global_and_inactive():
    person_rule = {"scope": {"type": "person", "value": "per_mike"}, "topics": ["finances"], "status": "active"}
    proposed = {"scope": {"type": "global", "value": None}, "topics": ["legal"], "status": "proposed"}
    global_rule = {"scope": {"type": "global", "value": None}, "topics": ["romance"], "status": "active"}
    rules = [person_rule, proposed, global_rule]
    assert blocked_topics_for("acquaintance", "per_mike", rules, truth={}) == {"finances", "romance"}
    assert blocked_topics_for("acquaintance", "per_other", rules, truth={}) == {"romance"}


def test_scoreboard_notes_name_real_models_and_flag_mock():
    from app.api.learning_routes import _scoreboard_notes
    real = {"cold": {"label": "REAL", "models": {"suggest_model": "Qwen/Qwen3-30B-A3B-Instruct-2507",
                                                "summary_model": "zai-org/GLM-5.3-Flash", "embed_model": "voyage-4-lite"}}}
    notes = _scoreboard_notes(real)
    assert notes.startswith("REAL") and "Qwen/Qwen3-30B-A3B-Instruct-2507" in notes and "GLM-5.3-Flash" in notes
    assert _scoreboard_notes({"cold": {"label": "MOCK"}}).startswith("MOCK")


async def test_health_only_rejection_also_blocks_medication_and_dedupes(fake_db):
    """Live 2026-11-14: Mike's rejected card was tagged only `health`; the next round leaked
    `medication` ("The meds are doing their job"). The learned rule must cover both, once."""
    from app.contracts import PersonOut
    from app.guard.enforce import apply_guard

    def reject(text, topics):
        return boundaries_mod.propose_and_validate(Event(
            user_id=USER, type=EventType.suggestion_rejected, person_id="per_mike",
            relationship="acquaintance", text=text, topics=topics, reason=RejectReason.too_personal))

    learned = await reject("Still adjusting. The dog's chewing boots again.", ["health", "humour"])
    assert learned is not None and learned.status == "active"
    assert set(learned.topics) == {"health", "medication"}
    assert await reject("The meds are a work in progress.", ["medication"]) is None   # no duplicate

    mike = PersonOut(id="per_mike", name="Mike", relationship="acquaintance")
    rules = await boundaries_mod.get_active_boundaries(USER, "acquaintance", "per_mike")
    allowed, blocked = apply_guard(
        [Candidate(text="The meds are doing their job, I suppose.", topics=["humour", "medication"]), SMALL],
        mike, rules)
    assert [c.text for c in allowed] == [SMALL.text] and len(blocked) == 1

    # a different sensitive topic is still learnable alongside the existing rule
    extra = await reject("Money's tight this month.", ["finances", "health"])
    assert extra is not None and extra.topics == ["finances"]


async def test_person_context_hides_memories_on_blocked_topics(fake_db, monkeypatch):
    """Live 2026-11-14: Mike's header kept a medication open thread after the rule was learned."""
    from app.learning import memory as memory_mod
    monkeypatch.setattr(memory_mod, "db", lambda: fake_db)
    await fake_db["people"].insert_one({"_id": "per_mike", "user_id": USER, "name": "Mike", "relationship": "acquaintance"})
    await fake_db["people"].insert_one({"_id": "per_dana", "user_id": USER, "name": "Dana", "relationship": "clinician"})
    thread = {"id": "thr_1", "text": "Partner awaiting Maya's update on how the new medication is working",
              "owner": "user", "status": "open"}
    for pid in ("per_mike", "per_dana"):
        await fake_db["memories"].insert_one({"_id": f"mem_ep_{pid}", "user_id": USER, "person_id": pid, "kind": "episode",
                                              "status": "active", "text": "Asked how Maya has been feeling.",
                                              "topics": ["small_talk"], "open_threads": [thread]})
    await fake_db["memories"].insert_one({"_id": "mem_ph_ok", "user_id": USER, "person_id": "per_mike", "kind": "phrase",
                                          "status": "active", "text": "How's the dog?", "topics": ["small_talk"]})
    await fake_db["memories"].insert_one({"_id": "mem_ph_meds", "user_id": USER, "person_id": "per_mike", "kind": "phrase",
                                          "status": "active", "text": "The meds are rough.", "topics": []})
    learned = await boundaries_mod.propose_and_validate(Event(
        user_id=USER, type=EventType.suggestion_rejected, person_id="per_mike", relationship="acquaintance",
        text="The meds are a work in progress.", topics=["medication"], reason=RejectReason.too_personal))
    assert learned is not None

    mike = await memory_mod.retrieve_person_context(USER, "per_mike", "acquaintance")
    assert mike.open_threads == [] and [m.text for m in mike.phrases] == ["How's the dog?"]
    assert [e.id for e in mike.recent_episodes] == ["mem_ep_per_mike"]   # the episode itself is safe
    dana = await memory_mod.retrieve_person_context(USER, "per_dana", "clinician")
    assert [t.id for t in dana.open_threads] == ["thr_1"]                # clinician keeps medication context
