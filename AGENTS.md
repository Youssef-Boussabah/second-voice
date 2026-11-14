# AGENTS.md: rules for every coding agent on Second Voice

You are one of **four coding agents** building this project in parallel during a one-day hackathon (submission due **5:00 PM ET**, feature freeze **3:40 PM ET**; video and form submitted by **4:40 PM ET**). Two humans each run Claude Code and Codex. Your lane is assigned in `docs/tasks/<LANE>.md`. Read `LAUNCH_NOW.md` first for the corrected deadlines and P0 order, then your lane file, `docs/02-architecture.md` and `docs/04-api-contracts.md`.

## 1. Lane ownership: only edit files you own
| Lane | Agent | Owns (may create/edit) |
|---|---|---|
| **A: Brain** | PC1 Claude Code | `backend/app/contracts.py`, `config.py`, `db.py`, `llm.py`, `embeddings.py`, `api/core_routes.py`, `graph/`, `guard/`, `memory/`, `realtime/`, `backend/tests/test_a_*` |
| **B: Voice** | PC1 Codex | `backend/app/voice/`, `api/voice_routes.py`, `backend/scripts/voice_*`, `backend/tests/test_b_*` |
| **C: Face** | PC2 Claude Code | everything in `frontend/` |
| **D: Learning + Proof** | PC2 Codex | `backend/app/learning/`, `api/learning_routes.py`, `seed/`, `eval/`, `backend/tests/test_d_*` |

`backend/app/main.py`, `backend/scripts/create_indexes.py` and `docs/` are **shared and frozen**. Change them only via the contract-change protocol below.

## 2. Contracts are law
- `backend/app/contracts.py` (Pydantic) and `frontend/src/contracts.ts` (TypeScript mirror) define every shape that crosses a lane boundary: REST bodies, WebSocket messages, MongoDB documents.
- **Never** invent a field another lane must read. If you need one: write `CONTRACT CHANGE REQUEST: <field>, <why>` in your PR description and tell your human. Lane A applies it to `contracts.py`, Lane C mirrors it in `contracts.ts`, in the same hour.
- All IDs are **strings with prefixes** (`usr_`, `per_`, `ses_`, `utt_`, `sug_`, `cand_`, `bnd_`, `mem_`, `evt_`). Use `contracts.new_id("per")`. No ObjectIds cross the wire.
- All timestamps are timezone-aware UTC `datetime` (ISO-8601 strings in JSON).

## 3. Work so others aren't blocked
- Every external dependency has a **mock flag** (`MOCK_LLM`, `MOCK_STT`, `MOCK_SPEAKER`, `MOCK_TTS`, `MOCK_EMBED`). Your code must honour the flag for anything you own, and must run against the *other* lanes' mocks/stubs.
- Stubs already exist for every cross-lane function (see `docs/04-api-contracts.md` §4). Keep their **signatures**; replace their **bodies**.
- Prefer finishing a thin end-to-end slice over polishing one piece.

## 4. Git protocol
- Branch: `lane-a`, `lane-b`, `lane-c`, `lane-d`. Commit small and often with messages like `[A] guard: deterministic topic filter`.
- `git pull --rebase origin main` at least every hour and before every checkpoint.
- Humans merge lanes into `main` at checkpoints (see `docs/08-workstreams.md`). Never force-push `main`.
- Never commit `.env`, audio of real people, or API keys.

## 5. Code standards
- Python 3.11, async everywhere in the request path (`pymongo.AsyncMongoClient`, `httpx.AsyncClient`). Blocking work (SpeechBrain, sync SDKs) goes in `await asyncio.to_thread(...)`.
- Type hints and Pydantic models at every boundary. No bare dicts across modules.
- Log with `logging.getLogger(__name__)`. Every request-path step logs its latency in ms.
- Each lane writes at least one smoke test (`pytest -q backend/tests/test_<lane>_*.py`) that runs with mocks on.
- Frontend: React + TS strict, Tailwind, no component library needed. Tablet-first (1024×768), buttons ≥ 64px tall.

## 6. Non-negotiable product rules (judges will ask)
1. **Nothing is ever spoken without the user's tap.**
2. Boundaries are enforced **deterministically in code** (`guard/`), never only by prompt.
3. Raw audio is never kept: the `audio_clips` collection has a 1-hour TTL. Unknown speakers' voiceprints are **not stored**.
4. Partners are enrolled **opt-in only** (consent flag required on `Person`).

## 7. When unsure
Re-read the docs. If they don't answer it, make the smallest reasonable choice, leave a `# DECISION:` comment explaining it, and mention it in your PR. Don't stall.
