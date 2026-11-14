"""Shared smoke test: contracts round-trip and the app boots with all mocks on."""
import os

os.environ.update({k: "true" for k in ["MOCK_LLM", "MOCK_EMBED", "MOCK_STT", "MOCK_SPEAKER", "MOCK_TTS"]})
os.environ["USE_CHANGE_STREAMS"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.contracts import (  # noqa: E402
    Boundary, BoundaryScope, Candidate, Event, EventType, SpeakerMatch, SuggestionSet, Utterance,
)


def test_contract_roundtrip():
    utt = Utterance(session_id="ses_1", user_id="usr_maya", speaker=SpeakerMatch(), text="hi", source="text")
    doc = utt.to_mongo()
    assert doc["_id"].startswith("utt_") and Utterance.model_validate(doc).id == utt.id
    s = SuggestionSet(session_id="ses_1", user_id="usr_maya", utterance_id=utt.id, stage="final",
                      candidates=[Candidate(text="Yes please", topics=["medication"])])
    assert s.model_dump(mode="json", by_alias=True)["candidates"][0]["topics"] == ["medication"]
    b = Boundary(user_id="usr_maya", scope=BoundaryScope(type="relationship", value="acquaintance"),
                 topics=["health"])
    assert b.to_mongo()["scope"]["type"] == "relationship"
    e = Event(user_id="usr_maya", type=EventType.suggestion_rejected, reason="too_personal")
    assert e.to_mongo()["type"] == "suggestion_rejected"


def test_app_boots():
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/health").json()["ok"] is True
