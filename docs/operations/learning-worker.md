# Operating the learning worker

`python -m app.learning.worker` (from `backend/`) turns user actions in the `events` collection into
learned phrases, privacy rules and episode summaries. This page covers how it stays correct when
it crashes or when more than one runs, and how to find and stop a worker that predates this design.

## Delivery model (what is and isn't guaranteed)
- **At-least-once processing, idempotent effects.** A handler can run more than once for the same
  event: after a crash between the side effect and the `done` mark, or when a claim's lease expires
  mid-run. It is **not** exactly-once execution. What is guaranteed is that a repeat run cannot
  create a second copy of a phrase, rule or episode:

| Effect | Why a repeat is harmless |
|---|---|
| Privacy rule | id = `bnd_` + triggering event id; a second insert hits the unique `_id` and is skipped |
| Phrase use | `uses += 1` only if the event id is not already in the phrase's `learning_events` |
| New phrase | id = hash(user, person, normalized wording); concurrent writers collide on `_id` and fall back to the counted update |
| Episode | id = `mem_ep_<session>`; the threads it resolves are stored on it and re-applied on every run (idempotent), so a run that died before resolving them is completed by the retry without a second LLM call |

- **Per-event state** on each event document, field `learning`:

| `state` | Meaning | Next |
|---|---|---|
| (absent) | never claimed | claimed by the change stream or the sweep |
| `processing` | claimed; `owner` = `<host>:<pid>`, `lease_until` = claim expiry (180 s) | `done`, or retaken by anyone after `lease_until` (crashed claimant) |
| `failed` | handler raised; `last_error` kept; `lease_until` = earliest retry (15 s, 60 s, 4 min, 15 min) | retried by the sweep when due |
| `dead` | failed 5 times | left for a human (see below) |
| `done` | effects applied by the current owner | never touched again |

  The claim is a single atomic `find_one_and_update`, so two workers can never hold a live claim on
  the same event. `done` is only recorded if the finisher still owns the claim.
- **Two feeds, one code path.** The change stream gives low latency (resume token in
  `worker_state/learning_worker_v2`). A sweep every 30 s re-drives anything not `done` that was
  created after `sweep_since` (set once, the first time a v2 worker runs on the database), so events
  that arrived while no worker ran, failed events, and abandoned claims are all picked up. History
  older than `sweep_since`, seeded events and other users' events are never replayed.
- **One active worker.** `worker_state/learning_worker_lock` is a 30 s lease renewed every 10 s.
  Other v2 workers wait in standby and take over when it expires. Correctness does not depend on
  this lease (per-event claims do); it only avoids duplicate work.

## Inspecting and re-driving events (mongosh)
```js
// stuck or failing events for the demo user
db.events.find({user_id: "usr_maya", "learning.state": {$in: ["failed", "dead", "processing"]}},
               {type: 1, learning: 1}).sort({created_at: -1})
// after fixing the cause, let a dead event be retried by the next sweep
db.events.updateOne({_id: "evt_..."}, {$set: {"learning.state": "failed", "learning.attempts": 0},
                                       $unset: {"learning.lease_until": ""}})
```

## Finding every worker attached to a database
Run the read-only audit from `backend/`:
```
python scripts/worker_audit.py
```
It prints the lease holder, every client with a change stream open on `events` (appName, client
IP:port, OS) and data symptoms of an old worker. v2 workers connect with
`appName = second-voice-worker-v2/<host>:<pid>`; anything else tailing `events` is not a v2 worker.

If the Atlas user may not run `$currentOp`, use Atlas UI → the cluster → **Real Time** (or
**Metrics → Connections**) to see client addresses and app names.

Caveats: the client IP is the public address after NAT, so every laptop on the same Wi-Fi shows
the **same IP**. Use the reported OS/architecture and appName to tell machines apart, then ask on
the team who runs a worker on that kind of machine.

### Symptoms of a pre-v2 worker
- learned rules whose id is not `bnd_<triggering event id>`, or two rules from one triggering event
- two active phrases with the same wording for the same person
- learnable events created after `sweep_since` with no `learning.state` (a v2 worker marks every one)
- `worker_state/learning_worker` (the v1 state document) still being updated

## Stopping a pre-v2 worker
Pre-v2 workers ignore both leases and every per-event claim, so the only reliable fix is to stop
them where they run:
1. **On the machine that runs it** (the owner does this): press Ctrl+C in its terminal, or
   - macOS / Linux: `pgrep -fl app.learning.worker`, then `kill <pid>`
   - Windows PowerShell: `Get-CimInstance Win32_Process | ? CommandLine -match 'app.learning.worker'`,
     then `Stop-Process -Id <pid>`
   Then update that checkout to this branch, or don't run a worker there at all.
2. **Only with the database owner's permission**, if the machine can't be reached:
   - `db.adminCommand({killOp: 1, op: <opid from $currentOp>})` ends its current cursor, but the
     process will reconnect, so this is temporary;
   - rotating the database user's password or tightening the Atlas IP access list stops it for
     good but also affects everyone else using that credential or network.

   Neither is automated here, and neither should be done without permission.

Duplicates already written by an old worker are not removed automatically. Review the audit's
list and retire them by hand (`status: "retired"`) if the owner agrees.

## Verification
- Unit tests: `backend/tests/test_release_worker.py`. They cover a failed attempt released then
  recovered by the sweep, a crash after the side effect retaken by another worker (no duplicate),
  a stale owner unable to complete, two workers competing for a claim, a poison event parked as
  `dead`, done events never reprocessed, the sweep's scope, phrase/rule/episode idempotency
  (including an episode crash before thread resolution), and standby takeover.
- Live check against real Atlas change streams on a throwaway database (name must end in `_it`,
  mock LLM/embeddings):
  ```
  python scripts/worker_failover_check.py
  ```
  It runs two worker processes, hard-kills the active one, injects an abandoned claim, a failed
  event and a malformed event, and checks every outcome. Result on 2026-11-14: 8/8 checks passed
  (standby took over 26 s after the kill). It leaves the scratch database `second_voice_worker_it`
  in place for inspection; drop it by hand.
