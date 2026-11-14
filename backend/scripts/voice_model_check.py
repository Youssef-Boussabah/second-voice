"""Download/warm ECAPA and verify its embedding shape using synthetic audio.

This verifies model operation, not speaker recognition accuracy.
Run before a live demo: python backend/scripts/voice_model_check.py
"""
import asyncio
from io import BytesIO
from pathlib import Path
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from app.config import settings
from app.voice.speaker import embed_voice


async def main() -> None:
    if settings.mock_speaker:
        raise SystemExit("Set MOCK_SPEAKER=0 for the real model check")
    buffer = BytesIO()
    signal = (np.sin(2 * np.pi * 180 * np.arange(32000) / 16000) * 4000).astype("<i2")
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(signal.tobytes())
    vector = await embed_voice(buffer.getvalue())
    assert len(vector) == 192 and abs(float(np.linalg.norm(vector)) - 1) < 1e-5
    print("ECAPA ready: 192 dimensions, unit norm; synthetic input only, no identity claim")


if __name__ == "__main__":
    asyncio.run(main())
