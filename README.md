**START HERE: [`LAUNCH_NOW.md`](LAUNCH_NOW.md) — official 5:00 PM deadline and revised launch instructions.**

# Second Voice

> A conversation co-pilot for people who can't speak. It recognizes who you're talking to, remembers your history with them, suggests full replies, and speaks them in **your own voice**. Its privacy guardrails **learn per relationship**.

Built for **Agents in Context Toronto: a MongoDB Hackathon**, Nov 14 2026.

## The 10-second pitch
Amelia helped deaf people hear the room. Second Voice helps people who can't speak talk back. It does that at conversation speed, in their own voice, and it never tells the neighbour what it would only tell the pharmacist.

## Repo map
```
second-voice/
├── AGENTS.md              ← rules every coding agent follows (Codex reads this)
├── CLAUDE.md              ← Claude Code entry point (imports AGENTS.md)
├── .env.example           ← every key/model/flag
├── docs/
│   ├── 01-product.md      ← problem, users, scope (P0/P1/P2), pitch, judge Q&A
│   ├── 02-architecture.md ← system diagram, per-utterance flow, latency budget, reliability
│   ├── 03-data-model.md   ← MongoDB collections, example docs, the 3 search indexes
│   ├── 04-api-contracts.md← REST + WebSocket contracts (source of truth)
│   ├── 05-guardrails.md   ← topic taxonomy, enforcement, boundary learning + replay validation
│   ├── 06-eval.md         ← dataset format, metrics, cold-vs-warm protocol
│   ├── 07-demo-script.md  ← 3-minute stage demo + backup plan
│   ├── 08-workstreams.md  ← 4 lanes, timeline, checkpoints, git protocol
│   └── tasks/             ← paste-ready kickoff prompts for each agent (A, B, C, D)
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── contracts.py   ← Pydantic models: THE shared contract (Lane A owns)
│   │   ├── config.py      ← settings from .env
│   │   ├── db.py          ← Mongo client + collection names
│   │   ├── main.py        ← FastAPI app; routers pre-wired (don't edit)
│   │   ├── api/           ← one router file per lane (core / voice / learning)
│   │   ├── graph/         ← Lane A: LangGraph suggestion pipeline
│   │   ├── guard/         ← Lane A: deterministic boundary enforcement
│   │   ├── memory/        ← Lane A: retrieval (hybrid search)
│   │   ├── realtime/      ← Lane A: WebSocket hub + change streams
│   │   ├── voice/         ← Lane B: speaker ID, STT, TTS
│   │   └── learning/      ← Lane D: worker, phrasebook, boundaries, episodes
│   └── scripts/create_indexes.py
├── frontend/src/contracts.ts  ← TS mirror of contracts.py (Lane C keeps in sync)
├── seed/                  ← Lane D: people, memories, scripted conversations
└── eval/                  ← Lane D: cold-vs-warm harness + scoreboard
```

## Quickstart
```bash
cp .env.example .env            # fill in keys
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-core.txt   # lightweight first; install SpeechBrain separately only if needed
python scripts/create_indexes.py
uvicorn app.main:app --reload --port 8000
python -m app.learning.worker    # separate terminal (Lane D)

cd frontend && npm install && npm run dev   # http://localhost:5173
```
Mock flags in `.env` (`MOCK_LLM`, `MOCK_STT`, `MOCK_SPEAKER`, `MOCK_TTS`) let every lane run without the others being finished.

## Stack
Python 3.11 · FastAPI · PyMongo Async · LangGraph + `langgraph-checkpoint-mongodb` · LangSmith · MongoDB Atlas (Vector Search, Search, Change Streams, TTL) · Voyage AI `voyage-4-lite` embeddings · ElevenLabs Scribe v2 (STT) + Flash TTS with a cloned voice · SpeechBrain ECAPA voiceprints · Claude / OpenAI (configurable) · React + Vite + TypeScript + Tailwind · `@ricky0123/vad-web`
