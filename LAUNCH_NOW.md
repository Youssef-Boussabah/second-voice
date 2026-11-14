# SECOND VOICE — LAUNCH NOW (14 NOV 2026, Toronto)

## Hard rules
- **Submission due 5:00 PM ET.** Original `08-workstreams.md` and `AGENTS.md` were wrong (they said 6:30 PM). This starter fixes that assumption.
- Must use the **MongoDB Atlas Hackathon Sandbox from the organizer's invitation email** to qualify as a finalist.
- Submit via Cerebral Valley: public GitHub repo, **1-minute** demo video with code + working product, concise description, and all team members.
- Start work today, originality required. Don't publish keys or unconsented audio. Audio enrollment/voice cloning requires explicit consent.
- Track focus: **Statement Two — Memory You Can Govern**. Demonstrate memory across sessions, relationship-scoped retrieval, correction/forgetting, behavior changed by memory, and user-controlled privacy rules.

## First 15 minutes: humans
1. Extract this project, create EMPTY public GitHub repo `second-voice`, `git init -b main`, `git add .`, `git commit -m 'Initial Second Voice scaffold'`, `git remote add origin https://github.com/USERNAME/second-voice.git`, `git push -u origin main`.
2. Check the MongoDB invitation email; **create the project and cluster using that exact invitation**. Create DB user, allow the venue's egress IP (avoid 0.0.0.0/0 unless necessary and temporary), copy `MONGODB_URI` into a local `.env` (never commit).
3. Keys: one supported LLM (Anthropic or OpenAI), Voyage AI, ElevenLabs; voice clone ONLY the consenting teammate. Clone optional early, and verify generated playback. API model names in `.env.example` are candidate values, verify with your actual account before switching off mocks.
4. Separate git worktrees (PC1 lanes A+B, PC2 lanes C+D), then paste prompt from `docs/tasks/<lane>.md` into each agent. Each agent must follow the TIME OVERRIDE below.
5. Create indexes: from `backend/`, after credentials are set, `python scripts/create_indexes.py` and verify that Atlas reports 3 indexes **queryable**. They can take time. Start this while agents code.

## Time override (replaces previous timing)
| ET | Target | Required proof |
|---|---|---|
| 12:00–12:20 | Setup in parallel with coding | Repo online; Atlas sandbox connected; agents running |
| 12:20–1:30 | **Text thin slice** | Text input (forced person) → Atlas context → 4 suggestions → user taps → speech or browser TTS; event saved |
| 1:30–2:45 | Core differentiator | Different context for pharmacist vs neighbour; reject too personal → scoped rule changes next suggestion; documented memory record |
| 2:45–3:40 | Voice + tests | ElevenLabs TTS, optionally STT/speaker ID; reconnect; cold vs warm eval first REAL metric |
| 3:40–4:10 | FEATURE FREEZE & record | Test end-to-end thrice, 1-minute recording with audio, public README + URL |
| 4:10–4:40 | SUBMIT | Upload video, repo, concise writeup, all team members; confirm submission receipt |
| 4:40–5:00 | Buffer only | Fix accessibility or submission errors, no risky features |

## Agent-specific execution order (overrides overly ambitious original task ordering)
- **A Brain:** implement sessions, text utterance, deterministic 4 suggestions with mock LLM, select→event, WebSocket. THEN real LLM, Atlas memory retrieval, deterministic privacy guard. LangGraph checkpointing only if core path works. **A owns API contracts.**
- **B Voice:** implement `POST /api/tts` with ElevenLabs + browser fallback, test voice clone. THEN STT. LAST: SpeechBrain auto-speaker-ID (large Torch dependency, noisy-room risk). Manual person selection stays supported.
- **C Face:** implement single polished tablet page; **text-mode first**, person picker, 4 cards, tap-to-speak, reject, status, demo toggle. Wire real REST/WS. THEN recording/VAD and evaluation panel. Do not block user on nonexistent routes; mock until API ready.
- **D Learning:** seed a real demo into Atlas FIRST (3 people, episode history, phrases, initial policies), verify A can query it. Implement `too_personal` rejection → scoped boundary update → filtered next round. THEN events/worker and reproducible *real* cold-vs-warm metric. Do not hardcode performance numbers.

## Cross-lane acceptance contract
1. Text: `POST /api/sessions` returns ID; `POST /api/utterances/text` with `person_id=per_dana` starts suggestions; WebSocket `/ws?session_id=<id>` emits `suggestions.ready` with 4 cards.
2. Tap: `POST /api/suggestions/<set_id>/select` records what the user actually chose; only then `POST /api/tts` may be called. **Never auto-speak generated text.**
3. Memory: two people asking similar questions must give different grounded suggestions; seeded memory document can be viewed in Atlas; stale/forbidden memory excluded.
4. Privacy: a `too_personal` rejection yields a scoped rule (either user-confirmed or transparently undoable); repeat utterance for acquaintance hides health info; clinician still gets clinician-appropriate info. Deterministic code guard, not prompt-only.
5. Fallback: manually select speaker and type transcript if STT or speaker ID fails. Browser speech may substitute for provider outages; **disclose** in demo when applicable.

## Git workflow (never edit the same working tree from 2 agents)
PC1: at repo root `git worktree add ../second-voice-a -b lane-a main`, `git worktree add ../second-voice-b -b lane-b main`.
PC2: clone repo, then `git worktree add ../second-voice-c -b lane-c main`, `git worktree add ../second-voice-d -b lane-d main`.
Agents commit to lane branches, push, human reviews and merges small PRs continuously. One integrator owns `main`. After merge: each lane pulls/rebases from main. Integrator deploys app from an updated `main` clone, not any lane worktree.

## Windows PowerShell quickstart (integration machine)
```powershell
Copy-Item .env.example .env
# Edit .env in editor. Set MONGODB_URI, API keys and MOCK_* intentionally.
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-core.txt
cd backend
..\.venv\Scripts\python.exe scripts/create_indexes.py
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# Separate terminal, after C scaffolds:
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```
If Python 3.11 isn't installed, use a supported local Python 3.11+ and substitute its launcher. Full speechbrain/torch is intentionally excluded from core dependencies.

**Critical:** `/api/health` working does NOT mean the product works: the source starter contains mostly TODOs. Test the real `/api/sessions` → `/api/utterances/text` → WS → `/api/suggestions/.../select` → `/api/tts` flow against Atlas after agents implement it.

## Submission checklist
- [ ] 5 PM deadline confirmed with staff/platform (use earliest time if platform differs)
- [ ] Atlas project created using invitation; demo writes and reads REAL Atlas documents
- [ ] GitHub PUBLIC and README updated, no secrets or real voice recordings in repo
- [ ] 1-minute video includes audio, visible code and product functionality
- [ ] Video/link tested in incognito
- [ ] Project description says exactly what is implemented (not planned)
- [ ] All human team members included and submission receipt verified
