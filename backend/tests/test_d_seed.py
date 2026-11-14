import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_demo_seed_has_three_opt_in_safe_partners_and_scoped_memory():
    people = json.loads((ROOT / "seed/people.json").read_text())
    memories = json.loads((ROOT / "seed/memories.json").read_text())
    boundaries = json.loads((ROOT / "seed/boundaries.json").read_text())

    assert {person["_id"] for person in people} == {"per_dana", "per_sam", "per_mike"}
    assert all(person["consent"]["voice"] is False for person in people)
    assert {memory["person_id"] for memory in memories} >= {"per_dana", "per_sam", "per_mike", "global"}
    assert any("blister pack" in thread["text"] for item in memories for thread in item.get("open_threads", []))
    assert all(boundary["scope"]["value"] != "acquaintance" for boundary in boundaries)
