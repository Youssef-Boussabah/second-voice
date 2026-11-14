"""ElevenLabs Scribe batch transcription; no audio is written to disk."""
from io import BytesIO
import logging
from time import perf_counter
import httpx

from app.config import settings

log = logging.getLogger(__name__)


async def transcribe(wav_bytes: bytes) -> str:
    """Return actual provider text, or the documented explicit mock sentence."""
    if settings.mock_stt:
        return "Hi Maya, how are you?"
    if not settings.elevenlabs_api_key:
        raise RuntimeError("STT provider is not configured")
    from elevenlabs.client import AsyncElevenLabs

    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key, httpx_client=http_client)
            result = await client.speech_to_text.convert(
                file=("utterance.wav", BytesIO(wav_bytes), "audio/wav"),
                model_id=settings.stt_model,
                language_code="eng",
                keyterms=["Maya", "Dana", "Leafs"],
            )
        return result.text.strip()
    finally:
        log.info("stt elapsed_ms=%d", (perf_counter() - started) * 1000)
