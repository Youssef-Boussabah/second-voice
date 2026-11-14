# 07: Demo script (3 minutes)

**Cast:** Teammate 1 = **Maya** (holds the tablet; their consented voice clone is Maya's voice). Teammate 2 = **Dana**, then **Mike** (a hat swap for Mike works). Teammate 2 also narrates.
**Voice casting problem:** speaker ID needs Dana and Mike to be *different voices*, and Maya's actor can't speak. So: **Dana = Teammate 2 live. Mike = a consenting friend's recorded lines played from a phone held up to the tablet** (enroll Mike from 3 other clips by the same friend), or a volunteer from the room. Speaker ID works on phone playback. Test it at 4:30 PM.
**Setup before going on stage:** `/api/admin/reset-demo` → Dana + Mike + Sam enrolled → train scenario already run so memories exist → tablet on the session screen → backup video open in a tab.

| Time | Beat | What the screen shows |
|---|---|---|
| 0:00–0:20 | **Hook** (narrator): "Maya has ALS. You speak at ~150 words a minute; she types at ~15. By the time she's replied, you've moved on." | Title slide → tablet |
| 0:20–0:55 | **Dana walks up:** "Hi Maya! Here for your refill?" | Header: **Dana Okafor · Pharmacist · last visit Oct 28**. Open thread chip: "Dana was checking on blister packs". Cards: "Yes please, same as October" · "Did the blister packs come in?" · … Maya taps the 2nd card → **spoken in Maya's voice**. |
| 0:55–1:00 | Narrator: "It knew who she was, what was pending, and spoke in Maya's own voice. One tap." | |
| 1:00–1:45 | **Mike walks up:** "Hey Maya! How've you been?" | Cards include "Honestly the new meds have been rough." Maya long-presses → **Too personal**. Toast: **"Learned: keep health & medication private with acquaintances. Checked against 23 past replies, no conflicts."** |
| 1:45–2:10 | Mike: "Anything new?" | Small-talk cards only. "🔒 1 suggestion hidden by your boundaries." |
| 2:10–2:25 | Dana again: "Any side effects with the new generic?" | Medication replies **still appear**. Narrator: "Per relationship, not a blanket ban." |
| 2:25–2:45 | **Scoreboard** | Cold vs warm: hit@4, taps/message, leaks |
| 2:45–3:00 | **Architecture in one breath:** "Voiceprints and memories in Atlas Vector Search, episodes in hybrid search, rules enforced in code, and the learning loop runs on Change Streams. LangGraph state checkpoints to MongoDB, so a crash doesn't lose the conversation." | One diagram slide |

## Failure plan
| If… | Then… |
|---|---|
| Room is too loud for VAD/STT | Switch the toggle to **text mode**: the partner types on a phone into `/api/utterances/text`, or the narrator types. Everything else is identical. |
| Speaker ID wrong | Tap the right chip ("Who's this?"). Say: "That's the fallback. It never guesses silently." |
| ElevenLabs down | Browser speech fallback; say so. |
| Anything worse | Play the backup video (recorded by 4:10 PM). |

## Rehearse
Three full run-throughs before 4:10 PM. Time each. Cut lines, not features.
