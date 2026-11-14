"""Lane B: voice REST routes. See docs/04-api-contracts.md §1 (Lane B)."""
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["voice"])


async def startup() -> None:
    """Called once at app start. Lane B: lazily warm the ECAPA speaker model here."""
    return None

# TODO(Lane B): POST /utterances/audio, POST /people, POST /people/{id}/enroll,
# POST /tts, GET /voice/status
