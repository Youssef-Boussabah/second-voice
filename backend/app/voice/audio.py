"""Bounded PCM WAV validation; raw clips are never persisted by voice routes."""
from io import BytesIO
import wave

MAX_AUDIO_BYTES = 4 * 1024 * 1024


def validate_wav(data: bytes) -> None:
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise ValueError("WAV must be nonempty and at most 4 MiB")
    try:
        with wave.open(BytesIO(data), "rb") as wav:
            frames = wav.getnframes()
            if (wav.getcomptype() != "NONE" or wav.getnchannels() not in (1, 2)
                    or wav.getsampwidth() != 2 or not 8000 <= wav.getframerate() <= 48000
                    or not 0 < frames <= wav.getframerate() * 30):
                raise ValueError("Expected 16-bit PCM WAV, 1-2 channels, up to 30 seconds")
            expected = frames * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(frames)) != expected:
                raise ValueError("Truncated WAV")
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid PCM WAV") from exc
