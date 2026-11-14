# 04: API contracts (REST + WebSocket + cross-lane functions)

Base URL `http://localhost:8000`. JSON bodies are the Pydantic models in `backend/app/contracts.py`, mirrored in `frontend/src/contracts.ts`. `DEMO_USER_ID` is implied (no auth today).

## 1. REST

### Lane A: `api/core_routes.py`
| Method | Path | Body → Response | Notes |
|---|---|---|---|
| GET | `/api/health` | → `{"ok":true,"mocks":{...}}` | smoke test |
| POST | `/api/sessions` | `SessionStartIn` → `Session` | writes `session_started` event |
| POST | `/api/sessions/{id}/end` | → `Session` | writes `session_ended` event (worker summarizes) |
| POST | `/api/utterances/text` | `TextUtteranceIn` → `UtteranceOut` | typed partner turn; `person_id` optional (forced speaker); triggers pipeline |
| POST | `/api/utterances/{id}/assign` | `AssignSpeakerIn` → `UtteranceOut` | "Who's this?" answer; reruns pipeline; writes `speaker_assigned` |
| GET | `/api/sessions/{id}/latest` | → `SuggestionSet \| null` | for WS reconnect |
| POST | `/api/suggestions/{set_id}/select` | `SelectIn` → `SelectOut` | writes `suggestion_selected` or `suggestion_edited` + a user `Utterance`; returns final text to speak |
| POST | `/api/suggestions/{set_id}/reject` | `RejectIn` → `{"ok":true}` | writes `suggestion_rejected` |
| POST | `/api/replies/typed` | `TypedReplyIn` → `SelectOut` | user typed their own reply; writes `reply_typed` |
| GET | `/api/people` | → `list[PersonOut]` | (no vectors) |

### Lane B: `api/voice_routes.py`
| Method | Path | Body → Response | Notes |
|---|---|---|---|
| POST | `/api/utterances/audio` | multipart: `session_id`, `audio` (WAV 16 kHz mono) → `UtteranceOut` | STT ‖ speaker ID, insert utterance, trigger pipeline |
| POST | `/api/people` | `PersonCreateIn` → `PersonOut` | requires `consent_voice=true` to enroll later |
| POST | `/api/people/{id}/enroll` | multipart: `clips[]` (3 WAVs, ~5 s each) → `PersonOut` | computes voiceprints + centroid |
| POST | `/api/tts` | `TTSIn` → `audio/mpeg` stream | cloned voice; **only called after a user tap** |
| GET | `/api/voice/status` | → `{"stt":"ok|mock","speaker":"ok|mock","tts":"ok|mock"}` | |

### Lane D: `api/learning_routes.py`
| Method | Path | Body → Response |
|---|---|---|
| GET | `/api/boundaries` | → `list[Boundary]` |
| POST | `/api/boundaries/{id}/confirm` | → `Boundary` (writes `boundary_confirmed`) |
| POST | `/api/boundaries/{id}/dismiss` | → `Boundary` (writes `boundary_dismissed`) |
| GET | `/api/people/{id}/context` | → `PersonContext` (episodes, open threads, top phrases; for the UI header) |
| GET | `/api/eval/scoreboard` | → `Scoreboard` |
| POST | `/api/admin/reset-demo` | → `{"ok":true}` (re-seed; demo only) |

## 2. WebSocket `/ws?session_id=ses_x` (Lane A hub)
Server → client messages are `WSMessage {type, session_id, data}`:
| `type` | `data` | When |
|---|---|---|
| `utterance.created` | `Utterance` | any utterance inserted for the session (partner or user) |
| `speaker.unknown` | `{utterance_id, candidates: PersonOut[]}` | speaker score below threshold |
| `suggestions.ready` | `SuggestionSet` | stage instant **and** final (client renders the latest by `created_at`; final replaces instant) |
| `boundary.proposed` | `Boundary` | replay found conflicts, so the user must confirm |
| `boundary.activated` | `Boundary` | rule learned → toast |
| `memory.updated` | `{person_id, kind}` | episode or phrase written (refresh header) |
| `error` | `{message, where}` | non-fatal |

Client → server: `{"type":"ping"}` only. Everything else goes over REST.

Source of each WS message: the hub tails change streams on `suggestion_sets`, `boundaries`, `utterances`, `memories` (filtered by `user_id`) and fans out by `session_id`. Boundary and memory messages go to **all** open sessions of the user. If `USE_CHANGE_STREAMS=false`, code paths call `realtime.hub.broadcast()` directly (fallback).

## 3. Status codes
200 OK · 400 invalid · 404 not found · 409 consent missing · 503 provider down (body says which; the client falls back).

## 4. Cross-lane Python functions (stubs exist; keep these signatures)
```python
# Lane A: app/graph/pipeline.py
async def on_partner_utterance(utt: Utterance) -> None
    """Run instant + final suggestion stages. Never raises; logs + emits WS error."""

# Lane A: app/embeddings.py
async def embed(texts: list[str], input_type: Literal["query","document"]) -> list[list[float]]

# Lane A: app/llm.py
async def complete_json(system: str, user: str, schema: type[BaseModel], *, model: str | None = None) -> BaseModel

# Lane A: app/guard/enforce.py
def apply_guard(cands: list[Candidate], person: PersonOut | None, boundaries: list[Boundary]) -> tuple[list[Candidate], list[Candidate]]
    """returns (allowed, blocked). Pure function. Must be deterministic."""
def tag_topics_safety_net(text: str, topics: list[Topic]) -> list[Topic]

# Lane B: app/voice/speaker.py
async def embed_voice(wav_bytes: bytes) -> list[float]            # 192-d, L2-normalized
async def identify(user_id: str, wav_bytes: bytes) -> SpeakerMatch

# Lane B: app/voice/stt.py
async def transcribe(wav_bytes: bytes) -> str

# Lane B: app/voice/tts.py
async def speak_stream(text: str) -> AsyncIterator[bytes]

# Lane D: app/learning/boundaries.py
async def propose_and_validate(evt: Event) -> Boundary | None     # used by worker AND eval
```
