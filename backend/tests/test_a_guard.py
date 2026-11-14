"""Lane A: deterministic guard (docs/05-guardrails.md §1). Pure, no I/O."""
from app.contracts import Boundary, BoundaryScope, Candidate, PersonOut
from app.guard.enforce import apply_guard, blocked_topics, tag_topics_safety_net

MIKE = PersonOut(id="per_mike", name="Mike", relationship="acquaintance")
DANA = PersonOut(id="per_dana", name="Dana", relationship="clinician")

ACQ_HEALTH = Boundary(_id="bnd_acq", user_id="usr_maya", status="active",
                      scope=BoundaryScope(type="relationship", value="acquaintance"),
                      topics=["health", "medication"])
STRANGER_ALL = Boundary(_id="bnd_str", user_id="usr_maya", status="active",
                        scope=BoundaryScope(type="relationship", value="stranger"),
                        topics=["health", "medication", "finances"])


def _c(text, topics):
    return Candidate(text=text, topics=topics)


def test_acquaintance_rule_blocks_meds():
    cands = [_c("Doing alright, thanks.", ["small_talk"]),
             _c("Honestly the new meds are rough.", ["health", "medication"])]
    allowed, blocked = apply_guard(cands, MIKE, [ACQ_HEALTH])
    assert [c.text for c in allowed] == ["Doing alright, thanks."]
    assert blocked[0].blocked and blocked[0].blocked_by == "bnd_acq"


def test_clinician_not_blocked_by_acquaintance_rule():
    cands = [_c("Yes please, same refill as October.", ["medication"])]
    allowed, blocked = apply_guard(cands, DANA, [ACQ_HEALTH])
    assert len(allowed) == 1 and not blocked


def test_safety_net_catches_mislabelled_meds():
    cands = [_c("I need to pick up my meds later.", ["small_talk"])]
    allowed, blocked = apply_guard(cands, MIKE, [ACQ_HEALTH])
    assert not allowed and blocked[0].blocked_by == "bnd_acq"
    assert "medication" in blocked[0].topics


def test_unknown_speaker_is_stranger():
    allowed, blocked = apply_guard([_c("My ALS makes talking slow.", [])], None, [STRANGER_ALL])
    assert not allowed and blocked[0].blocked_by == "bnd_str"


def test_person_and_global_scope_and_inactive():
    per = Boundary(_id="bnd_p", user_id="u", status="active",
                   scope=BoundaryScope(type="person", value="per_mike"), topics=["finances"])
    glob = Boundary(_id="bnd_g", user_id="u", status="active",
                    scope=BoundaryScope(type="global"), topics=["legal"])
    proposed = Boundary(_id="bnd_x", user_id="u", status="proposed",
                        scope=BoundaryScope(type="global"), topics=["small_talk"])
    cands = [_c("Rent is due Friday.", []), _c("Talked to my lawyer.", []), _c("Nice day!", ["small_talk"])]
    allowed, blocked = apply_guard(cands, MIKE, [per, glob, proposed])
    assert [c.text for c in allowed] == ["Nice day!"]
    assert {c.blocked_by for c in blocked} == {"bnd_p", "bnd_g"}
    # person rule doesn't apply to Dana
    allowed, _ = apply_guard(cands[:1], DANA, [per])
    assert len(allowed) == 1


def test_top4_preserves_rank_and_is_deterministic():
    cands = [_c(f"Option {i}", ["small_talk"]) for i in range(6)]
    a1, _ = apply_guard(cands, MIKE, [ACQ_HEALTH])
    a2, _ = apply_guard(cands, MIKE, [ACQ_HEALTH])
    assert [c.text for c in a1] == [f"Option {i}" for i in range(4)]
    assert [c.model_dump() for c in a1] == [c.model_dump() for c in a2]


def test_safety_net_no_false_positive_on_small_talk():
    assert tag_topics_safety_net("How's the dog doing?", ["small_talk"]) == ["small_talk"]
    assert "finances" in tag_topics_safety_net("That was $40!", [])


def test_blocked_topics_for_prompt():
    assert blocked_topics(MIKE, [ACQ_HEALTH]) == ["health", "medication"]
    assert blocked_topics(DANA, [ACQ_HEALTH]) == []
