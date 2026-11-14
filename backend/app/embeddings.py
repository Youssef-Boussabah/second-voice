"""Lane A: embeddings via Voyage AI. STABLE SIGNATURE (Lane D uses it)."""
import hashlib
import logging
import time
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
        _client = voyageai.AsyncClient(api_key=settings.voyage_api_key, max_retries=1, timeout=10)
    t0 = time.perf_counter()
    res = await _client.embed(texts, model=settings.embed_model, input_type=input_type,
                              output_dimension=settings.embed_dim)
    log.info("embed %d texts (%s) %dms", len(texts), input_type, (time.perf_counter() - t0) * 1000)
    return res.embeddings
