"""Lane A smoke test: sessions → text utterance → WS suggestions.ready (4 cards) → select → reject.

Runs with all mocks on against an isolated database (`second_voice_test`) on the configured
MONGODB_URI. Skips cleanly if MongoDB isn't reachable.
"""
import os

os.environ.update({k: "true" for k in ["MOCK_LLM", "MOCK_EMBED", "MOCK_STT", "MOCK_SPEAKER", "MOCK_TTS"]})
os.environ["USE_CHANGE_STREAMS"] = "false"
os.environ["MONGODB_DB"] = "second_voice_test"

import uuid  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.config import settings  # noqa: E402

SUFFIX = uuid.uuid4().hex[:6]
MIKE = f"per_mike_{SUFFIX}"
DANA = f"per_dana_{SUFFIX}"


@pytest.fixture(scope="module")
def seeded():
    assert settings.mongodb_db == "second_voice_test", "test must never touch the real DB"
    try:
        mc = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
        mc.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"MongoDB unreachable: {e}")
    d = mc[settings.mongodb_db]
    uid = settings.demo_user_id
    d.people.insert_many([
        {"_id": MIKE, "user_id": uid, "name": "Mike Russo", "relationship": "acquaintance",
         "label": "Neighbour", "created_at": "2026-11-01T00:00:00Z"},
        {"_id": DANA, "user_id": uid, "name": "Dana Okafor", "relationship": "clinician",
         "label": "Pharmacist", "created_at": "2026-11-01T00:00:00Z"},
    ])
    bnd = f"bnd_acq_{SUFFIX}"
    d.boundaries.insert_one({"_id": bnd, "user_id": uid, "status": "active", "origin": "seed",
                             "scope": {"type": "relationship", "value": "acquaintance"},
                             "topics": ["health", "medication"], "action": "block"})
    yield d
    d.people.delete_many({"_id": {"$in": [MIKE, DANA]}})
    d.boundaries.delete_one({"_id": bnd})
    mc.close()


def _final(ws):
    while True:
        msg = ws.receive_json()
        if msg["type"] == "error":
            raise AssertionError(msg)
        if msg["type"] == "suggestions.ready" and msg["data"]["stage"] == "final":
            return msg["data"]


def test_text_flow(seeded):
    from app.main import app

    with TestClient(app) as c:
        s = c.post("/api/sessions", json={"person_id": MIKE}).json()
        sid = s["_id"]
        assert sid.startswith("ses_")
        with c.websocket_connect(f"/ws?session_id={sid}") as ws:
            r = c.post("/api/utterances/text", json={"session_id": sid, "text": "Hey Maya, how are you?",
                                                     "person_id": MIKE})
            assert r.status_code == 200, r.text
            final = _final(ws)
        assert len(final["candidates"]) == 4
        texts = [x["text"] for x in final["candidates"]]
        assert not any("meds" in t or "tired" in t.lower() for t in texts), texts
        assert final["blocked"], "acquaintance health rule should hide something"
        assert "total" in final["latency_ms"]

        latest = c.get(f"/api/sessions/{sid}/latest").json()
        assert latest["_id"] == final["_id"]

        cand = final["candidates"][0]
        sel = c.post(f"/api/suggestions/{final['_id']}/select",
                     json={"candidate_id": cand["id"], "event_id": f"evt_sel{SUFFIX}"}).json()
        assert sel["text_to_speak"] == cand["text"]
        again = c.post(f"/api/suggestions/{final['_id']}/select",
                       json={"candidate_id": cand["id"], "event_id": f"evt_sel{SUFFIX}"}).json()
        assert again["utterance"]["_id"] == sel["utterance"]["_id"]  # idempotent

        rej = c.post(f"/api/suggestions/{final['_id']}/reject",
                     json={"candidate_id": final["candidates"][1]["id"], "reason": "too_personal"})
        assert rej.json() == {"ok": True}

        typed = c.post("/api/replies/typed", json={"session_id": sid, "text": "See you later!"}).json()
        assert typed["text_to_speak"] == "See you later!"

        # Dana (clinician) keeps medication suggestions: scope is per relationship
        s2 = c.post("/api/sessions", json={"person_id": DANA}).json()
        with c.websocket_connect(f"/ws?session_id={s2['_id']}") as ws:
            c.post("/api/utterances/text", json={"session_id": s2["_id"],
                                                 "text": "Hi Maya, here for your refill?"})
            final2 = _final(ws)
        assert any("medication" in x["topics"] for x in final2["candidates"])

        ended = c.post(f"/api/sessions/{sid}/end").json()
        assert ended["status"] == "ended"

        evts = {e["type"] for e in seeded.events.find({"session_id": sid})}
        assert {"session_started", "suggestion_selected", "suggestion_rejected", "reply_typed",
                "session_ended"} <= evts
        rej_evt = seeded.events.find_one({"session_id": sid, "type": "suggestion_rejected"})
        assert rej_evt["relationship"] == "acquaintance" and rej_evt["person_id"] == MIKE


def test_people_and_404s(seeded):
    from app.main import app

    with TestClient(app) as c:
        ids = {p["id"] for p in c.get("/api/people").json()}
        assert {MIKE, DANA} <= ids
        assert c.post("/api/utterances/text", json={"session_id": "ses_nope", "text": "hi"}).status_code == 404
        assert c.post("/api/suggestions/sug_nope/select", json={"candidate_id": "x"}).status_code == 404
