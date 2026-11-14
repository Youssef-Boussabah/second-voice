// One session store (Zustand). All server I/O goes through `api`; WS messages land in `handleWs`.
import { create } from "zustand";
import type {
  Boundary, Candidate, PersonContext, PersonOut, RejectReason, Session, SuggestionSet, Utterance, WSMessage,
} from "./contracts";
import { newId } from "./contracts";
import { api, connectSession } from "./lib/api";
import type { WsHandle } from "./lib/ws";
import { speak, stopSpeaking } from "./lib/speech";
import { USE_MOCKS } from "./config";

export type Screen = "talk" | "memory" | "scoreboard";
export type WsStatus = "connecting" | "open" | "closed" | "idle";

export interface Toast {
  id: string;
  tone: "learned" | "memory" | "error" | "info";
  title: string;
  body?: string;
}

export interface PrivacyChange {
  id: string;
  at: string;
  kind: "activated" | "proposed" | "confirmed" | "dismissed";
  boundary: Boundary;
}

interface State {
  screen: Screen;
  people: PersonOut[];
  personId: string | null;
  context: PersonContext | null;
  session: Session | null;
  wsStatus: WsStatus;
  turns: Utterance[];
  suggestions: SuggestionSet | null;
  speakingId: string | null; // candidate id or "typed"
  busy: boolean;
  unknownUtteranceId: string | null;
  boundaries: Boundary[];
  proposed: Boundary | null;
  privacyLog: PrivacyChange[];
  toasts: Toast[];

  setScreen(s: Screen): void;
  init(): Promise<void>;
  choosePerson(id: string): Promise<void>;
  sendIncoming(text: string): Promise<void>;
  assignUnknown(personId: string): Promise<void>;
  speakCandidate(c: Candidate, editedText?: string): Promise<void>;
  speakTyped(text: string): Promise<void>;
  rejectCandidate(c: Candidate, reason: RejectReason): Promise<void>;
  resolveProposed(confirm: boolean): Promise<void>;
  endConversation(): Promise<void>;
  refreshBoundaries(): Promise<void>;
  resetDemo(): Promise<void>;
  pushToast(t: Omit<Toast, "id">): void;
  dismissToast(id: string): void;
}

let ws: WsHandle | null = null;

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export const useStore = create<State>((set, get) => {
  const fail = (where: string) => (e: unknown) => {
    console.error(`[SV] ${where}`, e);
    get().pushToast({ tone: "error", title: `Couldn't ${where}`, body: errMsg(e) });
  };

  // Failure plan: if ElevenLabs is down the narrator must know it was the browser voice.
  const noteVoice = (v: "elevenlabs" | "browser") => {
    if (v === "browser" && !USE_MOCKS) get().pushToast({ tone: "info", title: "Spoken with the browser voice", body: "Cloned voice unavailable right now." });
  };

  const loadContext = async (personId: string) => {
    try {
      const ctx = await api.personContext(personId);
      if (get().personId === personId) set({ context: ctx });
    } catch (e) {
      console.warn("[SV] context unavailable", e);
      set({ context: null });
    }
  };

  const ensureSession = async (): Promise<Session> => {
    const cur = get().session;
    if (cur && cur.status === "active") return cur;
    const s = await api.createSession({ person_id: get().personId });
    set({ session: s, turns: [], suggestions: null });
    ws?.close();
    ws = connectSession(s._id, {
      onMessage: (m) => handleWs(m),
      onStatus: (st) => set({ wsStatus: st }),
      onReconnect: () => {
        api.latest(s._id).then((latest) => latest && acceptSet(latest)).catch(() => undefined);
      },
    });
    return s;
  };

  const acceptSet = (incoming: SuggestionSet) => {
    const cur = get().suggestions;
    // final replaces instant; never let an older/instant set overwrite a newer final one
    if (cur && cur._id === incoming._id && cur.stage === "final" && incoming.stage === "instant") return;
    if (cur && cur._id !== incoming._id && cur.created_at > incoming.created_at) return;
    set({ suggestions: incoming });
    const known = new Set(get().boundaries.map((b) => b._id));
    if (incoming.blocked.some((c) => c.blocked_by && !known.has(c.blocked_by))) void get().refreshBoundaries();
  };

  const logPrivacy = (kind: PrivacyChange["kind"], b: Boundary) =>
    set((s) => ({ privacyLog: [{ id: newId("evt"), at: new Date().toISOString(), kind, boundary: b }, ...s.privacyLog] }));

  const upsertBoundary = (b: Boundary) =>
    set((s) => ({ boundaries: [...s.boundaries.filter((x) => x._id !== b._id), b] }));

  const handleWs = (m: WSMessage) => {
    const sid = get().session?._id;
    if (m.session_id && sid && m.session_id !== sid) return;
    switch (m.type) {
      case "utterance.created":
        set((s) => (s.turns.some((t) => t._id === m.data._id) ? s : { turns: [...s.turns, m.data].slice(-12) }));
        break;
      case "speaker.unknown":
        set({ unknownUtteranceId: m.data.utterance_id });
        break;
      case "suggestions.ready":
        acceptSet(m.data);
        break;
      case "boundary.activated": {
        const b = m.data;
        upsertBoundary(b);
        logPrivacy("activated", b);
        get().pushToast({ tone: "learned", title: learnedTitle(b), body: learnedBody(b) });
        break;
      }
      case "boundary.proposed":
        upsertBoundary(m.data);
        logPrivacy("proposed", m.data);
        set({ proposed: m.data });
        break;
      case "memory.updated": {
        const p = get().people.find((x) => x.id === m.data.person_id);
        get().pushToast({ tone: "memory", title: p ? `Remembered your chat with ${p.name.split(" ")[0]}` : "Memory updated" });
        if (get().personId === m.data.person_id) void loadContext(m.data.person_id);
        break;
      }
      case "error":
        get().pushToast({ tone: "error", title: "Something went wrong", body: `${m.data.where}: ${m.data.message}` });
        break;
    }
  };

  return {
    screen: "talk",
    people: [],
    personId: null,
    context: null,
    session: null,
    wsStatus: "idle",
    turns: [],
    suggestions: null,
    speakingId: null,
    busy: false,
    unknownUtteranceId: null,
    boundaries: [],
    proposed: null,
    privacyLog: [],
    toasts: [],

    setScreen: (screen) => set({ screen }),

    async init() {
      try {
        set({ people: await api.people() });
      } catch (e) {
        fail("load people")(e);
      }
      void get().refreshBoundaries();
    },

    async choosePerson(id) {
      if (get().personId === id) return;
      set({ personId: id, context: null, suggestions: null, unknownUtteranceId: null });
      void loadContext(id);
    },

    async sendIncoming(text) {
      const clean = text.trim();
      if (!clean) return;
      set({ busy: true });
      try {
        const s = await ensureSession();
        const out = await api.postText({ session_id: s._id, text: clean, person_id: get().personId });
        // WS also delivers it; dedupe by id in handleWs
        set((st) => (st.turns.some((t) => t._id === out.utterance._id) ? st : { turns: [...st.turns, out.utterance].slice(-12) }));
      } catch (e) {
        fail("send what they said")(e);
      } finally {
        set({ busy: false });
      }
    },

    async assignUnknown(personId) {
      const uid = get().unknownUtteranceId;
      set({ unknownUtteranceId: null });
      await get().choosePerson(personId);
      if (uid) await api.assignSpeaker(uid, { person_id: personId }).catch(fail("assign speaker"));
    },

    // NOTHING is spoken unless this is called from a user tap.
    async speakCandidate(c, editedText) {
      const set_ = get().suggestions;
      if (!set_ || get().speakingId) return;
      set({ speakingId: c.id });
      try {
        const edited = editedText && editedText.trim() !== c.text ? editedText.trim() : null;
        const out = await api.select(set_._id, { candidate_id: c.id, edited_text: edited, event_id: newId("evt") });
        set((st) => ({
          suggestions: st.suggestions ? { ...st.suggestions, status: "chosen", chosen_candidate_id: c.id } : null,
          turns: st.turns.some((t) => t._id === out.utterance._id) ? st.turns : [...st.turns, out.utterance].slice(-12),
        }));
        noteVoice(await speak(out.text_to_speak));
      } catch (e) {
        fail("speak that")(e);
      } finally {
        set({ speakingId: null });
      }
    },

    async speakTyped(text) {
      const clean = text.trim();
      if (!clean || get().speakingId) return;
      set({ speakingId: "typed" });
      try {
        const s = await ensureSession();
        const out = await api.typedReply({ session_id: s._id, text: clean, event_id: newId("evt") });
        set((st) => ({ turns: st.turns.some((t) => t._id === out.utterance._id) ? st.turns : [...st.turns, out.utterance].slice(-12) }));
        noteVoice(await speak(out.text_to_speak));
      } catch (e) {
        fail("speak your reply")(e);
      } finally {
        set({ speakingId: null });
      }
    },

    async rejectCandidate(c, reason) {
      const set_ = get().suggestions;
      if (!set_) return;
      // hide it immediately; the server decides whether a rule is learned
      set({
        suggestions: { ...set_, candidates: set_.candidates.filter((x) => x.id !== c.id) },
      });
      try {
        await api.reject(set_._id, { candidate_id: c.id, reason, event_id: newId("evt") });
        if (reason !== "too_personal") get().pushToast({ tone: "info", title: "Thanks, noted" });
        else {
          // the learned-rule toast arrives over WS; if it doesn't, still acknowledge the tap
          const before = get().privacyLog.length;
          setTimeout(() => {
            if (get().privacyLog.length === before) get().pushToast({ tone: "info", title: "Noted: too personal", body: "That reply is hidden." });
          }, 5000);
        }
      } catch (e) {
        fail("record that")(e);
      }
    },

    async resolveProposed(confirm) {
      const b = get().proposed;
      if (!b) return;
      set({ proposed: null });
      try {
        const out = confirm ? await api.confirmBoundary(b._id) : await api.dismissBoundary(b._id);
        upsertBoundary(out);
        logPrivacy(confirm ? "confirmed" : "dismissed", out);
        get().pushToast(confirm ? { tone: "learned", title: learnedTitle(out) } : { tone: "info", title: "OK, rule not added" });
      } catch (e) {
        fail("update that rule")(e);
      }
    },

    async endConversation() {
      stopSpeaking();
      const s = get().session;
      // keep the old socket briefly so the end-of-session memory.updated toast still arrives
      const old = ws;
      ws = null;
      setTimeout(() => old?.close(), 5000);
      set({ session: null, turns: [], suggestions: null, wsStatus: "idle", unknownUtteranceId: null });
      if (s) await api.endSession(s._id).catch(fail("end the conversation"));
    },

    async resetDemo() {
      stopSpeaking();
      ws?.close();
      ws = null;
      try {
        await api.resetDemo();
      } catch (e) {
        fail("reset the demo")(e);
        return;
      }
      set({
        screen: "talk", personId: null, context: null, session: null, wsStatus: "idle", turns: [],
        suggestions: null, speakingId: null, busy: false, unknownUtteranceId: null, proposed: null, privacyLog: [],
      });
      await get().init();
      get().pushToast({ tone: "info", title: "Demo reset", body: "Memories and rules re-seeded." });
    },

    async refreshBoundaries() {
      try {
        set({ boundaries: await api.boundaries() });
      } catch (e) {
        console.warn("[SV] boundaries unavailable", e);
      }
    },

    pushToast(t) {
      const id = newId("evt");
      set((s) => ({ toasts: [...s.toasts, { ...t, id }].slice(-3) }));
      setTimeout(() => get().dismissToast(id), t.tone === "error" ? 8000 : 6500);
    },
    dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  };
});

// ---- wording helpers (docs/05-guardrails.md §4) ------------------------------
export const topicLabel = (t: string) => t.replace(/_/g, " ");
export const listJoin = (xs: string[]) =>
  xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} & ${xs[xs.length - 1]}`;

const REL_PLURAL: Record<string, string> = {
  family: "family", close_friend: "close friends", caregiver: "caregivers", clinician: "clinicians",
  service: "service staff", acquaintance: "acquaintances", stranger: "strangers",
};

export function scopeLabel(b: Boundary, people: PersonOut[] = []): string {
  if (b.scope.type === "global") return "everyone";
  if (b.scope.type === "relationship") return REL_PLURAL[b.scope.value ?? ""] ?? topicLabel(b.scope.value ?? "");
  const p = people.find((x) => x.id === b.scope.value);
  return p ? p.name : "one person";
}

export const learnedTitle = (b: Boundary, people?: PersonOut[]) =>
  `Learned: keep ${listJoin(b.topics.map(topicLabel))} private with ${scopeLabel(b, people)}.`;

export const learnedBody = (b: Boundary) =>
  b.validation.replayed > 0
    ? `Checked against ${b.validation.replayed} past replies, ${b.validation.conflicts === 0 ? "no conflicts" : `${b.validation.conflicts} conflicts`}.`
    : undefined;
