"""Lane D: learning worker. Run with `python -m app.learning.worker`.
Tails db.events change stream (resume token in worker_state) and dispatches by event type.
See docs/02-architecture.md "Learning loop"."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("learning.worker")


async def main() -> None:
    log.info("STUB learning worker started. TODO(Lane D): watch events, dispatch.")
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
