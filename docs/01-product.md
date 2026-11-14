# 01: Product

## The problem
People who rely on AAC (augmentative and alternative communication: typing or tapping to speak) talk far slower than the people around them. **[VERIFY before using on a slide: ~12–18 wpm for AAC vs ~125–185 wpm spoken.]** By the time a reply is typed, the conversation has moved on, and the partner reads the lag as disengagement.

Today's AI-assisted AAC (Lingraphica Conversations, the Scott-Morgan Foundation / Lenovo system, research such as SocializeChat and SPICA) already **suggests replies** from the live transcript. Two things are still missing:

1. **It doesn't know *who* you're talking to.** Your pharmacist and your grandson get the same generic suggestions.
2. **Its privacy is all-or-nothing.** Personalized suggestions surface private details at the wrong moment. Research that ran a personalized AI AAC for months flags exactly this. Nothing learns *which topics belong with which people*.

## What Second Voice does
1. **Recognizes the speaker** by voice (opt-in enrolled voiceprints in Atlas Vector Search).
2. **Recalls your history with that person**: past conversations, open threads ("you promised to call Sam Sunday"), and the phrases you actually use with them.
3. **Suggests 4 full replies** in your style. One tap speaks it in **your cloned voice** (ElevenLabs).
4. **Learns per-relationship privacy boundaries.** Reject a suggestion as "too personal" and it proposes a rule (e.g. *acquaintances × health → block*). It checks that rule against every reply you've already chosen, and only activates it if it wouldn't have blocked something you actually said. From then on, the rule is enforced in code.

**The one-liner:** *It knows who you're talking to, what you'd say to them, and what you'd never say to them.*

## Personas (for seed data and the demo; all fictional)
- **Maya Chen**, 58, Toronto, ALS diagnosed 2 years ago, uses a tablet with large-button UI. Warm, dry humour. Calls her grandson "bud". *(Played by a teammate. Their consented cloned voice is "Maya's voice".)*
- **Dana Okafor**: pharmacist at Maya's Shoppers (relationship `clinician`). Medication talk is appropriate.
- **Sam Chen**: grandson, 16, plays hockey (relationship `family`). Warm, teasing register.
- **Mike Russo**: neighbour (relationship `acquaintance`). Small talk only. Health is private.

## Scope
### P0 (must ship, the demo depends on it)
- Text **and** voice input of partner turns (text = fallback + eval path)
- Speaker ID from enrolled voiceprints + "Who's this?" manual fallback
- Context retrieval: profile, recent episodes, open threads, phrasebook, active boundaries
- 4 suggestions on screen in under 3 s, with instant phrasebook suggestions in under 0.5 s
- Tap → spoken in cloned voice; edit-then-speak; type-your-own
- Reject with reason ("too personal" / "not how I talk" / "wrong facts")
- Boundary learning with replay validation + live toast "Learned: …"
- Deterministic guard filtering
- Episode summary + open threads written at session end
- Cold-vs-warm scoreboard (hit@4, taps/message, privacy leaks)

### P1 (if time)
- Boundary panel (view / retire rules)
- Open-thread reminders shown proactively ("Ask Sam about the game")
- Caregiver view (read-only live transcript)
- LangSmith trace link per suggestion set

### P2 (pitch only)
- Eye-gaze input, realtime streaming STT, multilingual, on-device mode

### Non-goals today
Medical advice, diagnosing anything, speaking autonomously, storing unknown people.

## 60-second pitch
> "Maya has ALS. You speak at about 150 words a minute. She types at about 15. By the time she's typed a reply, you've moved on, and you've decided she's not following. AI reply suggestions exist, but they treat everyone the same. Watch."
>
> *(Dana walks up)* "It knew that was her pharmacist and what she picked up last time. One tap, and it speaks in Maya's own voice."
>
> *(Mike walks up)* "Her neighbour gets small talk. When it suggested something too personal, Maya rejected it once. Second Voice learned a rule for *acquaintances × health*, checked it against every reply she's ever chosen so it wouldn't silence anything she actually says, and turned it on. The pharmacist still gets medication answers."
>
> "Everything lives in MongoDB Atlas: voiceprints and memories in Vector Search, conversations in hybrid search, and the learning loop runs on Change Streams. Warm versus cold: [X] taps per message instead of [Y], and zero privacy leaks."

## Judge Q&A prep
| Question | Answer |
|---|---|
| Doesn't this exist? | Reply suggestion does (Lingraphica, Scott-Morgan/Lenovo). We add **who-aware memory** and **relationship privacy that learns and is validated before it activates**. Research flags that second part as an open problem. |
| Couldn't a frontier model just do this? | A model can't know who's standing in front of you, your history with them, or your boundaries. That's memory, not intelligence. Swap the model and the product still works; remove the memory and it doesn't. |
| Recording people without consent? | Voiceprints are opt-in only. Unknown speakers are never stored. Raw audio has a 1-hour TTL. Only summaries persist. |
| What if it says something wrong? | It never speaks without a tap. The guard runs in code, not in the prompt. Every spoken line is logged. |
| Why MongoDB? | One store for 192-d voiceprint vectors, 1024-d memory vectors, full-text episodes (hybrid), rules, and an event log whose change stream *is* the learning loop. TTL for privacy. LangGraph checkpoints let a session resume after a crash. |
| Latency? | Instant phrasebook suggestions in under 0.5 s; LLM suggestions in about 2–3 s after the partner stops talking. |
| How do you know it improves? | Scripted conversations with 3 people: learn on 5, test on 3 unseen. Same model cold vs warm. Show the scoreboard. |
