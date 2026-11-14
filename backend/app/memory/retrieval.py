"""Lane A: hybrid retrieval ($vectorSearch + $search, fused with RRF in Python).
See docs/tasks/A-brain.md step 4."""
from app.contracts import RetrievedContext


async def get_context(user_id: str, person_id: str | None, utterance_text: str) -> RetrievedContext:
    """TODO(Lane A)."""
    return RetrievedContext()


def rrf(*ranked_id_lists: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion over lists of ids (best first)."""
    scores: dict[str, float] = {}
    for ids in ranked_id_lists:
        for rank, _id in enumerate(ids):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)
