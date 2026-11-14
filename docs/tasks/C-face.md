# Lane C: Face (PC2 · Claude Code)

> **URGENT 5:00 PM SUBMISSION OVERRIDE**: Start by reading `LAUNCH_NOW.md` in the repository root. Original task timings and 6:30 submission assumptions are superseded. Reach a working P0 flow by 1:30 PM; prioritize the lane-specific order in `LAUNCH_NOW.md` ahead of later steps here. Commit and push usable partial functionality often. Avoid blocking any teammate on an unfinished optional dependency.


## Kickoff prompt (paste into Claude Code)
> You are Lane C ("Face") of Second Voice. Read `AGENTS.md`, `docs/01-product.md`, `docs/04-api-contracts.md`, `docs/05-guardrails.md` §4, `docs/07-demo-script.md`, `frontend/src/contracts.ts`, and this file. You own everything in `frontend/`. Scaffold Vite + React + TS + Tailwind there (keep the existing `src/contracts.ts`). Build in the order below. Until the backend is up, run against `src/mock/` (a fake WS + fake REST you write). Commit with a `[C]` prefix. Don't edit backend files. If you need a contract change, say `CONTRACT CHANGE REQUEST`.

## Design brief
Tablet landscape (1024×768), used by someone with limited motor control. **Huge targets (≥ 64 px), high contrast, nothing important requires precision.** Calm, warm palette. The suggestion cards are the hero. Readable from 2 m away for the stage (cards at least 28 px text). One screen, no navigation during a conversation.

## Screens
1. **Session screen** (the only one used in the demo)
   - **Header**: who's talking (name · relationship label · "last talked Oct 28"), confidence dot, open-thread chips ("Dana was checking on blister packs"). Unknown → big "Who's this?" chip row of people + "Someone new".
   - **Transcript strip**: last 4 turns (partner left, Maya right).
   - **4 suggestion cards** in a 2×2 grid. Tap → `POST /select` → `POST /api/tts` → play the MP3 blob (fallback: `speechSynthesis`). While audio plays, the card pulses. The instant stage renders first; the final stage replaces it with a quick crossfade, never a jarring jump.
   - **Long-press 600 ms** (and a visible ⋯ button) → bottom sheet: **Too personal** · Not how I talk · Wrong facts → `POST /reject`.
   - **Edit**: pencil on the card → text field prefilled → Speak.
   - **Type my own**: big button → keyboard → Speak (`POST /api/replies/typed`).
   - "🔒 2 hidden by your boundaries" under the cards (tap → read-only list of which rule hid what).
   - **Toasts**: `boundary.activated` (wording in `05-guardrails.md`), `memory.updated` ("Remembered your chat with Sam").
   - `boundary.proposed` → modal with evidence and two big buttons.
   - **Mic control**: big Listen toggle. Uses `@ricky0123/vad-web` (`MicVAD`) → on `onSpeechEnd(Float32Array @16 kHz)` encode a 16-bit PCM WAV → `POST /api/utterances/audio`. Show a live "listening / heard" indicator. **Text-mode toggle** for a loud room: a text box that posts `/api/utterances/text`.
   - End conversation button → `POST /sessions/{id}/end`.
2. **People / enrollment** (setup only): list people, add person (name, relationship, label, consent checkbox), record 3 × 5 s clips with a countdown → `POST /enroll`.
3. **Scoreboard** (`GET /api/eval/scoreboard`): cold vs warm side by side, big numbers, arrows, one line of methodology.
4. **Boundaries panel** (P1): list rules, scope, origin (seed / learned), validation stats, Retire.

## Plumbing
- `src/api.ts`: typed fetch helpers for every endpoint in `04-api-contracts.md`.
- `src/ws.ts`: auto-reconnecting WS (backoff 0.5 s → 5 s). On reconnect, call `/api/sessions/{id}/latest`.
- State: React context or Zustand. One `session` store.
- `VITE_API_URL` env, default `http://localhost:8000`.

## Build order
1. Scaffold + mock server + session screen with cards (60 min) → **Checkpoint 1**: works against the real backend in text mode.
2. Tap → TTS playback, reject sheet, toasts, WS reconnect (45 min).
3. VAD audio capture + Who's-this flow (45 min) → **Checkpoint 2**.
4. Enrollment screen, scoreboard, hidden-by-boundaries, polish, stage readability pass (rest).

## Acceptance
A teammate who hasn't seen it can hold the tablet and have the Dana → Mike → Dana demo conversation with zero instructions.
