"""Idempotently load the Second Voice demo records into Atlas (lane-d tagged only)."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from pymongo import AsyncMongoClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.learning.demo_seed import ResetDisabled, apply_seed, reset_demo  # noqa: E402


async def main(dry_run: bool, reset: bool) -> None:
    client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice-seed", tz_aware=True)
    try:
        database = client[settings.mongodb_db]
        if reset:
            try:
                result = await reset_demo(database, dry_run=dry_run)
            except ResetDisabled as error:
                raise SystemExit(f"refused: {error}. Nothing was deleted.") from error
            print(f"reset-demo deleted{' (would)' if dry_run else ''}: {result['deleted']}")
            report = result["seed"]
        else:
            report = await apply_seed(database, dry_run=dry_run)
        for name, counts in report.items():
            print(f"{name}: {counts}")
        print(f"{'DRY RUN: no documents written.' if dry_run else 'Seed complete.'} Database={settings.mongodb_db}")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report planned changes without writing")
    parser.add_argument("--reset", action="store_true",
                        help="also delete the demo user's lane-d learned docs + demo sessions/events first "
                             "(destructive: requires ENABLE_DEMO_RESET=true unless --dry-run)")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.dry_run, arguments.reset))
