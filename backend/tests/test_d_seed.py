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


def test_frozen_eval_fixture_has_train_and_test_for_every_partner():
    conversations = [
        json.loads(path.read_text())
        for path in sorted((ROOT / "seed/conversations").glob("c*.json"))
    ]
    assert len(conversations) == 8
    assert {item["id"] for item in conversations if item["split"] == "test"} == {"c06", "c07", "c08"}
    for person_id in {"per_dana", "per_sam", "per_mike"}:
        splits = {item["split"] for item in conversations if item["person_id"] == person_id}
        assert splits == {"train", "test"}
    assert all(len(item["turns"]) % 2 == 0 for item in conversations)


def test_seed_documents_have_deterministic_ids_and_unconsented_voice_defaults():
    datasets = ["people.json", "memories.json", "boundaries.json", "history_events.json"]
    for filename in datasets:
        documents = json.loads((ROOT / "seed" / filename).read_text())
        ids = [item["_id"] for item in documents]
        assert len(ids) == len(set(ids))
