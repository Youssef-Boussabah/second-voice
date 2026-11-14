"""Original Second Voice ECAPA/Atlas implementation; optional ML imports stay lazy.

Design reference: https://github.com/borisnezlobin/mongo-hacks (192-d ECAPA).
No Amelia source code is reused. Unknown voices are never persisted.
"""
import asyncio
from contextvars import ContextVar
from datetime import timedelta
from io import BytesIO
import logging
from pathlib import Path
from threading import Lock
from time import perf_counter

import numpy as np

from app import db
from app.config import settings
from app.contracts import SpeakerMatch, SpeakerMethod
from app.contracts import utcnow
from app.voice.audio import validate_wav

log = logging.getLogger(__name__)
session_context: ContextVar[str | None] = ContextVar("voice_session", default=None)
_model = None
_inference_lock = Lock()


async def warmup() -> None:
    """Optional background startup job; missing ML never breaks other voice routes."""
    def load() -> None:
        with _inference_lock:
            _encoder()
    started = perf_counter()
    try:
        await asyncio.to_thread(load)
    except Exception as exc:
        log.warning("speaker warmup unavailable error_type=%s", type(exc).__name__)
    finally:
        log.info("speaker warmup elapsed_ms=%d", (perf_counter() - started) * 1000)


def _encoder():
    global _model
    if _model is None:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy

        # DECISION: CPU only, one model and serialized inference for predictable RAM.
        model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(Path(__file__).resolve().parents[3] / ".models" / "ecapa"),
            run_opts={"device": "cpu"},
            # Copy directly into the ignored workspace cache: no Windows symlink privilege.
            local_strategy=LocalStrategy.COPY_SKIP_CACHE,
        )
        with torch.inference_mode():
            model.encode_batch(torch.zeros(1, 16000))
        _model = model
    return _model


def _embed_sync(wav_bytes: bytes) -> list[float]:
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly
    from math import gcd

    validate_wav(wav_bytes)
    signal, rate = sf.read(BytesIO(wav_bytes), dtype="float32", always_2d=True)
    mono = signal.mean(axis=1)
    if not np.isfinite(mono).all() or np.max(np.abs(mono)) < 1e-5:
        raise ValueError("No speech signal")
    if rate != 16000:
        divisor = gcd(rate, 16000)
        mono = resample_poly(mono, 16000 // divisor, rate // divisor)
    if len(mono) < 8000:
        raise ValueError("Speaker clips must be at least half a second")
    with _inference_lock, torch.inference_mode():
        vector = _encoder().encode_batch(torch.from_numpy(mono).unsqueeze(0))
        values = vector.detach().cpu().numpy().reshape(-1)
    return normalized(values)


def normalized(values) -> list[float]:
    vector = np.asarray(values, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if vector.shape != (192,) or not np.isfinite(vector).all() or norm < 1e-8:
        raise ValueError("Expected a finite nonzero 192-dimensional voice embedding")
    return (vector / norm).tolist()


async def embed_voice(wav_bytes: bytes) -> list[float]:
    """192-d L2-normalized ECAPA embedding, computed off the event loop."""
    if settings.mock_speaker:
        # DECISION: do not invent a biometric identity or persist fake enrollment.
        raise RuntimeError("Speaker enrollment is disabled in mock mode")
    started = perf_counter()
    try:
        return await asyncio.to_thread(_embed_sync, wav_bytes)
    finally:
        log.info("speaker embedding elapsed_ms=%d", (perf_counter() - started) * 1000)


async def identify(user_id: str, wav_bytes: bytes) -> SpeakerMatch:
    """Atlas cosine score and ambiguity margin; fail closed to unknown."""
    if settings.mock_speaker:
        return SpeakerMatch(method=SpeakerMethod.unknown)
    if _model is None:
        # DECISION: cold model/download must never hold up the STT thin slice.
        return SpeakerMatch()
    started = perf_counter()
    try:
        vector = await embed_voice(wav_bytes)
        cursor = await db.db()[db.PEOPLE].aggregate([
            {"$vectorSearch": {"index": db.IDX_PEOPLE_VOICE, "path": "voice_centroid",
                               "queryVector": vector, "filter": {"user_id": user_id},
                               "limit": 3, "numCandidates": 20}},
            {"$project": {"_id": 1, "user_id": 1, "consent": 1,
                          "score": {"$meta": "vectorSearchScore"}}},
        ])
        hits = await cursor.to_list(length=3)
        if not hits:
            return SpeakerMatch()
        top = hits[0]
        score = float(top["score"])
        margin = score - float(hits[1]["score"]) if len(hits) > 1 else 1.0
        if top.get("user_id") != user_id or not top.get("consent", {}).get("voice"):
            return SpeakerMatch()
        threshold = settings.speaker_threshold
        session_id = session_context.get()
        if session_id and threshold - 0.05 <= score < threshold:
            recent = await db.db()[db.UTTERANCES].find_one(
                {"user_id": user_id, "session_id": session_id,
                 "speaker.person_id": top["_id"], "speaker.kind": "partner",
                 "created_at": {"$gte": utcnow() - timedelta(seconds=30)}},
                sort=[("created_at", -1)],
            )
            if recent:
                threshold -= 0.05
        if score >= threshold and margin >= 0.03:
            return SpeakerMatch(person_id=top["_id"], score=score, method=SpeakerMethod.voice)
        return SpeakerMatch(score=score)
    except Exception as exc:
        log.warning("speaker unknown error_type=%s", type(exc).__name__)
        return SpeakerMatch()
    finally:
        log.info("speaker identification elapsed_ms=%d", (perf_counter() - started) * 1000)
