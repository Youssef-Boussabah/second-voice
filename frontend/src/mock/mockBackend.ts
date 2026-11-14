// In-browser fake of the Second Voice backend (REST + WS), used when VITE_USE_MOCKS=true.
// It mirrors the contracts exactly and runs a tiny deterministic guard so the privacy demo works offline.
import type {
  Boundary, Candidate, Memory, PersonContext, PersonOut, Relationship, Scoreboard, Session,
  SuggestionSet, Topic, Utterance, WSMessage,
} from "../contracts";
import { SENSITIVE_TOPICS, newId } from "../contracts";
import type { Api, WsCallbacks } from "../lib/api";
import type { WsHandle } from "../lib/ws";

const USER = "usr_maya";
const now = () => new Date().toISOString();
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

const PEOPLE: PersonOut[] = [
  { id: "per_dana", name: "Dana Okafor", relationship: "clinician", label: "Pharmacist", enrolled: true, last_seen: "2026-10-28T15:10:00Z" },
  { id: "per_mike", name: "Mike Chen", relationship: "acquaintance", label: "Neighbour", enrolled: true, last_seen: "2026-11-02T18:30:00Z" },
  { id: "per_sam", name: "Sam Rivera", relationship: "close_friend", label: "Old friend", enrolled: false, last_seen: "2026-11-09T20:00:00Z" },
];

const mem = (person_id: string, text: string, topics: Topic[], threads: { text: string; owner: "user" | "partner" }[], created_at: string): Memory => ({
  _id: newId("mem"), user_id: USER, person_id, kind: "episode", subkind: null, status: "active", text, topics,
  open_threads: threads.map((t) => ({ id: newId("thr"), text: t.text, owner: t.owner, status: "open" })),
  uses: 3, last_used: created_at, origin: "seed", session_id: null, created_at,
});

const EPISODES: Record<string, Memory> = {
  per_dana: mem("per_dana", "Picked up the October refill. Dana suggested blister packs and said she'd order them in.", ["medication", "logistics"], [{ text: "Dana was checking on blister packs", owner: "partner" }], "2026-10-28T15:10:00Z"),
  per_mike: mem("per_mike", "Chatted about the Leafs game and Mike's new puppy, Biscuit.", ["small_talk", "hobbies"], [{ text: "Ask how Biscuit's training is going", owner: "user" }], "2026-11-02T18:30:00Z"),
  per_sam: mem("per_sam", "Sam visited; talked about the new meds and planning a trip to the lake in spring.", ["health", "emotions_positive"], [{ text: "Plan the lake trip dates", owner: "user" }], "2026-11-09T20:00:00Z"),
};

const PHRASES: Record<string, string[]> = {
  per_dana: ["Same as last time, please", "Thanks Dana"],
  per_mike: ["Go Leafs!", "How's Biscuit?"],
  per_sam: ["Love you, Sam", "You always make me laugh"],
};

let boundaries: Boundary[] = [
  {
    _id: "bnd_seed_strangers", user_id: USER, scope: { type: "relationship", value: "stranger" },
    topics: ["health", "medication", "location_schedule", "finances"], action: "block", status: "active", origin: "seed",
    evidence: { trigger_event_id: null, rejected_text: null, person_id: null },
    validation: { replayed: 0, conflicts: 0, conflict_event_ids: [], passed: true, narrowed_from: null },
    created_at: "2026-10-01T12:00:00Z", activated_at: "2026-10-01T12:00:00Z",
  },
];

const sessions = new Map<string, Session>();
const latestBySession = new Map<string, SuggestionSet>();
const sets = new Map<string, SuggestionSet>();
const sockets = new Map<string, Set<WsCallbacks>>();

function emit(sessionId: string | null, msg: WSMessage) {
  const targets = sessionId ? [sockets.get(sessionId)] : [...sockets.values()];
  for (const subs of targets) subs?.forEach((cb) => setTimeout(() => cb.onMessage(msg), 0));
}

// ---- candidate generation (stand-in for Lane A's pipeline) -----------------
type Draft = [string, Topic[]];
function draftsFor(text: string, person: PersonOut | undefined): Draft[] {
  const t = text.toLowerCase();
  const rel = person?.relationship;
  if (/refill|prescription|pick.?up/.test(t))
    return [["Yes please, same as October", ["medication", "logistics"]], ["Did the blister packs come in?", ["medication", "logistics"]], ["The new generic has been fine so far", ["medication", "health"]], ["Thanks Dana, how's your week going?", ["small_talk"]], ["Can I pay on my card again?", ["finances"]], ["Not today, maybe Friday", ["logistics"]]];
  if (/side effect|dizzy|generic|dose|meds?\b|medication/.test(t))
    return [["A little dizzy in the mornings", ["health", "medication"]], ["No side effects so far, thanks", ["medication"]], ["Should I take it with food?", ["medication"]], ["Can we go over it next visit?", ["logistics"]], ["Sleeping a bit worse lately", ["health"]], ["All good, thanks for checking", ["small_talk"]]];
  if (/anything new|what'?s new|news|up to/.test(t))
    return [["My sister's visiting next week", ["family_news"]], ["The doctor upped my dose", ["health", "medication"]], ["Started a new puzzle book", ["hobbies"]], ["Not much, quiet week", ["small_talk"]], ["How's Biscuit doing?", ["small_talk", "hobbies"]]];
  if (/how.*(been|are you|doing)|hi |hey|hello/.test(t))
    return [["Pretty good, thanks! You?", ["small_talk"]], ["Honestly the new meds have been rough.", ["health", "medication"]], [rel === "acquaintance" ? "Did you catch the Leafs game?" : "Busy week, but good.", ["small_talk", "hobbies"]], ["So nice to see you!", ["emotions_positive"]], ["Tired, but hanging in there", ["health", "distress"]], ["Can't complain!", ["humour"]]];
  return [["Yes", ["small_talk"]], ["No, thank you", ["small_talk"]], ["Can you say that again?", ["small_talk"]], ["Give me a moment to type", ["small_talk"]], ["That sounds great", ["emotions_positive"]], ["I'm not sure yet", ["small_talk"]]];
}

function guard(cands: Candidate[], person: PersonOut | undefined): [Candidate[], Candidate[]] {
  const allowed: Candidate[] = [];
  const blocked: Candidate[] = [];
  const active = boundaries.filter((b) => b.status === "active" && b.action === "block");
  for (const c of cands) {
    const hit = active.find((b) => {
      const scoped = b.scope.type === "global"
        || (b.scope.type === "relationship" && person?.relationship === b.scope.value)
        || (b.scope.type === "person" && person?.id === b.scope.value);
      return scoped && c.topics.some((tp) => b.topics.includes(tp));
    });
    if (hit) blocked.push({ ...c, blocked: true, blocked_by: hit._id });
    else allowed.push(c);
  }
  return [allowed, blocked];
}

async function runPipeline(utt: Utterance, personId: string | null) {
  const person = PEOPLE.find((p) => p.id === personId);
  const drafts = draftsFor(utt.text, person);
  const mk = (d: Draft, source: Candidate["source"]): Candidate => ({
    id: newId("cand"), text: d[0], topics: d[1], source,
    memory_ids: personId && EPISODES[personId] && source === "llm" ? [EPISODES[personId]._id] : [],
    blocked: false, blocked_by: null,
  });
  const setId = newId("sug");
  const base = (stage: SuggestionSet["stage"], cands: Candidate[], blocked: Candidate[], ms: number): SuggestionSet => ({
    _id: setId, session_id: utt.session_id, user_id: USER, utterance_id: utt._id, person_id: personId,
    stage, candidates: cands, blocked, status: "shown", chosen_candidate_id: null,
    latency_ms: { total: ms }, trace_url: null, created_at: now(), updated_at: now(),
  });
  // instant stage: phrasebook-ish (first 2 drafts + generic)
  await wait(250);
  const [instAllowed, instBlocked] = guard([...drafts.slice(0, 2), ["Give me a moment to type", ["small_talk"]] as Draft].map((d) => mk(d, "phrasebook")), person);
  const inst = base("instant", instAllowed.slice(0, 4), instBlocked, 250);
  latestBySession.set(utt.session_id, inst);
  sets.set(setId, inst);
  emit(utt.session_id, { type: "suggestions.ready", session_id: utt.session_id, data: inst });
  // final stage
  await wait(900);
  const [allowed, blocked] = guard(drafts.map((d) => mk(d, "llm")), person);
  const fin = { ...base("final", allowed.slice(0, 4), blocked, 1150), created_at: now() };
  latestBySession.set(utt.session_id, fin);
  sets.set(setId, fin);
  emit(utt.session_id, { type: "suggestions.ready", session_id: utt.session_id, data: fin });
}

function userUtterance(sessionId: string, text: string, source: Utterance["source"], setId: string | null): Utterance {
  const u: Utterance = {
    _id: newId("utt"), session_id: sessionId, user_id: USER, text, source, suggestion_set_id: setId, created_at: now(),
    speaker: { kind: "user", person_id: null, score: null, method: "manual" },
  };
  emit(sessionId, { type: "utterance.created", session_id: sessionId, data: u });
  return u;
}

function notFound(what: string): never {
  throw new Error(`mock 404: ${what}`);
}

export const mockApi: Api = {
  async health() { return { ok: true, mocks: { frontend: true } }; },
  async createSession(b) {
    const s: Session = { _id: newId("ses"), user_id: USER, person_ids: b.person_id ? [b.person_id] : [], started_at: now(), ended_at: null, status: "active" };
    sessions.set(s._id, s);
    return s;
  },
  async endSession(id) {
    const s = sessions.get(id) ?? notFound(id);
    const ended: Session = { ...s, status: "ended", ended_at: now() };
    sessions.set(id, ended);
    const pid = s.person_ids[s.person_ids.length - 1];
    if (pid) setTimeout(() => emit(null, { type: "memory.updated", session_id: null, data: { person_id: pid, kind: "episode" } }), 600);
    return ended;
  },
  async postText(b) {
    await wait(80);
    const s = sessions.get(b.session_id) ?? notFound(b.session_id);
    if (b.person_id && !s.person_ids.includes(b.person_id)) s.person_ids.push(b.person_id);
    const u: Utterance = {
      _id: newId("utt"), session_id: b.session_id, user_id: USER, text: b.text, source: "text", suggestion_set_id: null, created_at: now(),
      speaker: { kind: "partner", person_id: b.person_id ?? null, score: null, method: b.person_id ? "forced" : "unknown" },
    };
    emit(b.session_id, { type: "utterance.created", session_id: b.session_id, data: u });
    if (!b.person_id) {
      emit(b.session_id, { type: "speaker.unknown", session_id: b.session_id, data: { utterance_id: u._id, candidates: PEOPLE } });
    } else void runPipeline(u, b.person_id);
    return { utterance: u, latency_ms: { insert: 80 } };
  },
  async assignSpeaker(id, b) {
    const u: Utterance = {
      _id: id, session_id: [...sessions.keys()].pop() ?? "", user_id: USER, text: "", source: "text", suggestion_set_id: null, created_at: now(),
      speaker: { kind: "partner", person_id: b.person_id, score: null, method: "manual" },
    };
    return { utterance: u, latency_ms: {} };
  },
  async latest(id) { return latestBySession.get(id) ?? null; },
  async select(setId, b) {
    await wait(60);
    const set = sets.get(setId) ?? notFound(setId);
    const c = set.candidates.find((x) => x.id === b.candidate_id) ?? notFound(b.candidate_id);
    set.status = "chosen";
    set.chosen_candidate_id = c.id;
    const text = b.edited_text?.trim() || c.text;
    const u = userUtterance(set.session_id, text, b.edited_text ? "edited" : "suggestion", setId);
    return { utterance: u, text_to_speak: text };
  },
  async reject(setId, b) {
    await wait(60);
    const set = sets.get(setId) ?? notFound(setId);
    const c = set.candidates.find((x) => x.id === b.candidate_id);
    const person = PEOPLE.find((p) => p.id === set.person_id);
    if (b.reason === "too_personal" && c && person) {
      const topics = c.topics.filter((t) => SENSITIVE_TOPICS.includes(t));
      if (topics.length) {
        const bnd: Boundary = {
          _id: newId("bnd"), user_id: USER, scope: { type: "relationship", value: person.relationship }, topics,
          action: "block", status: "active", origin: "learned",
          evidence: { trigger_event_id: b.event_id, rejected_text: c.text, person_id: person.id },
          validation: { replayed: 23, conflicts: 0, conflict_event_ids: [], passed: true, narrowed_from: null },
          created_at: now(), activated_at: now(),
        };
        boundaries = [...boundaries, bnd];
        setTimeout(() => emit(null, { type: "boundary.activated", session_id: null, data: bnd }), 700);
      }
    }
    return { ok: true };
  },
  async typedReply(b) {
    const u = userUtterance(b.session_id, b.text, "typed", null);
    return { utterance: u, text_to_speak: b.text };
  },
  async people() { return PEOPLE; },
  async createPerson(b) {
    const p: PersonOut = { id: newId("per"), name: b.name, relationship: b.relationship, label: b.label ?? "", enrolled: false, last_seen: null };
    PEOPLE.push(p);
    return p;
  },
  async tts() { return null; },
  async boundaries() { return boundaries; },
  async confirmBoundary(id) {
    boundaries = boundaries.map((b) => (b._id === id ? { ...b, status: "active", activated_at: now() } : b));
    return boundaries.find((b) => b._id === id) ?? notFound(id);
  },
  async dismissBoundary(id) {
    boundaries = boundaries.map((b) => (b._id === id ? { ...b, status: "dismissed" } : b));
    return boundaries.find((b) => b._id === id) ?? notFound(id);
  },
  async personContext(id): Promise<PersonContext> {
    const person = PEOPLE.find((p) => p.id === id) ?? notFound(id);
    const ep = EPISODES[id] ?? null;
    return { person, last_episode: ep, open_threads: ep?.open_threads ?? [], top_phrases: PHRASES[id] ?? [] };
  },
  async scoreboard(): Promise<Scoreboard> {
    return {
      cold: { hit_at_4: 0.31, taps_per_message: 9.4, leaks_per_conversation: 1.2, latency_p50_ms: 1450, latency_p95_ms: 2600, rules_learned: 0, false_positive_rules: 0, runs: 12 },
      warm: { hit_at_4: 0.58, taps_per_message: 4.1, leaks_per_conversation: 0.1, latency_p50_ms: 1180, latency_p95_ms: 2100, rules_learned: 3, false_positive_rules: 0, runs: 12 },
      notes: "MOCK DATA: replace with GET /api/eval/scoreboard from Lane D.",
      updated_at: now(),
    };
  },
  async resetDemo() {
    boundaries = boundaries.filter((b) => b.origin === "seed");
    return { ok: true };
  },
};

/** Exported for the "Simulate proposed rule" demo control in mock mode only. */
export function mockProposeBoundary(rel: Relationship, topics: Topic[]) {
  const bnd: Boundary = {
    _id: newId("bnd"), user_id: USER, scope: { type: "relationship", value: rel }, topics, action: "block",
    status: "proposed", origin: "learned",
    evidence: { trigger_event_id: null, rejected_text: "I'm seeing the specialist on Tuesday", person_id: null },
    validation: { replayed: 23, conflicts: 2, conflict_event_ids: [], passed: false, narrowed_from: null },
    created_at: now(), activated_at: null,
  };
  boundaries = [...boundaries, bnd];
  emit(null, { type: "boundary.proposed", session_id: null, data: bnd });
}

export function mockConnect(sessionId: string, cb: WsCallbacks): WsHandle {
  const subs = sockets.get(sessionId) ?? new Set<WsCallbacks>();
  subs.add(cb);
  sockets.set(sessionId, subs);
  cb.onStatus("connecting");
  setTimeout(() => cb.onStatus("open"), 150);
  return {
    close() {
      subs.delete(cb);
    },
  };
}
