"""Lane A: core REST routes. See docs/04-api-contracts.md §1 (Lane A)."""
from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/health")
async def health():
    return {
        "ok": True,
        "mocks": {
            "llm": settings.mock_llm, "embed": settings.mock_embed, "stt": settings.mock_stt,
            "speaker": settings.mock_speaker, "tts": settings.mock_tts,
        },
    }

# TODO(Lane A): sessions, utterances/text, utterances/{id}/assign, sessions/{id}/latest,
# suggestions/{set_id}/select, suggestions/{set_id}/reject, replies/typed, GET people
