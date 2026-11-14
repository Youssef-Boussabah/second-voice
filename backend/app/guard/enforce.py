"""Lane A: deterministic boundary enforcement. See docs/05-guardrails.md §1.
Pure functions, no I/O, no LLM. STABLE SIGNATURES (Lane D + eval use them)."""
from __future__ import annotations

import re

from app.contracts import Boundary, Candidate, PersonOut, Topic

MAX_ALLOWED = 4

# Keyword/regex safety net. Word-boundary matched, case-insensitive. Kept deliberately
# small and explicit so judges can read exactly what gets caught.
_KEYWORDS: dict[str, list[str]] = {
    "medication": [
        r"riluzole", r"rilutek", r"edaravone", r"radicava", r"relyvrio", r"tofersen", r"qalsody",
        r"baclofen", r"gabapentin", r"morphine", r"oxycodone", r"tylenol", r"advil", r"ibuprofen",
        r"insulin", r"antibiotics?", r"meds?", r"medications?", r"medicines?", r"pills?",
        r"prescriptions?", r"refills?", r"doses?", r"dosage", r"pharmac\w*", r"generic",
        r"blister packs?",
    ],
    "health": [
        r"tired", r"exhausted", r"fatigue", r"pain(?:ful)?", r"hurts?", r"doctors?", r"dr\.",
        r"neurologist", r"hospital", r"clinic", r"diagnos\w*", r"symptoms?", r"ALS",
        r"breathing", r"bipap", r"ventilator", r"feeding tube", r"peg tube", r"wheelchair",
        r"physio\w*", r"therapy", r"sick", r"illness", r"disease", r"weak(?:er|ness)?",
        r"cramps?", r"spasms?", r"swallow\w*", r"choking", r"progression", r"health",
        r"appointments?", r"scan", r"mri", r"bloodwork", r"nurse",
    ],
    "finances": [
        r"\$\s?\d[\d,.]*", r"rent", r"bills?", r"money", r"afford\w*", r"loans?", r"debt", r"broke",
        r"salary", r"mortgage", r"insurance", r"bank", r"savings", r"expensive", r"pay(?:ing)? for",
    ],
    "location_schedule": [
        r"home alone", r"by myself", r"away until", r"out of town", r"address", r"key under",
        r"spare key", r"nobody(?:'s| is) home", r"alarm code", r"door code", r"leaving on",
    ],
    "death_dying": [
        r"die", r"dying", r"death", r"dead", r"funeral", r"end of life", r"palliative",
        r"hospice", r"maid", r"assisted dying", r"time left", r"will and",
    ],
    "distress": [
        r"scared", r"terrified", r"afraid", r"depress\w*", r"anxious", r"anxiety", r"hopeless",
        r"can'?t cope", r"overwhelm\w*", r"crying", r"lonely", r"rough", r"struggling",
        r"hard days?", r"frustrat\w*",
    ],
    "family_conflict": [
        r"fight(?:ing)?", r"argu(?:e|ing|ment)", r"divorce", r"estranged", r"not speaking",
        r"yelled", r"falling out",
    ],
    "romance": [
        r"dating", r"date night", r"boyfriend", r"girlfriend", r"crush", r"romantic", r"sex\w*",
        r"intimacy", r"breakup", r"broke up",
    ],
    "legal": [r"lawyer", r"lawsuit", r"court", r"legal", r"power of attorney", r"custody"],
}

# Case-sensitive patterns (acronyms that collide with common words when lowercased).
_CASE_SENSITIVE = {r"ALS", r"MAID"}

_COMPILED: dict[str, list[re.Pattern[str]]] = {
    topic: [
        re.compile(rf"(?<![\w]){p}(?![\w])", 0 if p in _CASE_SENSITIVE else re.IGNORECASE)
        for p in pats
    ]
    for topic, pats in _KEYWORDS.items()
}


def _topic_value(t: Topic | str) -> str:
    return t.value if isinstance(t, Topic) else str(t)


def tag_topics_safety_net(text: str, topics: list[Topic]) -> list[Topic]:
    """Return `topics` plus any sensitive topics the keyword net detects in `text`.

    Order-preserving and de-duplicated. Never removes a topic the LLM supplied.
    """
    out: list[str] = []
    for t in topics:
        v = _topic_value(t)
        if v not in out:
            out.append(v)
    for topic, pats in _COMPILED.items():
        if topic in out:
            continue
        if any(p.search(text) for p in pats):
            out.append(topic)
    # medication implies health for guard purposes only if the LLM didn't say otherwise:
    # we keep them separate so a "medication-only" rule doesn't catch "I'm tired".
    return [Topic(v) for v in out]


def applicable_rules(person: PersonOut | None, boundaries: list[Boundary]) -> list[Boundary]:
    """Active rules that apply to this conversation partner. Unknown → stranger."""
    relationship = _rel(person)
    person_id = person.id if person else None
    rules: list[Boundary] = []
    for b in boundaries:
        if _val(b.status) != "active":
            continue
        st = _val(b.scope.type)
        if st == "global":
            rules.append(b)
        elif st == "relationship" and b.scope.value == relationship:
            rules.append(b)
        elif st == "person" and person_id is not None and b.scope.value == person_id:
            rules.append(b)
    return rules


def blocked_topics(person: PersonOut | None, boundaries: list[Boundary]) -> list[str]:
    """Union of topics blocked for this person (for the prompt's avoid-list)."""
    out: list[str] = []
    for b in applicable_rules(person, boundaries):
        if _val(b.action) != "block":
            continue
        for t in b.topics:
            v = _topic_value(t)
            if v not in out:
                out.append(v)
    return out


def apply_guard(
    cands: list[Candidate], person: PersonOut | None, boundaries: list[Boundary]
) -> tuple[list[Candidate], list[Candidate]]:
    """Return (allowed[:4], blocked). Deterministic: same input → same output.

    1. safety-net tag every candidate, 2. find applicable active rules,
    3. block on any topic intersection with a `block` rule, 4. keep LLM rank order.
    """
    rules = [b for b in applicable_rules(person, boundaries) if _val(b.action) == "block"]
    allowed: list[Candidate] = []
    blocked: list[Candidate] = []
    for c in cands:
        topics = tag_topics_safety_net(c.text, list(c.topics))
        tv = {_topic_value(t) for t in topics}
        hit = next((r for r in rules if tv & {_topic_value(t) for t in r.topics}), None)
        if hit is not None:
            blocked.append(c.model_copy(update={"topics": topics, "blocked": True, "blocked_by": hit.id}))
        else:
            allowed.append(c.model_copy(update={"topics": topics, "blocked": False, "blocked_by": None}))
    return allowed[:MAX_ALLOWED], blocked


def _rel(person: PersonOut | None) -> str:
    if person is None:
        return "stranger"
    return _val(person.relationship)


def _val(x) -> str:
    return x.value if hasattr(x, "value") else str(x)
