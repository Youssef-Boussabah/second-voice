"""Second Voice: shared contracts. Lane A owns this file.

Every shape that crosses a lane boundary (REST body, WebSocket message, MongoDB
document) is defined here. Mirror any change in frontend/src/contracts.ts.
IDs are prefixed strings; datetimes are timezone-aware UTC.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ───────────────────────── helpers ─────────────────────────
def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Doc(BaseModel):
    """Base for Mongo documents: field `id` is stored as `_id`."""
    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    def to_mongo(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="python")


# ───────────────────────── enums ─────────────────────────
class Relationship(str, Enum):
    family = "family"
    close_friend = "close_friend"
    caregiver = "caregiver"
    clinician = "clinician"
    service = "service"
    acquaintance = "acquaintance"
    stranger = "stranger"


class Topic(str, Enum):
    health = "health"
    medication = "medication"
    finances = "finances"
    family_conflict = "family_conflict"
    romance = "romance"
    location_schedule = "location_schedule"
    legal = "legal"
    distress = "distress"
    death_dying = "death_dying"
    work = "work"
    small_talk = "small_talk"
    logistics = "logistics"
    emotions_positive = "emotions_positive"
    humour = "humour"
    hobbies = "hobbies"
    family_news = "family_news"


SENSITIVE_TOPICS: frozenset[str] = frozenset({
    "health", "medication", "finances", "family_conflict", "romance",
    "location_schedule", "legal", "distress", "death_dying",
})


class SpeakerKind(str, Enum):
    partner = "partner"
    user = "user"


class SpeakerMethod(str, Enum):
    voice = "voice"
    manual = "manual"
    forced = "forced"
    unknown = "unknown"


class UtteranceSource(str, Enum):
    stt = "stt"
    text = "text"
    suggestion = "suggestion"
    edited = "edited"
    typed = "typed"


class SuggestionStage(str, Enum):
    instant = "instant"
    final = "final"


class CandidateSource(str, Enum):
    llm = "llm"
    phrasebook = "phrasebook"


class RejectReason(str, Enum):
    too_personal = "too_personal"
    not_my_style = "not_my_style"
    wrong_facts = "wrong_facts"
    other = "other"


class EventType(str, Enum):
    suggestion_selected = "suggestion_selected"
    suggestion_edited = "suggestion_edited"
    reply_typed = "reply_typed"
    suggestion_rejected = "suggestion_rejected"
    session_started = "session_started"
    session_ended = "session_ended"
    speaker_assigned = "speaker_assigned"
    boundary_confirmed = "boundary_confirmed"
    boundary_dismissed = "boundary_dismissed"


class ScopeType(str, Enum):
    global_ = "global"
    relationship = "relationship"
    person = "person"


class BoundaryStatus(str, Enum):
    proposed = "proposed"
    active = "active"
    dismissed = "dismissed"
    retired = "retired"


class BoundaryOrigin(str, Enum):
    seed = "seed"
    learned = "learned"
    manual = "manual"


class MemoryKind(str, Enum):
    episode = "episode"
    phrase = "phrase"
    fact = "fact"


# ───────────────────────── people ─────────────────────────
class Consent(BaseModel):
    voice: bool = False
    at: Optional[datetime] = None


class Person(Doc):
    id: str = Field(default_factory=lambda: new_id("per"), alias="_id")
    user_id: str
    name: str
    relationship: Relationship
    label: str = ""                      # e.g. "Pharmacist at Shoppers"
    notes: str = ""
    consent: Consent = Field(default_factory=Consent)
    voiceprints: list[list[float]] = Field(default_factory=list)   # each 192-d
    voice_centroid: Optional[list[float]] = None                   # 192-d, L2-normalized (index #1)
    last_seen: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class PersonOut(BaseModel):
    """Person without vectors, for the API/UI."""
    model_config = ConfigDict(use_enum_values=True)
    id: str
    name: str
    relationship: Relationship
    label: str = ""
    enrolled: bool = False
    last_seen: Optional[datetime] = None


class PersonCreateIn(BaseModel):
    name: str
    relationship: Relationship
    label: str = ""
    notes: str = ""
    consent_voice: bool = False


class SpeakerMatch(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    kind: SpeakerKind = SpeakerKind.partner
    person_id: Optional[str] = None
    score: Optional[float] = None
    method: SpeakerMethod = SpeakerMethod.unknown


# ───────────────────────── sessions & utterances ─────────────────────────
class Session(Doc):
    id: str = Field(default_factory=lambda: new_id("ses"), alias="_id")
    user_id: str
    person_ids: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None
    status: Literal["active", "ended"] = "active"


class SessionStartIn(BaseModel):
    person_id: Optional[str] = None


class Utterance(Doc):
    id: str = Field(default_factory=lambda: new_id("utt"), alias="_id")
    session_id: str
    user_id: str
    speaker: SpeakerMatch
    text: str
    source: UtteranceSource
    suggestion_set_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class UtteranceOut(BaseModel):
    utterance: Utterance
    latency_ms: dict[str, int] = Field(default_factory=dict)


class TextUtteranceIn(BaseModel):
    session_id: str
    text: str
    person_id: Optional[str] = None      # forced speaker (eval / text mode)


class AssignSpeakerIn(BaseModel):
    person_id: str
    add_voiceprint: bool = False         # Lane B may add the clip to the person's prints


# ───────────────────────── suggestions ─────────────────────────
class Candidate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    id: str = Field(default_factory=lambda: new_id("cand"))
    text: str
    topics: list[Topic] = Field(default_factory=list)
    source: CandidateSource = CandidateSource.llm
    memory_ids: list[str] = Field(default_factory=list)
    blocked: bool = False
    blocked_by: Optional[str] = None     # boundary id


class GeneratedCandidate(BaseModel):
    """What the LLM returns per candidate (no ids)."""
    model_config = ConfigDict(use_enum_values=True)
    text: str
    topics: list[Topic]
    memory_ids: list[str] = Field(default_factory=list)


class GeneratedCandidates(BaseModel):
    candidates: list[GeneratedCandidate]


class SuggestionSet(Doc):
    id: str = Field(default_factory=lambda: new_id("sug"), alias="_id")
    session_id: str
    user_id: str
    utterance_id: str
    person_id: Optional[str] = None
    stage: SuggestionStage
    candidates: list[Candidate] = Field(default_factory=list)   # ≤ 4 allowed
    blocked: list[Candidate] = Field(default_factory=list)
    status: Literal["shown", "chosen", "dismissed"] = "shown"
    chosen_candidate_id: Optional[str] = None
    latency_ms: dict[str, int] = Field(default_factory=dict)
    trace_url: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SelectIn(BaseModel):
    candidate_id: str
    edited_text: Optional[str] = None
    event_id: str = Field(default_factory=lambda: new_id("evt"))   # client-generated for idempotency


class SelectOut(BaseModel):
    utterance: Utterance
    text_to_speak: str


class RejectIn(BaseModel):
    candidate_id: str
    reason: RejectReason
    event_id: str = Field(default_factory=lambda: new_id("evt"))


class TypedReplyIn(BaseModel):
    session_id: str
    text: str
    event_id: str = Field(default_factory=lambda: new_id("evt"))


class TTSIn(BaseModel):
    text: str


# ───────────────────────── memory ─────────────────────────
class OpenThread(BaseModel):
    id: str = Field(default_factory=lambda: new_id("thr"))
    text: str
    owner: Literal["user", "partner"]
    status: Literal["open", "resolved"] = "open"


class Memory(Doc):
    id: str = Field(default_factory=lambda: new_id("mem"), alias="_id")
    user_id: str
    person_id: str                      # person id or "global"
    kind: MemoryKind
    subkind: Optional[str] = None       # fact: "person" | "style"
    status: Literal["active", "retired"] = "active"
    text: str
    topics: list[Topic] = Field(default_factory=list)
    open_threads: list[OpenThread] = Field(default_factory=list)   # episodes only
    uses: int = 0                       # phrases only
    last_used: Optional[datetime] = None
    origin: Optional[str] = None        # phrases: selected | edited | typed | seed
    session_id: Optional[str] = None
    embedding: Optional[list[float]] = None    # 1024-d (index #2)
    created_at: datetime = Field(default_factory=utcnow)


class EpisodeSummary(BaseModel):
    """LLM output schema for Lane D's session summarizer."""
    model_config = ConfigDict(use_enum_values=True)
    summary: str
    topics: list[Topic]
    open_threads_new: list[OpenThread] = Field(default_factory=list)
    threads_resolved_ids: list[str] = Field(default_factory=list)


class RetrievedContext(BaseModel):
    person: Optional[PersonOut] = None
    recent_episodes: list[Memory] = Field(default_factory=list)
    relevant_episodes: list[Memory] = Field(default_factory=list)
    open_threads: list[OpenThread] = Field(default_factory=list)
    phrases: list[Memory] = Field(default_factory=list)
    facts: list[Memory] = Field(default_factory=list)
    boundaries: list["Boundary"] = Field(default_factory=list)
    recent_turns: list[Utterance] = Field(default_factory=list)


class PersonContext(BaseModel):
    person: PersonOut
    last_episode: Optional[Memory] = None
    open_threads: list[OpenThread] = Field(default_factory=list)
    top_phrases: list[str] = Field(default_factory=list)


# ───────────────────────── boundaries ─────────────────────────
class BoundaryScope(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    type: ScopeType
    value: Optional[str] = None         # relationship name or person id; None for global


class BoundaryEvidence(BaseModel):
    trigger_event_id: Optional[str] = None
    rejected_text: Optional[str] = None
    person_id: Optional[str] = None


class BoundaryValidation(BaseModel):
    replayed: int = 0
    conflicts: int = 0
    conflict_event_ids: list[str] = Field(default_factory=list)
    passed: bool = False
    narrowed_from: Optional[str] = None


class Boundary(Doc):
    id: str = Field(default_factory=lambda: new_id("bnd"), alias="_id")
    user_id: str
    scope: BoundaryScope
    topics: list[Topic]
    action: Literal["block", "confirm"] = "block"
    status: BoundaryStatus = BoundaryStatus.proposed
    origin: BoundaryOrigin = BoundaryOrigin.learned
    evidence: BoundaryEvidence = Field(default_factory=BoundaryEvidence)
    validation: BoundaryValidation = Field(default_factory=BoundaryValidation)
    created_at: datetime = Field(default_factory=utcnow)
    activated_at: Optional[datetime] = None


RetrievedContext.model_rebuild()


# ───────────────────────── events ─────────────────────────
class Event(Doc):
    id: str = Field(default_factory=lambda: new_id("evt"), alias="_id")
    user_id: str
    type: EventType
    session_id: Optional[str] = None
    person_id: Optional[str] = None
    relationship: Optional[Relationship] = None     # denormalized for replay
    suggestion_set_id: Optional[str] = None
    candidate_id: Optional[str] = None
    boundary_id: Optional[str] = None
    text: Optional[str] = None
    topics: list[Topic] = Field(default_factory=list)
    reason: Optional[RejectReason] = None
    created_at: datetime = Field(default_factory=utcnow)


# ───────────────────────── realtime ─────────────────────────
WSType = Literal[
    "utterance.created", "speaker.unknown", "suggestions.ready",
    "boundary.proposed", "boundary.activated", "memory.updated", "error",
]


class WSMessage(BaseModel):
    type: WSType
    session_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


# ───────────────────────── pipeline state (LangGraph) ─────────────────────────
class PipelineState(BaseModel):
    utterance: Utterance
    person: Optional[PersonOut] = None
    context: Optional[RetrievedContext] = None
    generated: list[Candidate] = Field(default_factory=list)
    allowed: list[Candidate] = Field(default_factory=list)
    blocked: list[Candidate] = Field(default_factory=list)
    regenerations: int = 0
    timings_ms: dict[str, int] = Field(default_factory=dict)


# ───────────────────────── eval ─────────────────────────
class ConfigMetrics(BaseModel):
    hit_at_4: float
    taps_per_message: float
    leaks_per_conversation: float
    latency_p50_ms: int
    latency_p95_ms: int
    rules_learned: int = 0
    false_positive_rules: int = 0
    runs: int = 1


class Scoreboard(BaseModel):
    cold: Optional[ConfigMetrics] = None
    warm: Optional[ConfigMetrics] = None
    notes: str = ""
    updated_at: datetime = Field(default_factory=utcnow)
