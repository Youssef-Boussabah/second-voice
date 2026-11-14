"""Lane B: text-to-speech in the user's cloned voice. STABLE SIGNATURE.
Only ever called as the result of a user tap."""
from typing import AsyncIterator


async def speak_stream(text: str) -> AsyncIterator[bytes]:
    """TODO(Lane B): ElevenLabs streaming TTS, voice=settings.elevenlabs_voice_id, model=settings.tts_model."""
    raise NotImplementedError
    yield b""  # pragma: no cover  (makes this an async generator)
