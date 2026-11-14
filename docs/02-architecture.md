# 02: Architecture

## System diagram
```
 ┌──────────────────────── Tablet web app (Lane C, React) ────────────────────────┐
 │ mic → VAD (@ricky0123/vad-web, 16 kHz) → WAV blob            WebSocket client  │
 │ suggestion cards · tap/edit/type · long-press reject · "Who's this?" · toasts  │
 └───────┬───────────────────────────────┬───────────────────────────▲────────────┘
         │ POST /api/utterances/audio    │ POST /select /reject /tts │ WS /ws
         ▼                               ▼                           │
 ┌──────────────── FastAPI backend (uvicorn, one process) ───────────┴────────────┐
 │ Lane B voice/            Lane A graph/ (LangGraph)          Lane A realtime/   │
 │  ├ stt.py  (Scribe v2)    identify → retrieve → generate     WS hub ◄── change │
 │  ├ speaker.py (ECAPA)     → guard → publish                  streams on        │
 │  └ tts.py (Flash, clone)  checkpointer: MongoDBSaver         suggestion_sets,  │
 │                           Lane A memory/ (hybrid retrieval)  boundaries        │
 │                           Lane A guard/  (deterministic)                       │
 └──────────────┬──────────────────────────────┬──────────────────────────────────┘
                │ reads/writes                 │ inserts events
                ▼                              ▼
 ┌──────────────────────────── MongoDB Atlas ─────────────────────────────────────┐
 │ people(voice_centroid ⟵ VECTOR idx #1) · memories(embedding ⟵ VECTOR idx #2,   │
 │ text ⟵ SEARCH idx #3) · sessions · utterances · suggestion_sets · boundaries · │
 │ events · audio_clips(TTL 1h) · eval_runs · checkpoints (LangGraph)             │
 └──────────────────────────────▲──────────────────────────────────────────────────┘
                                │ change stream on `events`
 ┌──────────────────────────────┴───── Learning worker (Lane D, separate proc) ────┐
 │ selected/edited/typed → phrasebook upsert   rejected(too_personal) → propose   │
 │ boundary → REPLAY validate → activate/ask   session_ended → episode summary +  │
 │ open threads (LLM) → memories                                                  │
 └─────────────────────────────────────────────────────────────────────────────────┘
 External: ElevenLabs (STT, TTS, voice clone) · Voyage AI (voyage-4-lite, 1024-d) ·
           Anthropic/OpenAI (LLM) · LangSmith (tracing)
```

## Hot path: one partner utterance
| # | Step | Owner | Target |
|---|---|---|---|
| 1 | VAD detects end of speech → WAV (16 kHz mono, 16-bit) → `POST /api/utterances/audio` | C | — |
| 2 | In parallel: **STT** (Scribe v2) ‖ **speaker embedding** (ECAPA 192-d) | B | ≤ 900 ms |
| 3 | `$vectorSearch` on `people.voice_centroid` → match if score ≥ `SPEAKER_THRESHOLD`; else `unknown` (session-sticky: if same person spoke < 30 s ago and score is within 0.05 of threshold, keep them) | B | ≤ 80 ms |
| 4 | Insert `utterances` doc → call `graph.pipeline.on_partner_utterance(utt)` as a background task → HTTP returns `UtteranceOut` | B → A | — |
| 5 | **Instant stage**: top phrasebook phrases for this person ranked by vector similarity to the utterance → guard → publish `SuggestionSet(stage="instant")` | A | ≤ 400 ms |
| 6 | **Retrieve**: person profile, last 3 episodes, hybrid top-3 episodes (vector + text, RRF), open threads, top phrasebook, active boundaries, last 10 session turns | A | ≤ 250 ms |
| 7 | **Generate**: LLM returns 6 candidates, each with `topics[]` | A | ≤ 1.8 s |
| 8 | **Guard**: regex safety net adds missed topics → drop candidates hitting an active boundary → keep top 4 → if fewer than 3 remain, one regenerate with "avoid: …" | A | ≤ 20 ms |
| 9 | Upsert `SuggestionSet(stage="final")` → change stream → WS hub → tablet | A | ≤ 100 ms |
| 10 | User taps → `POST /select` (event + user utterance) → `POST /api/tts` streams MP3 in cloned voice | A, B | first audio ≤ 600 ms |

**Total target:** partner stops talking → final suggestions on screen in about 3 s; instant ones in under 1.5 s.

## LangGraph pipeline (Lane A)
```
START → identify_context → instant_suggest → retrieve → generate → guard → publish → END
                                                    ↑                    │
                                                    └── regenerate (≤1) ─┘ if < 3 survive
```
- State: `PipelineState` (see `contracts.py`). `thread_id = session_id`.
- Checkpointer: `langgraph.checkpoint.mongodb.MongoDBSaver` writing to the same Atlas DB. If the server restarts mid-session, the next utterance resumes the thread with prior turns intact. That's the reliability story.
- Tracing: set `LANGSMITH_TRACING=true` and every run is traced. LangSmith is a prize partner, so mention it.

## Learning loop (Lane D): event-driven via change streams
The API never does learning inline. It **inserts an `Event`**. The worker tails `db.events.watch()` with a resume token stored in `worker_state`, so it survives restarts and picks up where it left off.

| Event | Worker reaction |
|---|---|
| `suggestion_selected`, `suggestion_edited`, `reply_typed` | upsert phrase in `memories(kind=phrase)` for (user, person): `uses += 1`, embed new text |
| `suggestion_rejected` with `reason=too_personal` | propose boundary → **replay validate** → activate (or narrow scope, or ask the user) → write `boundaries` |
| `suggestion_rejected` with `reason=not_my_style` | decrement phrase weight if the phrase came from the phrasebook; store style note as `memories(kind=fact, subkind=style)` |
| `session_ended` | LLM summarizes the transcript → `memories(kind=episode)` with `open_threads[]`; close threads that were resolved |
| `boundary_confirmed` / `boundary_dismissed` | flip status |

The `boundaries` change stream → WS hub → toast "Learned: keep health private with acquaintances".

## Reliability behaviours (say these on stage)
- **Never speaks without a tap.** TTS is only called from a user action.
- **Graceful degradation:** STT down → text box. Speaker ID unsure → "Who's this?" chips. LLM slow → instant phrasebook suggestions are already on screen.
- **Crash-safe:** LangGraph state in MongoDB, worker resume tokens in MongoDB, WS auto-reconnect with replay of the latest `SuggestionSet` for the session.
- **Idempotent events:** each has a client-generated `event_id`. The worker skips duplicates.

## Tech decisions (and why)
| Choice | Why | Fallback |
|---|---|---|
| Atlas **Flex** cluster (M0 works too) | M0 allows only 3 search/vector indexes; we designed for exactly 3 | M0 is fine; don't add a 4th index |
| One `memories` collection (`kind`: episode / phrase / fact) | Fits the 3-index budget; one hybrid search for all memory | — |
| Hybrid search via **app-side RRF** (vector + `$search`) | Works on every tier/version | `$rankFusion` if the cluster supports it |
| `voyage-4-lite` @ 1024-d | MongoDB-owned, fast, cheap; same embedding space as `voyage-4` | `MOCK_EMBED` hash vectors |
| **ElevenLabs Scribe v2** (per utterance, batch) | Accurate, simple; VAD already chunks | `scribe_v2_realtime` (P2); OpenAI transcribe |
| **SpeechBrain ECAPA** `spkrec-ecapa-voxceleb`, 192-d | Runs on CPU in ~100 ms; Amelia used SpeechBrain | `MOCK_SPEAKER` + manual chips |
| ElevenLabs **`eleven_flash_v2_5`** TTS + Instant Voice Clone | ~75 ms model latency, cloned voice | Browser `speechSynthesis` |
| LLM: `claude-haiku-5-5` for suggestions, `claude-sonnet-5-5` for summaries | Speed vs quality | `LLM_PROVIDER=openai` |
| Client-side VAD | No streaming infra; robust | Push-to-talk button |
