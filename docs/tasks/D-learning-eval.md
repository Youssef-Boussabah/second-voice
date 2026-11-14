# Lane D: Learning + Proof (PC2 · Codex)

> **URGENT 5:00 PM SUBMISSION OVERRIDE**: Start by reading `LAUNCH_NOW.md` in the repository root. Original task timings and 6:30 submission assumptions are superseded. Reach a working P0 flow by 1:30 PM; prioritize the lane-specific order in `LAUNCH_NOW.md` ahead of later steps here. Commit and push usable partial functionality often. Avoid blocking any teammate on an unfinished optional dependency.


## Kickoff prompt (paste into Codex)
> You are Lane D ("Learning + Proof") of Second Voice. Read `AGENTS.md`, `docs/02-architecture.md` (learning loop), `docs/03-data-model.md`, `docs/05-guardrails.md` §2–3, `docs/06-eval.md`, `backend/app/contracts.py`, and this file. You own `backend/app/learning/`, `backend/app/api/learning_routes.py`, `seed/`, `eval/`, `backend/tests/test_d_*`. Use Lane A's `app.embeddings.embed`, `app.llm.complete_json` and `app.guard.enforce` (stubs/mocks exist). Build in the order below and commit with a `[D]` prefix. Don't edit other lanes' files.

## Build order
1. **Seed data** (40 min). Everything for user `usr_maya`:
   - `seed/people.json`: Dana (clinician), Sam (family), Mike (acquaintance), plus the user doc.
   - `seed/memories.json`: about 12 episodes (backdated over Sept–Nov), about 30 phrases (Maya's voice: dry humour, "bud" with Sam), about 8 facts. Include **open threads** that the test conversations can reference (Dana: blister packs; Sam: Saturday playoff game).
   - `seed/history_events.json`: about 25 past `suggestion_selected` events across relationships, with topics. They're the replay history, so make Mike's all small talk (so "acquaintance × health" validates with 0 conflicts) and Dana's include medication.
   - `seed/boundaries.json`: seed policy from `05-guardrails.md` §2 (**no acquaintance rule**).
   - `seed/conversations/c01..c08.json` + `seed/privacy_truth.json` per `06-eval.md`. **Freeze c06–c08 by 2:00 PM.**
   - `seed/load.py` (embeds memories with `embed(..., "document")`, upserts everything; `--reset` drops the app collections except LangGraph's) + `POST /api/admin/reset-demo`.
2. **Worker skeleton** (`learning/worker.py`, 30 min): `python -m app.learning.worker`. Tail `db.events.watch([{"$match":{"operationType":"insert"}}])`, store the resume token in `worker_state` after each event, dedupe by `_id`, dispatch by `type`. Log each reaction.
3. **Phrasebook** (`learning/phrasebook.py`, 20 min): on `suggestion_selected` / `suggestion_edited` / `reply_typed`, find an existing phrase for (user, person) with cosine ≥ 0.92 (vector search) → `uses += 1`, `last_used`; else insert a new phrase memory with embedding + topics. Emit nothing (the change stream on `memories` lets the hub tell the UI).
4. **Boundaries** (`learning/boundaries.py`, 45 min): `propose_and_validate(evt)` exactly as `05-guardrails.md` §3, including narrowing and the `proposed` path. Unit tests: (a) Mike + health → active relationship rule, 0 conflicts; (b) add a past Mike health selection → narrows or proposes; (c) small-talk "too personal" → None. Routes: `GET /api/boundaries`, confirm, dismiss.
5. **Episodes** (`learning/episodes.py`, 30 min): on `session_ended`, load the session's utterances, LLM (`SUMMARY_MODEL`) → `EpisodeSummary {summary, topics, open_threads_new, threads_resolved_ids}` → insert `kind=episode` memory (embedded), mark resolved threads. `GET /api/people/{id}/context`.
6. **Eval harness** (`eval/run_eval.py`, 60 min): implements `06-eval.md` in-process (call `pipeline.on_partner_utterance` with forced person and read the resulting `SuggestionSet` from Mongo; call learning functions directly or run the worker). `--config cold|warm --repeats 2` → writes `eval_runs` → `GET /api/eval/scoreboard`. **First real numbers by 4:30 PM.**

## Acceptance
- Live: reject a meds suggestion while talking to Mike → within 2 s the `boundaries` doc is active and the toast fires.
- End a session with Sam → a new episode memory with open threads appears and is retrievable next session.
- The scoreboard endpoint returns real cold and warm numbers.
