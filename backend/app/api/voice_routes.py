"""Voice REST routes; synthesis occurs only on the explicit tap request."""
import logging
import asyncio
from importlib.util import find_spec
from time import perf_counter
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, Response

from app import db
from app.config import settings
from app.contracts import (TTSIn, Utterance, UtteranceOut, SpeakerMatch, SpeakerMethod,
                           WSMessage, Person, PersonCreateIn, PersonOut, Consent, utcnow)
from app.graph.pipeline import on_partner_utterance
from app.realtime.hub import broadcast
from app.voice.audio import MAX_AUDIO_BYTES, validate_wav
from app.voice.stt import transcribe
from app.voice.speaker import identify, embed_voice, normalized, session_context, warmup
from app.voice.tts import speak_stream

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["voice"])
_warmup_task: asyncio.Task[None] | None = None


async def startup() -> None:
    """Speaker warmup is optional and must never delay speech output."""
    global _warmup_task
    if not settings.mock_speaker and (_warmup_task is None or _warmup_task.done()):
        _warmup_task = asyncio.create_task(warmup())


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
        token = session_context.set(session_id)
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
            session_context.reset(token)
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
    # speaker.unknown (with the people to choose from) is emitted by the pipeline itself.
    background_tasks.add_task(on_partner_utterance, utt)
    latency["total"] = int((perf_counter() - started) * 1000)
    log.info("audio utterance latency_ms=%s", latency)
    return UtteranceOut(utterance=utt, latency_ms=latency)


def _person_out(person: Person) -> PersonOut:
    return PersonOut(id=person.id, name=person.name, relationship=person.relationship,
                     label=person.label, enrolled=person.voice_centroid is not None,
                     last_seen=person.last_seen)


@router.post("/people", response_model=PersonOut)
async def create_person(body: PersonCreateIn) -> PersonOut:
    if not body.name.strip():
        raise HTTPException(400, "Person name is required")
    person = Person(user_id=settings.demo_user_id, name=body.name, relationship=body.relationship,
                    label=body.label, notes=body.notes,
                    consent=Consent(voice=body.consent_voice,
                                    at=utcnow() if body.consent_voice else None))
    await db.db()[db.PEOPLE].insert_one(person.to_mongo())
    return _person_out(person)


@router.post("/people/{person_id}/enroll", response_model=PersonOut)
async def enroll_person(person_id: str, clips: list[UploadFile] = File(..., alias="clips[]")) -> PersonOut:
    started = perf_counter()
    try:
        stored = await db.db()[db.PEOPLE].find_one(
            {"_id": person_id, "user_id": settings.demo_user_id}
        )
        if not stored:
            raise HTTPException(404, "Person not found")
        person = Person.model_validate(stored)
        if not person.consent.voice:
            raise HTTPException(409, "Voice enrollment requires explicit consent")
        if not 3 <= len(clips) <= 10:
            raise HTTPException(400, "Provide 3 to 10 WAV clips as clips[]")
        if settings.mock_speaker:
            raise HTTPException(503, "Real speaker enrollment is disabled in mock mode")
        vectors: list[list[float]] = []
        for clip in clips:
            wav = await _read_wav(clip)
            try:
                vectors.append(await embed_voice(wav))
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except Exception as exc:
                log.warning("enrollment unavailable error_type=%s", type(exc).__name__)
                raise HTTPException(503, "Speaker model unavailable") from exc
        centroid = normalized([sum(v[i] for v in vectors) / len(vectors) for i in range(192)])
        # Recheck consent in the write predicate in case it changed during inference.
        result = await db.db()[db.PEOPLE].update_one(
            {"_id": person_id, "user_id": settings.demo_user_id, "consent.voice": True},
            {"$set": {"voiceprints": vectors, "voice_centroid": centroid}},
        )
        if not result.matched_count:
            raise HTTPException(409, "Person removed or voice consent withdrawn")
        person.voiceprints = vectors
        person.voice_centroid = centroid
        return _person_out(person)
    finally:
        for clip in clips:
            await clip.close()
        log.info("enrollment elapsed_ms=%d", (perf_counter() - started) * 1000)


@router.get("/voice/status")
async def voice_status() -> dict[str, str]:
    """Report configured modes, not a paid provider connectivity probe."""
    if ((not settings.mock_stt or not settings.mock_tts) and not settings.elevenlabs_api_key
            or not settings.mock_tts and not settings.elevenlabs_voice_id):
        raise HTTPException(503, "ElevenLabs voice services are not configured")
    if not settings.mock_speaker and any(find_spec(name) is None for name in
                                        ("torch", "torchaudio", "speechbrain", "soundfile", "scipy")):
        raise HTTPException(503, "Speaker dependencies are not installed; use manual speaker selection")
    return {"stt": "mock" if settings.mock_stt else "ok",
            "speaker": "mock" if settings.mock_speaker else "ok",
            "tts": "mock" if settings.mock_tts else "ok"}
