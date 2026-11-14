"""Explicit, paid live ElevenLabs checks; never runs as part of pytest.

python backend/scripts/voice_verify_live.py [--isolated-db]
Uses real TTS and STT regardless of .env mock flags, for this process only.
Default: real Atlas persistence. --isolated-db substitutes only database operations;
provider requests and both FastAPI voice endpoints still execute real code.
Generated audio stays in ignored .models/voice-verification; no enrollment occurs.
"""
import argparse
import asyncio
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from app import db
from app.config import settings
from app.contracts import Session, new_id
from app.main import app
from app.voice.stt import transcribe
from app.voice.tts import speak_stream

TEXT = "Hello Maya. The garden looks lovely today."
OUTPUT = Path(__file__).resolve().parents[2] / ".models" / "voice-verification"


def report(step: str, **values) -> None:
    print(json.dumps({"step": step, **values}), flush=True)


def decode_mp3(audio: bytes) -> bytes:
    """Decode the whole MP3 and make a 16-kHz mono PCM WAV for the upload contract."""
    with sf.SoundFile(BytesIO(audio)) as source:
        if source.format != "MP3":
            raise ValueError("Provider response is not MPEG audio")
        signal = source.read(dtype="float32", always_2d=True).mean(axis=1)
        rate = source.samplerate
    if len(signal) < rate // 2 or not np.isfinite(signal).all() or np.max(np.abs(signal)) < 1e-5:
        raise ValueError("Audio is empty, silent, or invalid")
    from math import gcd
    divisor = gcd(rate, 16000)
    mono = resample_poly(signal, 16000 // divisor, rate // divisor)
    pcm = (np.clip(mono, -1, 1) * 32767).astype("<i2")
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm.tobytes())
    report("mp3_decoded", bytes=len(audio), duration_seconds=round(len(signal) / rate, 2),
           sample_rate=rate, non_silent=True)
    return buffer.getvalue()


def verify_transcript(text: str) -> None:
    words = re.findall(r"[a-z]+", text.lower())
    if words != re.findall(r"[a-z]+", TEXT.lower()):
        # This is known synthetic test speech, never an arbitrary user's transcript.
        report("transcript_mismatch", expected=TEXT, actual=text)
        raise ValueError("Transcript differs from synthetic test sentence")


async def main(isolated_db: bool) -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    report("credentials", key_loaded=bool(settings.elevenlabs_api_key),
           voice_loaded=bool(settings.elevenlabs_voice_id))
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        raise ValueError("Missing credentials")
    # DECISION: verification explicitly exercises real providers without rewriting .env.
    settings.mock_tts = False
    settings.mock_stt = False
    settings.mock_speaker = True
    settings.use_change_streams = False
    settings.demo_user_id = new_id("usr")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    chunks: list[bytes] = []
    first_audio_ms = None
    async for chunk in speak_stream(TEXT):
        if first_audio_ms is None:
            first_audio_ms = int((perf_counter() - started) * 1000)
        chunks.append(chunk)
    audio = b"".join(chunks)
    wav = decode_mp3(audio)
    (OUTPUT / "sdk_sample.mp3").write_bytes(audio)
    report("live_sdk_tts", passed=True, elapsed_ms=int((perf_counter() - started) * 1000),
           first_audio_ms=first_audio_ms)
    started = perf_counter()
    transcript = await transcribe(wav)
    verify_transcript(transcript)
    report("live_sdk_stt", passed=True, transcript=transcript,
           elapsed_ms=int((perf_counter() - started) * 1000))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voice-check") as client:
        started = perf_counter()
        response = await client.post("/api/tts", json={"text": TEXT})
        if response.status_code != 200 or response.headers.get("content-type") != "audio/mpeg":
            raise ValueError(f"TTS endpoint HTTP {response.status_code}")
        route_wav = decode_mp3(response.content)
        (OUTPUT / "route_sample.mp3").write_bytes(response.content)
        report("live_route_tts", passed=True, http_status=response.status_code,
               elapsed_ms=int((perf_counter() - started) * 1000), app="app.main")

        session = Session(user_id=settings.demo_user_id)
        if isolated_db:
            # Only persistence is substituted. STT, route parsing and pipeline dispatch are real.
            insert = AsyncMock()
            collections = {
                db.SESSIONS: SimpleNamespace(find_one=AsyncMock(return_value=session.to_mongo())),
                db.UTTERANCES: SimpleNamespace(insert_one=insert),
            }
            with patch.object(db, "db", return_value=collections):
                response = await client.post("/api/utterances/audio", data={"session_id": session.id},
                    files={"audio": ("generated.wav", route_wav, "audio/wav")})
            insert.assert_awaited_once()
        else:
            connected = False
            try:
                async with asyncio.timeout(15):
                    await db.client().admin.command("ping")
                report("live_atlas_ping", passed=True)
                connected = True
                await db.db()[db.SESSIONS].insert_one(session.to_mongo())
                response = await client.post("/api/utterances/audio", data={"session_id": session.id},
                    files={"audio": ("generated.wav", route_wav, "audio/wav")})
                if response.status_code == 200:
                    stored = await db.db()[db.UTTERANCES].find_one(
                        {"session_id": session.id, "user_id": settings.demo_user_id})
                    if not stored or stored["text"] != response.json()["utterance"]["text"]:
                        raise ValueError("Live utterance persistence verification failed")
            finally:
                # Delete only documents belonging to this synthetic run's unique user/session.
                # If ping failed, avoid another slow connection attempt just for cleanup.
                try:
                    if connected:
                        await db.db()[db.UTTERANCES].delete_many(
                            {"session_id": session.id, "user_id": settings.demo_user_id})
                        await db.db()[db.SESSIONS].delete_one(
                            {"_id": session.id, "user_id": settings.demo_user_id})
                finally:
                    await db.close()
        if response.status_code != 200:
            raise ValueError(f"Audio endpoint HTTP {response.status_code}")
        utterance = response.json()["utterance"]
        verify_transcript(utterance["text"])
        if utterance["source"] != "stt" or utterance["speaker"]["method"] != "unknown":
            raise ValueError("Unexpected utterance source or speaker fallback")
        report("live_route_audio", passed=True, transcript=utterance["text"],
               database="substitute" if isolated_db else "live_atlas", speaker="mock_unknown",
               latency_ms=response.json()["latency_ms"])
    report("complete", passed=True, audio_directory=str(OUTPUT))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-db", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.isolated_db))
    except Exception as exc:
        # Never print provider bodies, request URLs, settings, or exception reprs: they may hold secrets.
        code = getattr(exc, "status_code", None)
        detail = getattr(exc, "body", None)
        provider_code = detail.get("detail", {}).get("status") if isinstance(detail, dict) and isinstance(detail.get("detail"), dict) else None
        if not isinstance(provider_code, str) or not re.fullmatch(r"[a-z_]{1,80}", provider_code):
            provider_code = None
        report("failed", error_type=type(exc).__name__, http_status=code, provider_code=provider_code)
        sys.exit(1)
