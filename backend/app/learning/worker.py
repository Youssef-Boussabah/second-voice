"""Consume learning events and persist phrase and privacy learning.

Run from backend/:  python -m app.learning.worker

Reliability (release-final):
- Single instance: a lease document in `worker_state` (heartbeat every 10 s, 30 s expiry). A
  second worker against the same database refuses to start instead of double-learning.
- Exactly-once per event: each event is claimed atomically (`learning.claimed_at`) before it is
  processed, so a change-stream re-delivery after a crash never increments a phrase twice or
  proposes a duplicate rule.
- Survives stream errors: reconnects with backoff and resumes from the stored resume token.
- Scoped to the demo user: the eval harness learns for its throwaway users in-process.
"""
import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

from app.config import settings
from app.contracts import Event
from app.db import EVENTS, WORKER_STATE, db
from app.learning.boundaries import propose_and_validate
from app.learning.episodes import summarize_session
from app.learning.phrasebook import learn_phrase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("learning.worker")

STATE_ID = "learning_worker"
LOCK_ID = "learning_worker_lock"
LEASE_S = 30
HEARTBEAT_S = 10
OWNER = f"{socket.gethostname()}:{os.getpid()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def acquire_lease(database, owner: str = OWNER) -> bool:
    """Take the single-worker lease if it is free, expired, or already ours."""
    now = _now()
    try:
        await database[WORKER_STATE].update_one(
            {"_id": LOCK_ID, "$or": [{"expires_at": {"$lt": now}}, {"owner": owner}]},
            {"$set": {"owner": owner, "expires_at": now + timedelta(seconds=LEASE_S), "heartbeat_at": now}},
            upsert=True,
        )
        return True
    except PyMongoError as error:  # duplicate key on upsert = someone else holds a live lease
        if getattr(error, "code", None) == 11000 or "duplicate key" in str(error).lower():
            return False
        raise


async def release_lease(database, owner: str = OWNER) -> None:
    await database[WORKER_STATE].delete_one({"_id": LOCK_ID, "owner": owner})


async def _heartbeat(database) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_S)
        if not await acquire_lease(database):
            log.error("lost the worker lease to another process; stopping")
            os._exit(3)


async def claim(database, event_id: str) -> bool:
    """Atomically mark an event as being processed. False = already handled."""
    result = await database[EVENTS].update_one(
        {"_id": event_id, "learning.claimed_at": {"$exists": False}},
        {"$set": {"learning.claimed_at": _now(), "learning.worker": OWNER}},
    )
    return result.modified_count == 1


async def handle(event: Event) -> None:
    if event.type in {"suggestion_selected", "suggestion_edited", "reply_typed"}:
        await learn_phrase(event)
    elif event.type == "suggestion_rejected" and event.reason == "too_personal":
        await propose_and_validate(event)
    elif event.type == "session_ended":
        await summarize_session(event)


async def process_change(database, change: dict) -> None:
    record = change["fullDocument"]
    event = Event.model_validate(record)
    if not await claim(database, event.id):
        log.info("event %s already processed; skipping re-delivery", event.id)
        return
    try:
        await handle(event)
        await database[EVENTS].update_one({"_id": event.id}, {"$set": {"learning.done_at": _now()}})
        log.info("Processed learning event %s (%s)", event.id, event.type)
    except Exception as error:  # noqa: BLE001  record and move on; never wedge the stream
        log.exception("Learning event %s failed", event.id)
        await database[EVENTS].update_one(
            {"_id": event.id}, {"$set": {"learning.error": f"{type(error).__name__}: {str(error)[:200]}"}})


async def run_stream(database) -> None:
    state = await database[WORKER_STATE].find_one({"_id": STATE_ID})
    options = {"resume_after": state["resume_token"]} if state and state.get("resume_token") else {}
    pipeline = [{"$match": {"operationType": "insert", "fullDocument.user_id": settings.demo_user_id}}]
    async with await database[EVENTS].watch(pipeline, **options) as stream:
        log.info("Learning worker listening (owner=%s, resumed=%s)", OWNER, bool(options))
        async for change in stream:
            await process_change(database, change)
            await database[WORKER_STATE].update_one(
                {"_id": STATE_ID},
                {"$set": {"resume_token": change["_id"], "updated_at": _now()}},
                upsert=True,
            )


async def main() -> None:
    database = db()
    if not await acquire_lease(database):
        holder = await database[WORKER_STATE].find_one({"_id": LOCK_ID})
        raise SystemExit(f"Another learning worker holds the lease ({(holder or {}).get('owner')}); "
                         f"not starting a second one. It expires {LEASE_S}s after that worker stops.")
    beat = asyncio.create_task(_heartbeat(database))
    backoff = 1.0
    try:
        while True:
            try:
                await run_stream(database)
            except PyMongoError as error:
                message = str(error)
                log.warning("change stream dropped (%s); reconnecting in %.0fs", message[:200], backoff)
                if "resume" in message.lower() or getattr(error, "code", None) in (260, 280, 286):
                    # resume point no longer in the oplog: restart from now rather than wedge
                    await database[WORKER_STATE].update_one({"_id": STATE_ID}, {"$unset": {"resume_token": ""}})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            else:
                backoff = 1.0
    finally:
        beat.cancel()
        await release_lease(database)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Learning worker stopped")
