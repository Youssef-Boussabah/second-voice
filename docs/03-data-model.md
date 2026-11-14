# 03: Data model (MongoDB Atlas, database `second_voice`)

All `_id`s are prefixed strings (`contracts.new_id`). All times are UTC. Pydantic definitions are in `backend/app/contracts.py`, and that file wins if anything here disagrees.

## Search index budget: exactly 3 (free/M0 limit)
| # | Name | Collection | Type | Definition |
|---|---|---|---|---|
| 1 | `people_voice` | `people` | vectorSearch | `voice_centroid` 192-d cosine; filter `user_id` |
| 2 | `memories_vector` | `memories` | vectorSearch | `embedding` 1024-d cosine; filters `user_id`, `person_id`, `kind`, `status` |
| 3 | `memories_text` | `memories` | search | `text` (lucene.english); `user_id`, `person_id`, `kind` as `token` |

Created by `backend/scripts/create_indexes.py` (idempotent). **Do not add a 4th** without upgrading to Flex or dedicated.

## Collections

### `users`
```json
{"_id":"usr_maya","name":"Maya Chen","voice_id":"<elevenlabs voice id>","created_at":"..."}
```
Single user for the hackathon: `DEMO_USER_ID=usr_maya`.

### `people` (conversation partners)
```json
{
  "_id":"per_dana","user_id":"usr_maya","name":"Dana Okafor",
  "relationship":"clinician","label":"Pharmacist at Shoppers",
  "notes":"Fills Maya's prescriptions monthly",
  "consent":{"voice":true,"at":"2026-11-14T17:10:00Z"},
  "voiceprints":[[...192],[...192],[...192]],
  "voice_centroid":[...192],            // L2-normalized mean of voiceprints  ← index #1
  "last_seen":"2026-10-28T15:02:00Z","created_at":"..."
}
```
`relationship` ∈ `family | close_friend | caregiver | clinician | service | acquaintance | stranger`

### `sessions`
```json
{"_id":"ses_x","user_id":"usr_maya","person_ids":["per_dana"],"started_at":"...","ended_at":null,"status":"active"}
```

### `utterances`
```json
{
  "_id":"utt_x","session_id":"ses_x","user_id":"usr_maya",
  "speaker":{"kind":"partner","person_id":"per_dana","score":0.83,"method":"voice"},
  "text":"Hi Maya, here for your refill?","source":"stt",
  "suggestion_set_id":null,"created_at":"..."
}
```
`speaker.kind` ∈ `partner | user`; `method` ∈ `voice | manual | forced | unknown`; `source` ∈ `stt | text | suggestion | edited | typed`.
Index: `{session_id:1, created_at:1}`.

### `audio_clips` (TTL)
`{"_id":"aud_x","session_id":"...","utterance_id":"...","wav":<Binary>,"created_at":"..."}`. TTL index on `created_at`, `expireAfterSeconds=3600`. Optional: only Lane B writes here, and only for debugging.

### `suggestion_sets` (watched by WS hub)
```json
{
  "_id":"sug_x","session_id":"ses_x","user_id":"usr_maya","utterance_id":"utt_x",
  "person_id":"per_dana","stage":"final",          // instant | final
  "candidates":[
    {"id":"cand_1","text":"Yes please, same as October.","topics":["medication","logistics"],
     "source":"llm","memory_ids":["mem_ep_oct28"],"blocked":false,"blocked_by":null}
  ],
  "blocked":[{"id":"cand_5","text":"...","topics":["health"],"blocked":true,"blocked_by":"bnd_x"}],
  "status":"shown","chosen_candidate_id":null,
  "latency_ms":{"retrieve":180,"generate":1600,"total":2100},
  "trace_url":null,"created_at":"...","updated_at":"..."
}
```
Index: `{session_id:1, created_at:-1}`. `blocked` is kept for the demo ("2 suggestions hidden by your boundaries") and for eval.

### `memories` (one collection, three kinds) ← indexes #2 and #3
```json
// kind = episode  (written by Lane D at session end)
{"_id":"mem_ep_1","user_id":"usr_maya","person_id":"per_dana","kind":"episode","status":"active",
 "text":"Oct 28: Picked up Riluzole refill. Dana said the new generic looks different. Maya joked about the line.",
 "topics":["medication","small_talk"],
 "open_threads":[{"id":"thr_1","text":"Dana to check if blister packs are available","owner":"partner","status":"open"}],
 "session_id":"ses_old","embedding":[...1024],"created_at":"2026-10-28T15:10:00Z"}

// kind = phrase   (the user's own words with this person; person_id "global" for anyone)
{"_id":"mem_ph_1","user_id":"usr_maya","person_id":"per_sam","kind":"phrase","status":"active",
 "text":"Proud of you, bud.","topics":["emotions_positive"],"uses":7,"last_used":"...",
 "origin":"selected","embedding":[...1024],"created_at":"..."}

// kind = fact     (stable facts about the person or the user's style)
{"_id":"mem_f_1","user_id":"usr_maya","person_id":"per_sam","kind":"fact","subkind":"person",
 "status":"active","text":"Sam plays hockey (defence) for the Leaside Flames.","embedding":[...1024],"created_at":"..."}
```
`kind` ∈ `episode | phrase | fact`; `status` ∈ `active | retired`.

### `boundaries`
```json
{
  "_id":"bnd_x","user_id":"usr_maya",
  "scope":{"type":"relationship","value":"acquaintance"},   // type: global | relationship | person
  "topics":["health","medication"],"action":"block",
  "status":"active",                                          // proposed | active | dismissed | retired
  "origin":"learned",                                         // seed | learned | manual
  "evidence":{"trigger_event_id":"evt_x","rejected_text":"Honestly the new meds are rough.",
              "person_id":"per_mike"},
  "validation":{"replayed":23,"conflicts":0,"conflict_event_ids":[],"passed":true,
                "narrowed_from":null},
  "created_at":"...","activated_at":"..."
}
```
Index: `{user_id:1, status:1}`.

### `events` (append-only; the worker watches this)
```json
{
  "_id":"evt_x","user_id":"usr_maya","session_id":"ses_x","type":"suggestion_rejected",
  "person_id":"per_mike","relationship":"acquaintance",         // denormalized for replay
  "suggestion_set_id":"sug_x","candidate_id":"cand_3",
  "text":"Honestly the new meds are rough.","topics":["health","medication"],
  "reason":"too_personal","created_at":"..."
}
```
`type` ∈ `suggestion_selected | suggestion_edited | reply_typed | suggestion_rejected | session_started | session_ended | speaker_assigned | boundary_confirmed | boundary_dismissed`.
Indexes: `{user_id:1, type:1, relationship:1}`, `{user_id:1, type:1, person_id:1}`.

### `worker_state`
`{"_id":"learning_worker","resume_token":{...},"updated_at":"..."}`

### `eval_runs`
`{"_id":"run_x","config":"cold|warm","metrics":{...},"per_turn":[...],"created_at":"..."}`

### LangGraph
`MongoDBSaver` creates `checkpoints` and `checkpoint_writes` itself. Don't touch them.

## Topic taxonomy (fixed enum, used by guard and eval)
`health, medication, finances, family_conflict, romance, location_schedule, legal, distress, death_dying, work, small_talk, logistics, emotions_positive, humour, hobbies, family_news`

Sensitive by default (what the guard and replay care about): `health, medication, finances, family_conflict, romance, location_schedule, legal, distress, death_dying`.
