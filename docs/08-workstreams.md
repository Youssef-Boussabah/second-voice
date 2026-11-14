# 08: Workstreams and corrected 5:00 PM submission timeline

**OVERRIDE: The old deadline assumption was wrong. Official event guide says submissions due at 5:00 PM on Nov 14.** Read `../LAUNCH_NOW.md` for exact workflow and acceptance gates.

## Lanes
- A Brain (PC1, Claude Code): core API + LLM + memory retrieval + deterministic guardrails + WS.
- B Voice (PC1, Codex): TTS first, STT second, auto speaker ID last.
- C Face (PC2, Claude Code): tablet UI in text mode first, then audio and polish.
- D Learning + Proof (PC2, Codex): seed people/memories first, privacy learning second, measured evaluation last.

## Checkpoints
- **1:30 PM**: end-to-end text-to-card-to-speech loop, backed by Atlas.
- **2:45 PM**: learned privacy rule changes the NEXT suggestions and does not censor the clinician.
- **3:40 PM**: feature freeze; measured evaluation and voice where stable.
- **4:10 PM**: 1-minute video already recorded.
- **4:40 PM**: submission uploaded and receipt checked.
- **5:00 PM**: organizer's deadline, not code freeze.

## Merge protocol
Agents work in separate worktrees, lane branches, and push frequent PRs. A single human merges to `main`; demo server always runs `main`. Keep mock fallbacks functional. No contract changes without simultaneous Pydantic/TypeScript updates.
