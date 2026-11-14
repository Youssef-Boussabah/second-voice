# Second Voice

> A conversation co-pilot for people who can't speak. It knows who you're talking to, remembers your
> history with them, suggests full replies you can say with one tap, and **learns which topics stay
> private with which relationships**, enforced in code.

Built for **Agents in Context Toronto: a MongoDB Hackathon** (Nov 14 2026), track *Memory You Can Govern*.

## What it does
Maya (persona) has ALS and speaks through a tablet. When someone talks to her:

1. **Who + what was said.** The partner is picked with one tap (Dana the pharmacist, Sam her grandson,
   Mike the neighbour); what they said is typed or dictated.
2. **Instant replies (~0.5 s).** Maya's own saved phrases for that person, ranked from Atlas with no AI call.
3. **Personalized replies (~4–5 s).** An LLM writes candidates grounded in that relationship's memories:
   past conversations, open threads ("Dana to confirm the blister packs"), the phrases Maya actually uses.
4. **One tap speaks.** Only an explicit tap calls ElevenLabs TTS (browser speech if it's down).
   Nothing is ever spoken automatically.
5. **Privacy that learns.** Mark a reply *too personal* and the learning worker proposes a rule for that
   relationship (e.g. *acquaintances × health, medication*), replays it against every reply Maya has
   actually chosen, and only switches it on if it wouldn't have silenced something she said.
6. **Memory that persists.** Ending a chat writes an episode summary + open threads for that person;
   chosen replies become per-person phrases.

## How privacy is enforced (two deterministic layers)
| Layer | Where | What it does |
|---|---|---|
| **Input filter** | `guard/enforce.py: filter_context` | Before the prompt is built, every memory, fact, phrase and open thread whose topics (stored tags ∪ keyword safety net) hit a rule for this partner is **withheld from the model**. |
| **Output guard** | `guard/enforce.py: apply_guard` | Every candidate is re-tagged by a keyword net and dropped if it touches a blocked topic. Unknown speakers are treated as strangers. Hidden cards are counted on screen ("1 hidden by your privacy rules"). |

Memories are always queried per `(user, person)`; a session holds one partner, and
`memory/retrieval.py: partner_segment` keeps a previous partner's turns out of both the prompt and the
episode summary. The memory screen and the conversation header apply the same rules.

## Architecture
```
React tablet app ──REST──► FastAPI (one process) ──► MongoDB Atlas
      ▲                        │  instant stage: phrases + rules (no AI)          people · memories (vector + text
      └──────WebSocket─────────┤  final stage: retrieve → filter → LLM → guard     indexes) · sessions · utterances
                               │  /api/tts → ElevenLabs   /api/utterances/audio     · suggestion_sets · boundaries
                               │                → ElevenLabs Scribe                 · events · worker_state
                               └─ change streams (boundaries, memories) → WS toasts
Learning worker (separate process) ── tails `events` change stream ──► phrases · rules (replay-validated) · episodes
```
- **Why MongoDB:** one store for per-person memories with **Atlas Vector Search** (Voyage `voyage-4-lite`,
  1024-d) and **Atlas Search** (hybrid, fused with RRF in Python), the privacy rules, and an append-only
  `events` log whose **change stream is the learning loop** (resume token + per-event claim, so it survives
  restarts and never double-learns). A second change stream pushes "Learned: …" to the tablet.
- **LLM:** Nebius Token Factory. Suggestions: `Qwen/Qwen3-30B-A3B-Instruct-2507`, with an optional
  hedge (`LLM_HEDGE_MODEL`, default `MiniMaxAI/MiniMax-M3.1-Flash`) when it is slow; which model answered is
  counted in `/api/health`. Summaries: `zai-org/GLM-5.3-Flash`.
- **Crash safety:** conversation turns live in Atlas and are re-read on every turn, so a backend restart
  mid-chat loses nothing; the tablet's WebSocket reconnects and re-fetches the latest suggestions.

## What is real and what isn't (be precise on stage)
| Capability | Status |
|---|---|
| Atlas memory, rules, events, change streams | **Real** (verified live) |
| Nebius suggestions + summaries | **Real**; hot path hedged (see above) |
| Voyage embeddings | **Real**, but the free tier is 3 req/min: when limited, retrieval falls back to text search and memories are saved without vectors until `seed/backfill_embeddings.py` runs |
| ElevenLabs TTS (tap to speak) | **Real**, browser speech fallback |
| ElevenLabs Scribe STT | **Real in the backend** (`POST /api/utterances/audio`, verified with a WAV). The tablet's mic button uses the **browser's** Web Speech API to fill the text box; it does not call Scribe |
| Speaker identification (SpeechBrain ECAPA) | Code exists, **not enabled** (needs torch + consented enrollment). The partner is chosen manually |
| Cold-vs-warm scoreboard | Only **MOCK** runs recorded (canned LLM, random embeddings). The UI labels them MOCK; they are not AI measurements |
| LangGraph / LangSmith | **Not used.** The pipeline runs plain async stages (see `graph/pipeline.py`) |

## Run it locally (Windows PowerShell)
Prerequisites: Python 3.11+ (tested 3.12), Node 20+ (tested 24), an Atlas cluster with the 3 search
indexes, Nebius / Voyage / ElevenLabs keys.
```powershell
Copy-Item .env.example .env          # fill in keys; keep ONE line per key
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-core.txt
cd backend
..\.venv\Scripts\python.exe scripts\create_indexes.py          # once; wait until Atlas says queryable
# terminal 1: API
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# terminal 2: learning worker (one active per database; a second v2 worker waits in standby)
..\.venv\Scripts\python.exe -m app.learning.worker
# terminal 3: tablet app
cd ..\frontend
Copy-Item .env.example .env          # VITE_USE_MOCKS=false for the real backend
npm install
npm run dev -- --host 127.0.0.1      # http://127.0.0.1:5173
```
Check what the running API actually loaded: `GET http://127.0.0.1:8000/api/health` (mocks, models,
which model answered, key presence; never key values).

Seed data (3 people, history, phrases, default rules) is loaded by `seed/load.py`.

**Demo reset is destructive and off by default.** `POST /api/admin/reset-demo` (and
`seed/load.py --reset`) deletes the demo user's learned rules, phrases and episodes plus demo
sessions and events, then re-seeds. It refuses unless the server has `ENABLE_DEMO_RESET=true`, and
over HTTP it also needs an `X-Admin-Token` header equal to `ADMIN_TOKEN`. `?dry_run=true` only counts
what would be deleted and is always allowed. The UI's reset button is hidden unless
`VITE_ENABLE_RESET=true`; it sends no token, so against a real backend it only works in mock mode.

**Learning worker:** run exactly one per database; extra v2 workers wait in standby. See
[docs/operations/learning-worker.md](docs/operations/learning-worker.md) for its guarantees
(at-least-once with idempotent effects), how to inspect stuck events, and how to find and stop an
older worker (`python scripts/worker_audit.py`, read-only).

## Tests
```powershell
cd backend;  ..\.venv\Scripts\python.exe -m pytest -q          # unit tests, mocks, no network
cd frontend; npm run build; npm run smoke                       # TS strict build + mock flow smoke
# browser e2e of the stage demo against a MOCK dev server at both tablet orientations:
$env:VITE_USE_MOCKS="true"; $env:VITE_ENABLE_RESET="true"; npx vite --port 5174   # separate terminal
$env:E2E_URL="http://127.0.0.1:5174/"; npm run e2e
```

## Measured on the real stack (Nov 14 2026, local Windows laptop, 8 turns, client-side)
- First (instant) suggestions: 0.47–1.22 s (p50 ≈ 0.55 s).
- Personalized suggestions: 4.0–4.9 s (p50 ≈ 4.6 s). The original 3 s target is **not** met.
- Tap → first audio byte from ElevenLabs: ≈ 0.7 s.
- Scribe transcription of a 4 s clip: ≈ 0.8 s provider, 1.1 s end-to-end.

## Repo map
```
backend/app/   api/ (routes) · graph/ (instant + final pipeline) · guard/ (privacy enforcement)
               memory/ (retrieval) · learning/ (worker, phrasebook, rules, episodes) · realtime/ (WS hub)
               voice/ (Scribe, TTS, optional speaker ID) · contracts.py (shared Pydantic shapes)
frontend/src/  screens/ (Talk, Memory & privacy, Evaluation) · components/ · store.ts · contracts.ts
seed/          people, memories, rules, history, scripted conversations
eval/          cold-vs-warm harness (results so far: MOCK only)
docs/          original design docs (planning-time; see "What is real" above for the shipped state)
```
