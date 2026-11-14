"""Embedding for worker writes that must never lose the memory (Lane D).

Voyage can rate-limit (free tier: 3 RPM) or stall. Learning writes call this instead of
`embed()` directly: one try, one short retry only if it still fits the ~2 s budget, then
give up and return None. The caller saves the doc without `embedding`; the backfill
(`seed/backfill_embeddings.py`) later fills every lane-d doc that lacks one.
"""
import asyncio
import logging
import time

from app.embeddings import embed

log = logging.getLogger(__name__)

BUDGET_S = 2.0
RETRY_BACKOFF_S = 0.5


async def embed_document_or_none(text: str, *, budget_s: float = BUDGET_S) -> list[float] | None:
    started = time.perf_counter()
    for attempt in (1, 2):
        remaining = budget_s - (time.perf_counter() - started)
        if remaining <= 0.1:
            break
        try:
            return (await asyncio.wait_for(embed([text], "document"), timeout=remaining))[0]
        except Exception as error:  # noqa: BLE001  rate limit, timeout, network: never lose the memory
            log.warning("embed attempt %d failed (%s); %.0fms used", attempt, type(error).__name__,
                        (time.perf_counter() - started) * 1000)
            if attempt == 1 and budget_s - (time.perf_counter() - started) > RETRY_BACKOFF_S + 0.3:
                await asyncio.sleep(RETRY_BACKOFF_S)
            else:
                break
    log.warning("saving without embedding; backfill will embed it later")
    return None
