"""On-demand speech. No background or pipeline code calls this module."""
import logging
from time import perf_counter
from typing import AsyncIterator
import httpx

from app.config import settings

log = logging.getLogger(__name__)


class SpeechUnavailable(RuntimeError):
    """The caller should offer browser speech synthesis."""


async def speak_stream(text: str) -> AsyncIterator[bytes]:
    """Stream MP3 from ElevenLabs using its asynchronous SDK."""
    if settings.mock_tts or not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        raise SpeechUnavailable("Speech provider unavailable")
    from elevenlabs.client import AsyncElevenLabs

    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0) as http_client:
            client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key, httpx_client=http_client)
            async for chunk in client.text_to_speech.stream(
                voice_id=settings.elevenlabs_voice_id,
                text=text,
                model_id=settings.tts_model,
                output_format="mp3_44100_128",
            ):
                if chunk:
                    yield chunk
    finally:
        log.info("tts elapsed_ms=%d", (perf_counter() - started) * 1000)
