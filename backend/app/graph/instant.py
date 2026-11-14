"""Lane A: instant-stage quick replies. Pure functions: no I/O, no embeddings, no LLM.

The instant stage must put something useful on screen in a few hundred ms even when Voyage is
rate-limited and the phrasebook is nearly empty. It ranks the user's saved phrases (this person ∪
global) by cheap lexical relevance + usage, then tops up with neutral quick replies chosen by the
shape of what was said (greeting, question, thanks, how-are-you). The caller always runs the
result through the deterministic guard before publishing.
"""
from __future__ import annotations

import math
import re

from app.contracts import Candidate, CandidateSource, Memory

TARGET = 4

_WORD = re.compile(r"[a-z']+")
_STOP = frozenset("""a an the and or but if then so to of in on at for with from by is are was were be
been being am i you he she it we they me him her us them my your his its our their this that these
those do does did have has had will would can could should just not no yes ok okay oh hi hey hello
maya what how why when where who""".split())

# Neutral quick replies. Every one is small talk/logistics; the guard still checks them.
# (text, topics, cue): cue selects replies that fit the shape of the partner's utterance.
NEUTRAL: list[tuple[str, list[str], str]] = [
    ("Hi! Good to see you.", ["small_talk"], "greeting"),
    ("Doing okay, thanks. You?", ["small_talk"], "how_are_you"),
    ("Good question. Give me a sec.", ["small_talk"], "question"),
    ("Yes, please.", ["small_talk"], "question"),
    ("You're welcome.", ["small_talk"], "thanks"),
    ("Give me a sec to type.", ["small_talk"], "any"),
    ("Sorry, could you say that again?", ["small_talk"], "any"),
    ("Ha, fair enough.", ["small_talk", "humour"], "any"),
    ("Tell me more.", ["small_talk"], "any"),
]

_CUES = {
    "greeting": re.compile(r"\b(hi|hey|hello|morning|afternoon|evening|good to see)\b", re.I),
    "how_are_you": re.compile(r"how (are|have) you|how'?s it going|how you doing|been feeling|how are things", re.I),
    "thanks": re.compile(r"\b(thanks|thank you|cheers)\b", re.I),
    "question": re.compile(r"\?\s*$"),
}


def tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _signature(text: str) -> set[str]:
    """3-char stems of all words (stop words kept): tolerant to sec/second, type/typing."""
    return {w[:3] for w in _WORD.findall(text.lower()) if len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def cues(text: str) -> set[str]:
    return {name for name, rx in _CUES.items() if rx.search(text)}


def score_phrase(utt_tokens: set[str], phrase: Memory, person_id: str | None) -> float:
    """Lexical overlap dominates; usage and person-specificity break ties."""
    overlap = len(utt_tokens & tokens(phrase.text))
    return (2.0 * overlap
            + 0.5 * math.log1p(max(phrase.uses, 0))
            + (0.75 if person_id and phrase.person_id == person_id else 0.0))


def rank_quick_replies(utterance_text: str, phrases: list[Memory], person_id: str | None,
                       *, limit: int = 8) -> list[Candidate]:
    """Saved phrases (ranked) first, then cue-matched neutral replies, then generic neutral ones.
    Returns more than TARGET so the guard can drop some and still leave 4."""
    utt_tokens = tokens(utterance_text)
    ranked = sorted(phrases, key=lambda m: score_phrase(utt_tokens, m, person_id), reverse=True)
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(c: Candidate) -> None:
        k = c.text.strip().lower()
        if not k or k in seen:
            return
        # skip near-duplicates ("Give me a sec to type." vs "Give me a second to type that.")
        sig = _signature(c.text)
        if sig and any(_jaccard(sig, _signature(o.text)) >= 0.75 for o in out):
            return
        seen.add(k)
        out.append(c)

    for m in ranked[:TARGET]:
        add(Candidate(text=m.text, topics=list(m.topics), source=CandidateSource.phrasebook,
                      memory_ids=[m.id]))
    want = cues(utterance_text)
    for text, topics, cue in NEUTRAL:
        if cue in want:
            add(Candidate(text=text, topics=topics, source=CandidateSource.phrasebook))
    for text, topics, cue in NEUTRAL:
        if cue == "any":
            add(Candidate(text=text, topics=topics, source=CandidateSource.phrasebook))
    return out[:limit]
