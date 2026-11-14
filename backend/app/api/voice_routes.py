"""Voice REST routes; synthesis occurs only on the explicit tap request."""
import logging
import asyncio
from time import perf_counter
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, Response

from app import db
from app.config import settings
from app.contracts import TTSIn, Utterance, UtteranceOut, SpeakerMatch, SpeakerMethod, WSMessage
from app.graph.pipeline import on_partner_utterance
from app.realtime.hub import broadcast
from app.voice.audio import MAX_AUDIO_BYTES, validate_wav
from app.voice.stt import transcribe
from app.voice.speaker import identify
from app.voice.tts import speak_stream

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["voice"])


async def startup() -> None:
    """Speaker warmup is optional and must never delay speech output."""


@router.post("/tts")
async def tts(body: TTSIn):
    text = body.text.strip()
    if not text or len(text) > 5000:
        raise HTTPException(400, "Text must contain 1 to 5000 characters")
    stream = speak_stream(text)
    try:
        # Prime before HTTP headers: provider failures can still return fallback JSON.
        first = await anext(stream)
    except Exception as exc:
        await stream.aclose()
        log.warning("tts unavailable error_type=%s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"fallback": "browser"})

    async def audio() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    return StreamingResponse(audio(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


async def _read_wav(upload: UploadFile) -> bytes:
    try:
        data = await upload.read(MAX_AUDIO_BYTES + 1)
    finally:
        await upload.close()
    try:
        validate_wav(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return data


@router.post("/utterances/audio", response_model=UtteranceOut)
async def audio_utterance(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    x_mock_text: str | None = Header(None),
    x_mock_person: str | None = Header(None),
):
    started = perf_counter()
    session = await db.db()[db.SESSIONS].find_one(
        {"_id": session_id, "user_id": settings.demo_user_id}
    )
    if not session:
        raise HTTPException(404, "Session not found")
    if session.get("status") == "ended":
        raise HTTPException(409, "Session has ended")
    wav = await _read_wav(audio)
    latency: dict[str, int] = {}

    async def text_step() -> str:
        tick = perf_counter()
        try:
            if settings.mock_stt and x_mock_text is not None:
                return x_mock_text.strip()
            return await transcribe(wav)
        finally:
            latency["stt"] = int((perf_counter() - tick) * 1000)

    async def speaker_step() -> SpeakerMatch:
        tick = perf_counter()
        try:
            if settings.mock_speaker and x_mock_person:
                person = await db.db()[db.PEOPLE].find_one(
                    {"_id": x_mock_person, "user_id": settings.demo_user_id}
                )
                if person:
                    return SpeakerMatch(person_id=x_mock_person, method=SpeakerMethod.forced)
            return await identify(settings.demo_user_id, wav)
        except Exception as exc:
            log.warning("speaker fallback error_type=%s", type(exc).__name__)
            return SpeakerMatch()
        finally:
            latency["speaker"] = int((perf_counter() - tick) * 1000)

    # return_exceptions waits for both jobs even if STT fails (no orphan inference).
    text, speaker = await asyncio.gather(text_step(), speaker_step(), return_exceptions=True)
    if isinstance(text, BaseException):
        log.warning("stt unavailable error_type=%s", type(text).__name__)
        raise HTTPException(503, "STT unavailable; type the partner's words")
    if not text.strip():
        return Response(status_code=204)
    if isinstance(speaker, BaseException):
        speaker = SpeakerMatch()
    utt = Utterance(session_id=session_id, user_id=settings.demo_user_id,
                    speaker=speaker, text=text.strip(), source="stt")
    await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
    if not settings.use_change_streams:
        await broadcast(WSMessage(type="utterance.created", session_id=session_id,
                                  data=utt.model_dump(mode="json")))
    background_tasks.add_task(on_partner_utterance, utt)
    latency["total"] = int((perf_counter() - started) * 1000)
    log.info("audio utterance latency_ms=%s", latency)
    return UtteranceOut(utterance=utt, latency_ms=latency)
