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
