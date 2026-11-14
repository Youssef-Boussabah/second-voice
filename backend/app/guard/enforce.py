"""Lane A: deterministic boundary enforcement. See docs/05-guardrails.md §1.
Pure functions, no I/O, no LLM. STABLE SIGNATURES (Lane D + eval use them)."""
from app.contracts import Boundary, Candidate, PersonOut, Topic


def tag_topics_safety_net(text: str, topics: list[Topic]) -> list[Topic]:
    """Add sensitive topics the LLM missed (keyword/regex lists). TODO(Lane A)."""
    return list(topics)


def apply_guard(
    cands: list[Candidate], person: PersonOut | None, boundaries: list[Boundary]
) -> tuple[list[Candidate], list[Candidate]]:
    """Return (allowed[:4], blocked). TODO(Lane A): implement per 05-guardrails.md §1."""
    return cands[:4], []
