"""Lane A: embeddings via Voyage AI. STABLE SIGNATURE (Lane D uses it)."""
import hashlib
from typing import Literal

import numpy as np

from app.config import settings


def _mock_vec(text: str, dim: int) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    v = np.random.default_rng(seed).standard_normal(dim)
    return (v / np.linalg.norm(v)).tolist()


async def embed(texts: list[str], input_type: Literal["query", "document"]) -> list[list[float]]:
    """1024-d unit vectors. MOCK_EMBED gives deterministic random vectors (no semantics!)."""
    if settings.mock_embed:
        return [_mock_vec(t, settings.embed_dim) for t in texts]
    # TODO(Lane A): voyageai.AsyncClient(api_key=...).embed(texts, model=settings.embed_model,
    #               input_type=input_type, output_dimension=settings.embed_dim).embeddings
    raise NotImplementedError
