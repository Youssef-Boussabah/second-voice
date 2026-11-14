"""Consume learning events and persist phrase, privacy and episode learning.

Run from backend/:  python -m app.learning.worker

Delivery model: AT-LEAST-ONCE processing with IDEMPOTENT side effects. This module does not
claim exactly-once execution: a handler may run more than once for the same event (crash after
the side effect but before `done` is recorded, or a lease that expires mid-run). Every handler is
written so a repeat run cannot create a second phrase, rule or episode:
  - rules:    id derived from the triggering event (`bnd_<event>`), insert-or-skip
  - phrases:  per-event application marker (`learning_events`) + deterministic id per
              (user, person, normalized text) for new phrases
  - episodes: id derived from the session (`mem_ep_<session>`); thread resolution is stored on the
              episode and re-applied on every run (idempotent)

Per-event durable state lives on the event document (`learning.*`):
  state       processing | done | failed | dead     (absent = never claimed)
  attempts    claims so far
  lease_until claim expiry; for `failed` it is the earliest retry time (backoff)
  owner       "<host>:<pid>" of the current/last claimant
  last_error  last failure, truncated
A claim is one atomic find_one_and_update that only matches an unclaimed, failed-and-due, or
lease-expired event, so a crashed worker's events are retaken after EVENT_LEASE_S, and two
workers can never hold the same live claim. Completion only counts if the finisher still owns
the claim. After MAX_ATTEMPTS the event is parked as `dead` for a human to inspect.

Two paths feed the same `process_event`:
  - the change stream on `events` (low latency; resume token in worker_state/STATE_ID)
  - a periodic sweep for anything not done (failed, lease-expired, or inserted while no worker
    ran), bounded below by `sweep_since` so pre-existing history is never replayed.

A worker-level lease (`LOCK_ID`) keeps one ACTIVE worker per database; others wait in standby and
take over when the lease expires. Correctness does not depend on it (claims do); it only avoids
wasted duplicate work. Workers from before this design ignore both leases: see
docs/operations/learning-worker.md for how to find and stop one.
"""
import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.config import settings
from app.contracts import Event
from app.db import EVENTS, WORKER_STATE, db
from app.learning.boundaries import propose_and_validate
from app.learning.episodes import summarize_session
from app.learning.phrasebook import learn_phrase

log = logging.getLogger("learning.worker")

STATE_ID = "learning_worker_v2"      # v1 (pre-release worker) used "learning_worker"; kept separate
LOCK_ID = "learning_worker_lock"
WORKER_LEASE_S = 30
HEARTBEAT_S = 10
EVENT_LEASE_S = 180                  # > the slowest handler (episode summary LLM timeout is 90 s)
MAX_ATTEMPTS = 5
BACKOFF_S = (15, 60, 240, 900)       # wait before retry n+1
SWEEP_EVERY_S = 30
SWEEP_BATCH = 50
OWNER = f"{socket.gethostname()}:{os.getpid()}"

LEARNABLE = ("suggestion_selected", "suggestion_edited", "reply_typed", "suggestion_rejected", "session_ended")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_learnable(record: dict) -> bool:
    if record.get("type") not in LEARNABLE:
        return False
    if record.get("type") == "suggestion_rejected" and record.get("reason") != "too_personal":
        return False
    return not record.get("seed_source")


# ───────────────────────── per-event claims ─────────────────────────
async def claim(database, event_id: str, owner: str = OWNER, now: datetime | None = None) -> dict | None:
    """Atomically take the event if nobody holds a live claim on it. Returns the claimed doc."""
    now = now or _now()
    return await database[EVENTS].find_one_and_update(
        {"_id": event_id,
         "learning.state": {"$nin": ["done", "dead"]},
         "$or": [{"learning.lease_until": {"$exists": False}}, {"learning.lease_until": {"$lte": now}}]},
        {"$set": {"learning.state": "processing", "learning.owner": owner,
                  "learning.lease_until": now + timedelta(seconds=EVENT_LEASE_S),
                  "learning.claimed_at": now},
         "$inc": {"learning.attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )


async def complete(database, event_id: str, owner: str = OWNER) -> bool:
    """Mark done only if we still own the claim (a lease-expired run is not trusted)."""
    result = await database[EVENTS].update_one(
        {"_id": event_id, "learning.state": "processing", "learning.owner": owner},
        {"$set": {"learning.state": "done", "learning.done_at": _now()},
         "$unset": {"learning.lease_until": "", "learning.last_error": ""}},
    )
    return result.modified_count == 1


async def fail(database, event_id: str, attempts: int, error: BaseException, owner: str = OWNER) -> str:
    """Release the claim as `failed` with a backoff, or park it as `dead` after MAX_ATTEMPTS."""
    message = f"{type(error).__name__}: {str(error)[:300]}"
    if attempts >= MAX_ATTEMPTS:
        state, update = "dead", {"learning.state": "dead", "learning.last_error": message, "learning.dead_at": _now()}
    else:
        delay = BACKOFF_S[min(attempts - 1, len(BACKOFF_S) - 1)]
        state, update = "failed", {"learning.state": "failed", "learning.last_error": message,
                                   "learning.lease_until": _now() + timedelta(seconds=delay)}
    await database[EVENTS].update_one(
        {"_id": event_id, "learning.state": "processing", "learning.owner": owner}, {"$set": update})
    return state


async def handle(event: Event) -> None:
    if event.type in {"suggestion_selected", "suggestion_edited", "reply_typed"}:
        await learn_phrase(event)
    elif event.type == "suggestion_rejected" and event.reason == "too_personal":
        await propose_and_validate(event)
    elif event.type == "session_ended":
        await summarize_session(event)


async def process_event(database, event_id: str, owner: str = OWNER) -> str:
    """Claim → handle → complete, or record the failure. Returns the outcome."""
    doc = await claim(database, event_id, owner)
    if doc is None:
        return "skipped"              # done, dead, or someone else holds a live claim
    if not is_learnable(doc):
        await complete(database, event_id, owner)
        return "ignored"
    attempts = int((doc.get("learning") or {}).get("attempts", 1))
    try:
        await handle(Event.model_validate(doc))
    except Exception as error:  # noqa: BLE001  never wedge the stream; the sweep retries later
        state = await fail(database, event_id, attempts, error, owner)
        log.exception("learning event %s failed (attempt %d) -> %s", event_id, attempts, state)
        return state
    if await complete(database, event_id, owner):
        log.info("processed learning event %s (%s, attempt %d)", event_id, doc.get("type"), attempts)
        return "done"
    log.warning("event %s finished after its claim was taken over; effects are idempotent", event_id)
    return "superseded"


async def sweep(database, owner: str = OWNER, since: datetime | None = None) -> dict[str, int]:
    """Re-drive learnable events that are not done: never claimed, failed and due, or whose claim
    expired (crashed worker). Bounded by `since` so older history is never replayed."""
    now = _now()
    flt = {"user_id": settings.demo_user_id, "type": {"$in": list(LEARNABLE)},
           "seed_source": {"$exists": False},
           "learning.state": {"$nin": ["done", "dead"]},
           "$or": [{"learning.lease_until": {"$exists": False}}, {"learning.lease_until": {"$lte": now}}]}
    if since is not None:
        flt["created_at"] = {"$gte": since}
    ids = [d["_id"] for d in await database[EVENTS].find(flt, {"_id": 1}).sort("created_at", 1)
           .limit(SWEEP_BATCH).to_list(SWEEP_BATCH)]
    outcomes: dict[str, int] = {}
    for event_id in ids:
        outcome = await process_event(database, event_id, owner)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    if ids:
        log.info("sweep: %s", outcomes)
    return outcomes


async def sweep_since(database) -> datetime:
    """Lower bound for sweeps, fixed the first time this worker version runs on a database."""
    state = await database[WORKER_STATE].find_one({"_id": STATE_ID})
    if state and state.get("sweep_since"):
        return state["sweep_since"]
    try:
        await database[WORKER_STATE].update_one(
            {"_id": STATE_ID, "sweep_since": {"$exists": False}}, {"$set": {"sweep_since": _now()}}, upsert=True)
    except PyMongoError as error:  # another worker set it first (duplicate key on upsert)
        if getattr(error, "code", None) != 11000 and "duplicate key" not in str(error).lower():
            raise
    return (await database[WORKER_STATE].find_one({"_id": STATE_ID}))["sweep_since"]


# ───────────────────────── worker-level lease (one active worker) ─────────────────────────
async def acquire_lease(database, owner: str = OWNER) -> bool:
    """Take or renew the active-worker lease if it is free, expired, or already ours."""
    now = _now()
    try:
        await database[WORKER_STATE].update_one(
            {"_id": LOCK_ID, "$or": [{"expires_at": {"$lt": now}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": now + timedelta(seconds=WORKER_LEASE_S), "heartbeat_at": now}},
            upsert=True,
        )
        return True
    except PyMongoError as error:  # duplicate key on upsert = someone else holds a live lease
        if getattr(error, "code", None) == 11000 or "duplicate key" in str(error).lower():
            return False
        raise


async def release_lease(database, owner: str = OWNER) -> None:
    await database[WORKER_STATE].delete_one({"_id": LOCK_ID, "owner": owner})


# ───────────────────────── run loop ─────────────────────────
async def run_stream(database) -> None:
    state = await database[WORKER_STATE].find_one({"_id": STATE_ID})
    options = {"resume_after": state["resume_token"]} if state and state.get("resume_token") else {}
    pipeline = [{"$match": {"operationType": "insert", "fullDocument.user_id": settings.demo_user_id}}]
    async with await database[EVENTS].watch(pipeline, **options) as stream:
        log.info("listening on events (owner=%s, resumed=%s)", OWNER, bool(options))
        async for change in stream:
            if is_learnable(change["fullDocument"]):
                await process_event(database, change["documentKey"]["_id"])
            await database[WORKER_STATE].update_one(
                {"_id": STATE_ID}, {"$set": {"resume_token": change["_id"], "updated_at": _now()}}, upsert=True)


async def _sweeper(database, since: datetime) -> None:
    while True:
        try:
            await sweep(database, since=since)
        except PyMongoError as error:
            log.warning("sweep failed (%s); retrying", str(error)[:200])
        await asyncio.sleep(SWEEP_EVERY_S)


async def _heartbeat(database, lost: asyncio.Event) -> None:
    while not lost.is_set():
        await asyncio.sleep(HEARTBEAT_S)
        try:
            if not await acquire_lease(database):
                log.error("lost the active-worker lease; returning to standby")
                lost.set()
        except PyMongoError as error:
            log.warning("heartbeat failed (%s)", str(error)[:200])


async def run_active(database) -> None:
    """Run stream + sweeper until the lease is lost (then return to standby)."""
    since = await sweep_since(database)
    lost = asyncio.Event()
    tasks = [asyncio.create_task(_heartbeat(database, lost), name="heartbeat"),
             asyncio.create_task(_sweeper(database, since), name="sweeper")]
    backoff = 1.0
    try:
        while not lost.is_set():
            stream = asyncio.create_task(run_stream(database), name="stream")
            waiter = asyncio.create_task(lost.wait())
            done, _ = await asyncio.wait({stream, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if stream not in done:
                stream.cancel()
                break
            error = stream.exception()
            if error is None:
                backoff = 1.0
                continue
            message = str(error)
            log.warning("change stream dropped (%s); reconnecting in %.0fs", message[:200], backoff)
            if "resume" in message.lower() or getattr(error, "code", None) in (260, 280, 286):
                # resume point fell out of the oplog: restart from now; the sweep covers the gap
                await database[WORKER_STATE].update_one({"_id": STATE_ID}, {"$unset": {"resume_token": ""}})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    finally:
        for task in tasks:
            task.cancel()


async def main() -> None:
    database = db()
    log.info("learning worker %s starting", OWNER)
    try:
        while True:
            if await acquire_lease(database):
                log.info("active (lease %ss)", WORKER_LEASE_S)
                await run_active(database)
            else:
                holder = await database[WORKER_STATE].find_one({"_id": LOCK_ID})
                log.info("standby: lease held by %s", (holder or {}).get("owner"))
                await asyncio.sleep(HEARTBEAT_S)
    finally:
        await release_lease(database)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("MONGO_APPNAME", f"second-voice-worker-v2/{OWNER}")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("learning worker stopped")
