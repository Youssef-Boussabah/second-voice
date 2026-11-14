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
