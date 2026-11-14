// Second Voice: TypeScript mirror of backend/app/contracts.py. Lane C keeps this in sync.
// Datetimes arrive as ISO-8601 strings. IDs are prefixed strings.

export type Relationship =
  | "family" | "close_friend" | "caregiver" | "clinician" | "service" | "acquaintance" | "stranger";

export type Topic =
  | "health" | "medication" | "finances" | "family_conflict" | "romance" | "location_schedule"
  | "legal" | "distress" | "death_dying" | "work" | "small_talk" | "logistics"
  | "emotions_positive" | "humour" | "hobbies" | "family_news";

export const SENSITIVE_TOPICS: Topic[] = [
  "health", "medication", "finances", "family_conflict", "romance",
  "location_schedule", "legal", "distress", "death_dying",
];

export type SpeakerKind = "partner" | "user";
export type SpeakerMethod = "voice" | "manual" | "forced" | "unknown";
export type UtteranceSource = "stt" | "text" | "suggestion" | "edited" | "typed";
export type SuggestionStage = "instant" | "final";
export type CandidateSource = "llm" | "phrasebook";
export type RejectReason = "too_personal" | "not_my_style" | "wrong_facts" | "other";
export type ScopeType = "global" | "relationship" | "person";
export type BoundaryStatus = "proposed" | "active" | "dismissed" | "retired";
export type BoundaryOrigin = "seed" | "learned" | "manual";
export type MemoryKind = "episode" | "phrase" | "fact";

export interface PersonOut {
  id: string; name: string; relationship: Relationship; label: string;
  enrolled: boolean; last_seen: string | null;
}
export interface PersonCreateIn {
  name: string; relationship: Relationship; label?: string; notes?: string; consent_voice: boolean;
}
export interface SpeakerMatch {
  kind: SpeakerKind; person_id: string | null; score: number | null; method: SpeakerMethod;
}
export interface Session {
  _id: string; user_id: string; person_ids: string[]; started_at: string;
  ended_at: string | null; status: "active" | "ended";
}
export interface SessionStartIn { person_id?: string | null }

export interface Utterance {
  _id: string; session_id: string; user_id: string; speaker: SpeakerMatch; text: string;
  source: UtteranceSource; suggestion_set_id: string | null; created_at: string;
}
export interface UtteranceOut { utterance: Utterance; latency_ms: Record<string, number> }
export interface TextUtteranceIn { session_id: string; text: string; person_id?: string | null }
export interface AssignSpeakerIn { person_id: string; add_voiceprint?: boolean }

export interface Candidate {
  id: string; text: string; topics: Topic[]; source: CandidateSource; memory_ids: string[];
  blocked: boolean; blocked_by: string | null;
}
export interface SuggestionSet {
  _id: string; session_id: string; user_id: string; utterance_id: string; person_id: string | null;
  stage: SuggestionStage; candidates: Candidate[]; blocked: Candidate[];
  status: "shown" | "chosen" | "dismissed"; chosen_candidate_id: string | null;
  latency_ms: Record<string, number>; trace_url: string | null; created_at: string; updated_at: string;
}
export interface SelectIn { candidate_id: string; edited_text?: string | null; event_id: string }
export interface SelectOut { utterance: Utterance; text_to_speak: string }
export interface RejectIn { candidate_id: string; reason: RejectReason; event_id: string }
export interface TypedReplyIn { session_id: string; text: string; event_id: string }
export interface TTSIn { text: string }

export interface OpenThread { id: string; text: string; owner: "user" | "partner"; status: "open" | "resolved" }
export interface Memory {
  _id: string; user_id: string; person_id: string; kind: MemoryKind; subkind: string | null;
  status: "active" | "retired"; text: string; topics: Topic[]; open_threads: OpenThread[];
  uses: number; last_used: string | null; origin: string | null; session_id: string | null;
  created_at: string; // embedding is never sent to the UI
}
export interface PersonContext {
  person: PersonOut; last_episode: Memory | null; open_threads: OpenThread[]; top_phrases: string[];
}

export interface BoundaryScope { type: ScopeType; value: string | null }
export interface Boundary {
  _id: string; user_id: string; scope: BoundaryScope; topics: Topic[]; action: "block" | "confirm";
  status: BoundaryStatus; origin: BoundaryOrigin;
  evidence: { trigger_event_id: string | null; rejected_text: string | null; person_id: string | null };
  validation: { replayed: number; conflicts: number; conflict_event_ids: string[]; passed: boolean; narrowed_from: string | null };
  created_at: string; activated_at: string | null;
}

export type WSType =
  | "utterance.created" | "speaker.unknown" | "suggestions.ready"
  | "boundary.proposed" | "boundary.activated" | "memory.updated" | "error";

export type WSMessage =
  | { type: "utterance.created"; session_id: string | null; data: Utterance }
  | { type: "speaker.unknown"; session_id: string | null; data: { utterance_id: string; candidates: PersonOut[] } }
  | { type: "suggestions.ready"; session_id: string | null; data: SuggestionSet }
  | { type: "boundary.proposed"; session_id: string | null; data: Boundary }
  | { type: "boundary.activated"; session_id: string | null; data: Boundary }
  | { type: "memory.updated"; session_id: string | null; data: { person_id: string; kind: MemoryKind } }
  | { type: "error"; session_id: string | null; data: { message: string; where: string } };

export interface ConfigMetrics {
  hit_at_4: number; taps_per_message: number; leaks_per_conversation: number;
  latency_p50_ms: number; latency_p95_ms: number; rules_learned: number;
  false_positive_rules: number; runs: number;
}
export interface Scoreboard { cold: ConfigMetrics | null; warm: ConfigMetrics | null; notes: string; updated_at: string }

export const newId = (prefix: string) =>
  `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
