"""Lane B: speaker embedding + identification. STABLE SIGNATURES (see 04-api-contracts §4)."""
from app.contracts import SpeakerMatch, SpeakerMethod


async def embed_voice(wav_bytes: bytes) -> list[float]:
    """192-d L2-normalized ECAPA embedding. TODO(Lane B)."""
    raise NotImplementedError


async def identify(user_id: str, wav_bytes: bytes) -> SpeakerMatch:
    """$vectorSearch on people.voice_centroid. TODO(Lane B)."""
    return SpeakerMatch(method=SpeakerMethod.unknown)
