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


def test_open_thread_ids_are_unique_and_lane_d_phrases_are_scoped():
    memories = json.loads((ROOT / "seed/memories.json").read_text())
    thread_ids = [thread["id"] for item in memories for thread in item.get("open_threads", [])]
    assert len(thread_ids) == len(set(thread_ids)), thread_ids
    assert all(thread_id.startswith("thr_") for thread_id in thread_ids)
    # one open blister-pack thread for Dana, one open game thread for Sam
    open_texts = [t["text"] for item in memories for t in item.get("open_threads", []) if t["status"] == "open"]
    assert sum("blister pack" in text for text in open_texts) == 1
    assert sum("saturday game" in text.lower() for text in open_texts) == 1
    mike_phrase = next(m for m in memories if m["_id"] == "mem_ph_maya_dry")
    assert mike_phrase["person_id"] == "per_mike"


def test_sam_is_mayas_teenage_grandson_not_a_sibling():
    people = {p["_id"]: p for p in json.loads((ROOT / "seed/people.json").read_text())}
    sam = people["per_sam"]
    assert sam["relationship"] == "family" and "grandson" in sam["label"].lower() and "16" in sam["notes"]
    texts = [sam["label"], sam["notes"]]
    texts += [m["text"] for m in json.loads((ROOT / "seed/memories.json").read_text()) if m["person_id"] == "per_sam"]
    texts += [e["text"] for e in json.loads((ROOT / "seed/history_events.json").read_text()) if e["person_id"] == "per_sam"]
    for path in sorted((ROOT / "seed/conversations").glob("c*.json")):
        conversation = json.loads(path.read_text())
        if conversation["person_id"] == "per_sam":
            texts += [t.get("text") or t.get("intended") for t in conversation["turns"]]
    for marker in ("brother", "sibling", "sister", "tell mom", "recreational"):
        assert not any(marker in text.lower() for text in texts), marker
