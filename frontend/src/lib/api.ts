// Typed client for every endpoint in docs/04-api-contracts.md.
// One interface, two implementations: real HTTP and the in-browser mock (VITE_USE_MOCKS).
import type {
  AssignSpeakerIn, Boundary, PersonContext, PersonCreateIn, PersonOut, RejectIn, Scoreboard,
  SelectIn, SelectOut, Session, SessionStartIn, SuggestionSet, TextUtteranceIn, TypedReplyIn,
  UtteranceOut, WSMessage,
} from "../contracts";
import { API_URL, USE_MOCKS, WS_URL } from "../config";
import { mockApi, mockConnect } from "../mock/mockBackend";
import { connectReconnecting, type WsHandle } from "./ws";

export interface Api {
  health(): Promise<{ ok: boolean; mocks?: Record<string, unknown> }>;
  createSession(body: SessionStartIn): Promise<Session>;
  endSession(id: string): Promise<Session>;
  postText(body: TextUtteranceIn): Promise<UtteranceOut>;
  assignSpeaker(utteranceId: string, body: AssignSpeakerIn): Promise<UtteranceOut>;
  latest(sessionId: string): Promise<SuggestionSet | null>;
  select(setId: string, body: SelectIn): Promise<SelectOut>;
  reject(setId: string, body: RejectIn): Promise<{ ok: boolean }>;
  typedReply(body: TypedReplyIn): Promise<SelectOut>;
  people(): Promise<PersonOut[]>;
  createPerson(body: PersonCreateIn): Promise<PersonOut>;
  /** Returns MP3 audio, or null when the caller should use browser speech. Only call after a user tap. */
  tts(text: string): Promise<Blob | null>;
  boundaries(): Promise<Boundary[]>;
  confirmBoundary(id: string): Promise<Boundary>;
  dismissBoundary(id: string): Promise<Boundary>;
  personContext(personId: string): Promise<PersonContext>;
  scoreboard(): Promise<Scoreboard>;
  resetDemo(): Promise<{ ok: boolean }>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function http<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = (await res.json()) as { detail?: unknown };
      if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* non-JSON body */ }
    throw new ApiError(res.status, `${method} ${path}: ${res.status} ${detail}`);
  }
  return (await res.json()) as T;
}

const realApi: Api = {
  health: () => http("GET", "/api/health"),
  createSession: (b) => http("POST", "/api/sessions", b),
  endSession: (id) => http("POST", `/api/sessions/${id}/end`),
  postText: (b) => http("POST", "/api/utterances/text", b),
  assignSpeaker: (id, b) => http("POST", `/api/utterances/${id}/assign`, b),
  latest: (id) => http("GET", `/api/sessions/${id}/latest`),
  select: (setId, b) => http("POST", `/api/suggestions/${setId}/select`, b),
  reject: (setId, b) => http("POST", `/api/suggestions/${setId}/reject`, b),
  typedReply: (b) => http("POST", "/api/replies/typed", b),
  people: () => http("GET", "/api/people"),
  createPerson: (b) => http("POST", "/api/people", b),
  async tts(text) {
    try {
      const res = await fetch(`${API_URL}/api/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) return null;
      const blob = await res.blob();
      return blob.size > 0 ? blob : null;
    } catch {
      return null; // provider down → browser speech fallback
    }
  },
  boundaries: () => http("GET", "/api/boundaries"),
  confirmBoundary: (id) => http("POST", `/api/boundaries/${id}/confirm`),
  dismissBoundary: (id) => http("POST", `/api/boundaries/${id}/dismiss`),
  personContext: (id) => http("GET", `/api/people/${id}/context`),
  scoreboard: () => http("GET", "/api/eval/scoreboard"),
  resetDemo: () => http("POST", "/api/admin/reset-demo"),
};

export const api: Api = USE_MOCKS ? mockApi : realApi;

export interface WsCallbacks {
  onMessage: (m: WSMessage) => void;
  onStatus: (s: "connecting" | "open" | "closed") => void;
  onReconnect: () => void;
}

export function connectSession(sessionId: string, cb: WsCallbacks): WsHandle {
  if (USE_MOCKS) return mockConnect(sessionId, cb);
  return connectReconnecting(`${WS_URL}/ws?session_id=${encodeURIComponent(sessionId)}`, cb);
}
