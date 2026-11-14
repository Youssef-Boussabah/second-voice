"""Consume learning events and persist phrase and privacy learning."""
import asyncio
import logging
from datetime import datetime, timezone

from app.contracts import Event
from app.db import EVENTS, WORKER_STATE, db
from app.learning.boundaries import propose_and_validate
from app.learning.episodes import summarize_session
from app.learning.phrasebook import learn_phrase

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("learning.worker")


async def main() -> None:
    database = db()
    state = await database[WORKER_STATE].find_one({"_id": "learning_worker"})
    options = {"resume_after": state["resume_token"]} if state and state.get("resume_token") else {}
    async with await database[EVENTS].watch(
        [{"$match": {"operationType": "insert"}}], **options
    ) as stream:
        log.info("Learning worker started")
        async for change in stream:
            record = change["fullDocument"]
            try:
                event = Event.model_validate(record)
                if event.type in {"suggestion_selected", "suggestion_edited", "reply_typed"}:
                    await learn_phrase(event)
                elif event.type == "suggestion_rejected" and event.reason == "too_personal":
                    await propose_and_validate(event)
                elif event.type == "session_ended":
                    await summarize_session(event)
                await database[WORKER_STATE].update_one(
                    {"_id": "learning_worker"},
                    {"$set": {"resume_token": change["_id"], "updated_at": datetime.now(timezone.utc)}},
                    upsert=True,
                )
                log.info("Processed learning event %s (%s)", event.id, event.type)
            except Exception:
                log.exception("Learning event processing failed")
                await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
