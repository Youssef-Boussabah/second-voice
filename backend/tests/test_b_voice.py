"""Isolated voice router tests: no Atlas, credentials, or ML required."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
import wave
import httpx

from app.api import voice_routes
from app.config import settings
from app import db
from app.contracts import Session, Person, Consent
from app.voice import stt, tts, speaker


def wav_bytes():
    buf = BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * 16000)
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "mock_tts", True)
    app = FastAPI()
    app.include_router(voice_routes.router)
    return TestClient(app)


def test_tts_mock_browser_fallback(client):
    response = client.post("/api/tts", json={"text": "Hello Maya"})
    assert response.status_code == 503
    assert response.json() == {"fallback": "browser"}


def test_tts_stream_and_explicit_request(client, monkeypatch):
    calls = []

    async def stream(text):
        calls.append(text)
        yield b"ID3"
        yield b"mp3-payload"

    monkeypatch.setattr(voice_routes, "speak_stream", stream)
    assert calls == []
    assert client.get("/api/tts").status_code == 405
    assert calls == []
    response = client.post("/api/tts", json={"text": "Hello"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3mp3-payload"
    assert calls == ["Hello"]


def test_tts_outage_before_headers(client, monkeypatch):
    async def stream(text):
        raise TimeoutError("provider")
        yield b""

    monkeypatch.setattr(voice_routes, "speak_stream", stream)
    response = client.post("/api/tts", json={"text": "Hello"})
    assert response.status_code == 503
    assert response.json()["fallback"] == "browser"


@pytest.mark.parametrize("text", ["", "   ", "x" * 5001])
def test_tts_invalid_text(client, text):
    assert client.post("/api/tts", json={"text": text}).status_code == 400


@pytest.mark.asyncio
async def test_real_sdk_tts_and_stt_requests(monkeypatch):
    """Use installed SDK serialization against HTTP transport, no provider access."""
    requests = []

    def handler(request):
        requests.append(request)
        if "/text-to-speech/" in request.url.path:
            return httpx.Response(200, content=b"ID3-mpeg", headers={"content-type": "audio/mpeg"})
        return httpx.Response(200, json={"text": "This is actual provider text.",
                                        "language_code": "eng", "language_probability": 1.0,
                                        "words": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "mock_tts", False)
    monkeypatch.setattr(settings, "mock_stt", False)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-only")
    monkeypatch.setattr(settings, "elevenlabs_voice_id", "test-voice")
    assert b"".join([chunk async for chunk in tts.speak_stream("Chosen text")]) == b"ID3-mpeg"
    assert await stt.transcribe(wav_bytes()) == "This is actual provider text."
    assert requests[0].url.params["output_format"] == "mp3_44100_128"
    assert b'"text":"Chosen text"' in requests[0].content
    assert b"utterance.wav" in requests[1].content
    assert settings.stt_model.encode() in requests[1].content


@pytest.fixture
def database(monkeypatch):
    session = Session(user_id=settings.demo_user_id)
    person = Person(user_id=settings.demo_user_id, name="Dana", relationship="clinician")
    sessions = SimpleNamespace(find_one=AsyncMock(return_value=session.to_mongo()))
    utterances = SimpleNamespace(insert_one=AsyncMock(), find_one=AsyncMock(return_value=None))
    people = SimpleNamespace(find_one=AsyncMock(return_value=person.to_mongo()),
                             insert_one=AsyncMock(),
                             update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
    collections = {db.SESSIONS: sessions, db.UTTERANCES: utterances, db.PEOPLE: people}
    monkeypatch.setattr(db, "db", lambda: collections)
    monkeypatch.setattr(settings, "mock_stt", True)
    monkeypatch.setattr(settings, "mock_speaker", True)
    monkeypatch.setattr(settings, "use_change_streams", False)
    monkeypatch.setattr(voice_routes, "broadcast", AsyncMock())
    monkeypatch.setattr(voice_routes, "on_partner_utterance", AsyncMock())
    return SimpleNamespace(session=session, person=person, utterances=utterances,
                           people=people, sessions=sessions)


def send_audio(client, database, headers=None, data=None):
    return client.post("/api/utterances/audio", data={"session_id": database.session.id},
                       files={"audio": ("turn.wav", wav_bytes() if data is None else data, "audio/wav")},
                       headers=headers or {})


def test_audio_mock_transcript_and_pipeline(client, database):
    response = send_audio(client, database, {"X-Mock-Text": "Dana speaking",
                                            "X-Mock-Person": database.person.id})
    assert response.status_code == 200
    utt = response.json()["utterance"]
    assert utt["text"] == "Dana speaking"
    assert utt["speaker"]["person_id"] == database.person.id
    assert utt["source"] == "stt"
    database.utterances.insert_one.assert_awaited_once()
    voice_routes.on_partner_utterance.assert_awaited_once()
    voice_routes.broadcast.assert_awaited_once()
    assert {"stt", "speaker", "total"} <= response.json()["latency_ms"].keys()


def test_audio_empty_no_pipeline(client, database):
    assert send_audio(client, database, {"X-Mock-Text": " "}).status_code == 204
    database.utterances.insert_one.assert_not_awaited()
    voice_routes.on_partner_utterance.assert_not_awaited()


def test_audio_invalid_wav(client, database):
    assert send_audio(client, database, data=b"not wav").status_code == 400
    database.utterances.insert_one.assert_not_awaited()


def test_audio_real_path_ignores_mock_headers(client, database, monkeypatch):
    monkeypatch.setattr(settings, "mock_stt", False)
    monkeypatch.setattr(settings, "mock_speaker", False)
    monkeypatch.setattr(voice_routes, "transcribe", AsyncMock(return_value="Provider transcript"))
    monkeypatch.setattr(voice_routes, "identify", AsyncMock(side_effect=RuntimeError("ML missing")))
    response = send_audio(client, database, {"X-Mock-Text": "Fake", "X-Mock-Person": database.person.id})
    assert response.status_code == 200
    assert response.json()["utterance"]["text"] == "Provider transcript"
    assert response.json()["utterance"]["speaker"]["method"] == "unknown"


def test_stt_outage_no_pipeline(client, database, monkeypatch):
    monkeypatch.setattr(settings, "mock_stt", False)
    monkeypatch.setattr(voice_routes, "transcribe", AsyncMock(side_effect=TimeoutError()))
    assert send_audio(client, database).status_code == 503
    database.utterances.insert_one.assert_not_awaited()


def test_session_missing_or_ended(client, database):
    database.sessions.find_one.return_value = None
    assert send_audio(client, database).status_code == 404
    database.sessions.find_one.return_value = {**database.session.to_mongo(), "status": "ended"}
    assert send_audio(client, database).status_code == 409


def test_enrollment_requires_consent(client, database):
    response = client.post(f"/api/people/{database.person.id}/enroll",
        files=[("clips[]", (f"{i}.wav", wav_bytes(), "audio/wav")) for i in range(3)])
    assert response.status_code == 409
    database.people.update_one.assert_not_awaited()


def test_enroll_vectors_and_no_audio_storage(client, database, monkeypatch):
    monkeypatch.setattr(settings, "mock_speaker", False)
    database.person.consent = Consent(voice=True)
    database.people.find_one.return_value = database.person.to_mongo()
    monkeypatch.setattr(voice_routes, "embed_voice", AsyncMock(return_value=[1.0] + [0.0] * 191))
    response = client.post(f"/api/people/{database.person.id}/enroll",
        files=[("clips[]", (f"{i}.wav", wav_bytes(), "audio/wav")) for i in range(3)])
    assert response.status_code == 200
    assert response.json()["enrolled"] is True
    assert "voiceprints" not in response.json()
    write = database.people.update_one.call_args.args
    assert write[0]["consent.voice"] is True
    assert len(write[1]["$set"]["voiceprints"]) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("scores,consent,expected", [([.9, .8], True, "voice"),
    ([.9, .89], True, "unknown"), ([.7, .6], True, "unknown"), ([.95], False, "unknown")])
async def test_speaker_threshold_margin_consent(database, monkeypatch, scores, consent, expected):
    monkeypatch.setattr(settings, "mock_speaker", False)
    monkeypatch.setattr(settings, "speaker_threshold", .8)
    monkeypatch.setattr(speaker, "embed_voice", AsyncMock(return_value=[1.] + [0.] * 191))
    hits = [{"_id": f"per_{i}", "score": score, "user_id": settings.demo_user_id,
             "consent": {"voice": consent}} for i, score in enumerate(scores)]
    database.people.aggregate = AsyncMock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=hits)))
    match = await speaker.identify(settings.demo_user_id, wav_bytes())
    assert match.method == expected
    if expected == "unknown":
        assert match.person_id is None
    database.people.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_sticky_match_scoped_to_session(database, monkeypatch):
    monkeypatch.setattr(settings, "mock_speaker", False)
    monkeypatch.setattr(settings, "speaker_threshold", .8)
    monkeypatch.setattr(speaker, "embed_voice", AsyncMock(return_value=[1.] + [0.] * 191))
    hits = [{"_id": "per_dana", "score": .77, "user_id": settings.demo_user_id,
             "consent": {"voice": True}}]
    database.people.aggregate = AsyncMock(return_value=SimpleNamespace(to_list=AsyncMock(return_value=hits)))
    database.utterances.find_one.return_value = {"_id": "utt_recent"}
    assert (await speaker.identify(settings.demo_user_id, wav_bytes())).method == "unknown"
    token = speaker.session_context.set(database.session.id)
    try:
        assert (await speaker.identify(settings.demo_user_id, wav_bytes())).method == "voice"
    finally:
        speaker.session_context.reset(token)
    query = database.utterances.find_one.call_args.args[0]
    assert query["session_id"] == database.session.id
    assert query["user_id"] == settings.demo_user_id
    assert query["speaker.person_id"] == "per_dana"
    assert "created_at" in query


def test_person_creation_consent_and_vectors_hidden(client, database):
    response = client.post("/api/people", json={"name": "Dana", "relationship": "clinician",
                                                "consent_voice": True})
    assert response.status_code == 200
    assert response.json()["id"].startswith("per_")
    assert "voiceprints" not in response.json()
    document = database.people.insert_one.call_args.args[0]
    assert document["consent"]["voice"] is True
    assert document["consent"]["at"].tzinfo is not None


def test_enrollment_consent_revoked_during_inference(client, database, monkeypatch):
    monkeypatch.setattr(settings, "mock_speaker", False)
    database.person.consent = Consent(voice=True)
    database.people.find_one.return_value = database.person.to_mongo()
    database.people.update_one.return_value = SimpleNamespace(matched_count=0)
    monkeypatch.setattr(voice_routes, "embed_voice", AsyncMock(return_value=[1.] + [0.] * 191))
    response = client.post(f"/api/people/{database.person.id}/enroll",
        files=[("clips[]", (f"{i}.wav", wav_bytes(), "audio/wav")) for i in range(3)])
    assert response.status_code == 409


def test_mock_speaker_has_no_fake_enrollment(client, database):
    database.person.consent = Consent(voice=True)
    database.people.find_one.return_value = database.person.to_mongo()
    response = client.post(f"/api/people/{database.person.id}/enroll",
        files=[("clips[]", (f"{i}.wav", wav_bytes(), "audio/wav")) for i in range(3)])
    assert response.status_code == 503
    database.people.update_one.assert_not_awaited()
