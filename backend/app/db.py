"""MongoDB client + collection names. Lane A owns this file."""
from pymongo import AsyncMongoClient

from app.config import settings

# Collection names: use these constants, never string literals.
USERS = "users"
PEOPLE = "people"
SESSIONS = "sessions"
UTTERANCES = "utterances"
AUDIO_CLIPS = "audio_clips"
SUGGESTION_SETS = "suggestion_sets"
MEMORIES = "memories"
BOUNDARIES = "boundaries"
EVENTS = "events"
WORKER_STATE = "worker_state"
EVAL_RUNS = "eval_runs"

# Search index names (exactly 3: free-tier limit)
IDX_PEOPLE_VOICE = "people_voice"
IDX_MEMORIES_VECTOR = "memories_vector"
IDX_MEMORIES_TEXT = "memories_text"

_client: AsyncMongoClient | None = None


def client() -> AsyncMongoClient:
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice", tz_aware=True)
    return _client


def db():
    return client()[settings.mongodb_db]


async def close() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def warmup(connections: int = 4) -> int:
    """Open several pooled connections before the first utterance so the instant stage's
    parallel queries don't each pay a TLS handshake (measured: ~1.4 s cold vs ~0.1 s warm).
    Returns elapsed ms. Never raises."""
    import asyncio
    import logging
    import time

    t = time.perf_counter()
    d = db()
    uid = settings.demo_user_id
    try:
        await asyncio.gather(
            d.command("ping"),
            d[PEOPLE].find_one({"user_id": uid}, {"_id": 1}),
            d[BOUNDARIES].find_one({"user_id": uid, "status": "active"}, {"_id": 1}),
            d[MEMORIES].find_one({"user_id": uid, "kind": "phrase"}, {"_id": 1}),
            *[d.command("ping") for _ in range(max(0, connections - 4))],
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("mongo warmup failed: %s", str(e)[:200])
    ms = int((time.perf_counter() - t) * 1000)
    logging.getLogger(__name__).info("mongo warmup %d ms", ms)
    return ms
