# Lane A: Brain (PC1 · Claude Code)

> **URGENT 5:00 PM SUBMISSION OVERRIDE**: Start by reading `LAUNCH_NOW.md` in the repository root. Original task timings and 6:30 submission assumptions are superseded. Reach a working P0 flow by 1:30 PM; prioritize the lane-specific order in `LAUNCH_NOW.md` ahead of later steps here. Commit and push usable partial functionality often. Avoid blocking any teammate on an unfinished optional dependency.


## Kickoff prompt (paste into Claude Code)
> You are Lane A ("Brain") of Second Voice. Read `AGENTS.md`, `docs/02-architecture.md`, `docs/03-data-model.md`, `docs/04-api-contracts.md`, `docs/05-guardrails.md` §1, and this file. You own the files listed for Lane A in AGENTS.md. Post a 10-line plan, then build in the order below. After each step, run `pytest -q backend/tests/test_a_*.py` and commit with a `[A]` prefix. Use mocks until real keys are in `.env`. Don't edit other lanes' files. If you need a contract change, say `CONTRACT CHANGE REQUEST` and stop.

## Build order
1. **Wrappers** (15 min)
   - `app/llm.py`: `complete_json(system, user, schema, model=None)`. Anthropic (default) or OpenAI by `LLM_PROVIDER`. Ask for JSON matching the Pydantic schema, validate with `schema.model_validate_json`, retry once on validation error. `MOCK_LLM=1` → return a canned instance (realistic text for the demo personas).
   - `app/embeddings.py`: `embed(texts, input_type)` via `voyageai.AsyncClient().embed(texts, model=settings.embed_model, input_type=..., output_dimension=1024)`. `MOCK_EMBED=1` → deterministic hash-seeded unit vectors (1024-d).
2. **Core routes** (`api/core_routes.py`, 30 min): implement every Lane A endpoint in `04-api-contracts.md`. Each write that matters also inserts an `Event` (denormalize `person_id`, `relationship`, `text`, `topics`). `select` returns `SelectOut.text_to_speak` (edited text if provided). `/api/utterances/text` inserts the utterance, then `asyncio.create_task(pipeline.on_partner_utterance(utt))`.
3. **Pipeline** (`graph/pipeline.py`, 45 min). LangGraph `StateGraph(PipelineState)` with nodes `identify_context → instant_suggest → retrieve → generate → guard → publish`, compiled with `MongoDBSaver` (thread_id = session_id). Use `AsyncMongoDBSaver` if available in the installed version, else run the graph in a thread.
   - `instant_suggest`: top 6 `kind=phrase` memories for (user, person ∪ "global") by `$vectorSearch` on the utterance embedding → guard → publish `stage="instant"` (skip if none).
   - `generate`: prompt = persona of Maya (concise, warm, dry humour, says "bud" to Sam) + person card + retrieved memories (with ids) + last 10 turns + applicable boundaries as "avoid topics". Output `GeneratedCandidates` (6 candidates, each 3–14 words, first person, in Maya's voice, mixed intents: answer / ask back / reference an open thread / short acknowledgement). Temperature 0.3.
   - `guard`: `apply_guard` → if fewer than 3 allowed, regenerate once with explicit avoid list.
   - `publish`: upsert `SuggestionSet(stage="final")`, record `latency_ms`. Never raise. On error, publish the instant set and send WS `error`.
4. **Retrieval** (`memory/retrieval.py`, 30 min): `get_context(user_id, person_id, utterance_text) -> RetrievedContext`. Do `$vectorSearch` (index `memories_vector`, filter user/person/kind=episode, limit 5, numCandidates 100) and `$search` (index `memories_text`, compound must text + filter equals user_id/person_id, limit 5). Fuse with RRF (k=60) in Python → top 3. Also: last 3 episodes by date, open threads from episodes, top 8 phrases by `uses`, `kind=fact` for the person, active boundaries. Log latency.
5. **Guard** (`guard/enforce.py`, 20 min): implement exactly `05-guardrails.md` §1. Pure, deterministic, unit-tested: (a) acquaintance + health rule blocks a meds sentence; (b) clinician is not blocked by the acquaintance rule; (c) the safety net catches "my meds" even if the LLM tagged `small_talk`.
6. **Realtime** (`realtime/hub.py` + `ws.py`, 30 min): `ConnectionHub` keyed by session_id. On startup, start tasks tailing change streams on `suggestion_sets`, `boundaries`, `utterances`, `memories` (pipeline `[{"$match":{"fullDocument.user_id": DEMO_USER_ID}}]`, `full_document="updateLookup"`) → map to `WSMessage` → fan out. `USE_CHANGE_STREAMS=false` → direct `broadcast()` from the write sites. Reconnect: `/api/sessions/{id}/latest`.
7. **Speaker-unknown path**: if `utt.speaker.method == "unknown"`, emit WS `speaker.unknown` with the people list and still generate stranger-safe suggestions (relationship `stranger`).

## Acceptance (Checkpoint 1)
`POST /api/sessions` → `POST /api/utterances/text {"session_id":..., "text":"Hi Maya, here for your refill?", "person_id":"per_dana"}` → within 3 s a WS client receives `suggestions.ready` with stage `final`, 4 candidates, latencies logged. Test with `websocat` or `backend/scripts/ws_tail.py` (write it).

## Stretch
LangSmith trace URL on each set (`trace_url`), `$rankFusion` if supported, an open-thread-first candidate.
