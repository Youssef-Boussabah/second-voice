"""Lane A: embeddings via Voyage AI. STABLE SIGNATURE (Lane D uses it)."""
import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Literal

import numpy as np

from app.config import settings

log = logging.getLogger(__name__)

_client = None


def _mock_vec(text: str, dim: int) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    v = np.random.default_rng(seed).standard_normal(dim)
    return (v / np.linalg.norm(v)).tolist()


async def embed(texts: list[str], input_type: Literal["query", "document"]) -> list[list[float]]:
    """1024-d unit vectors. MOCK_EMBED gives deterministic random vectors (no semantics!)."""
    if not texts:
        return []
    if settings.mock_embed:
        return [_mock_vec(t, settings.embed_dim) for t in texts]
    global _client
    import voyageai

    if _client is None:
        if not settings.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY not set (or set MOCK_EMBED=true)")
        _client = voyageai.AsyncClient(api_key=settings.voyage_api_key, max_retries=3, timeout=10)  # hot path is time-boxed by embed_query
    t0 = time.perf_counter()
    res = await _client.embed(texts, model=settings.embed_model, input_type=input_type,
                              output_dimension=settings.embed_dim)
    log.info("embed %d texts (%s) %dms", len(texts), input_type, (time.perf_counter() - t0) * 1000)
    return res.embeddings


# ───────────────────────── hot-path query embedding ─────────────────────────
# DECISION: the partner-utterance path embeds exactly one query. It is time-boxed so a slow or
# rate-limited Voyage call (free tier: 3 RPM without a payment method) can't stall suggestions;
# the pipeline then falls back to text-only retrieval. Repeated lines hit an in-memory LRU cache.
_QUERY_CACHE: "OrderedDict[str, list[float]]" = OrderedDict()
_QUERY_CACHE_MAX = 512


async def embed_query(text: str, *, timeout_s: float = 2.5) -> list[float]:
    key = " ".join(text.lower().split())
    hit = _QUERY_CACHE.get(key)
    if hit is not None:
        _QUERY_CACHE.move_to_end(key)
        return hit
    vec = (await asyncio.wait_for(embed([text], "query"), timeout=timeout_s))[0]
    _QUERY_CACHE[key] = vec
    if len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
        _QUERY_CACHE.popitem(last=False)
    return vec
