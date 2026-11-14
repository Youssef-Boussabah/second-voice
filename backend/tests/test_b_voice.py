"""Isolated voice router tests: no Atlas, credentials, or ML required."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import voice_routes
from app.config import settings


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
