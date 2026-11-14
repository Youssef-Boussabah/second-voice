"""Idempotently load the Second Voice demo records into Atlas."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
load_dotenv(ROOT / ".env")

from app.config import settings
COLLECTIONS = ("users", "people", "memories", "boundaries", "events")


def read_json(name: str) -> list[dict]:
    return json.loads((ROOT / "seed" / name).read_text())


def parse_dates(record: dict) -> dict:
    for key in ("created_at", "activated_at", "last_seen"):
        if isinstance(record.get(key), str):
            record[key] = datetime.fromisoformat(record[key].replace("Z", "+00:00"))
    return record


async def main(dry_run: bool) -> None:
    client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice-seed", tz_aware=True)
    try:
        database = client[settings.mongodb_db]
        user = {"_id": "usr_maya", "name": "Maya Chen", "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)}
        people = read_json("people.json")
        boundaries = read_json("boundaries.json")
        memories = read_json("memories.json")
        events = [parse_dates(item) for item in read_json("history_events.json")]
        for memory in memories:
            memory["user_id"] = "usr_maya"
            memory["topics"] = memory.get("topics", [])
        payloads = {
            "users": [user],
            "people": [parse_dates(item) | {"user_id": "usr_maya"} for item in people],
            "memories": [parse_dates(item) for item in memories],
            "boundaries": [parse_dates(item) | {"user_id": "usr_maya"} for item in boundaries],
            "events": events,
        }
        for name, documents in payloads.items():
            collection = database[name]
            total = await collection.count_documents({})
            inserted = skipped = owned = 0
            for document in documents:
                document["seed_source"] = "lane-d"
                previous = await collection.find_one({"_id": document["_id"]}, {"seed_source": 1})
                if previous and previous.get("seed_source") != "lane-d":
                    skipped += 1
                    continue
                if previous:
                    owned += 1
                else:
                    inserted += 1
                if not dry_run:
                    if previous:
                        await collection.update_one(
                            {"_id": document["_id"], "seed_source": "lane-d"},
                            {"$set": {key: value for key, value in document.items() if key != "_id"}},
                        )
                    else:
                        try:
                            await collection.insert_one(document)
                        except DuplicateKeyError:
                            print(f"{name}: skipped raced id={document['_id']} (existing document not owned)")
            print(f"{name}: existing={total}, would_insert={inserted}, would_update_owned={owned}, would_skip={skipped}")
        print(f"{'DRY RUN: no documents written.' if dry_run else 'Seed complete.'} Database={settings.mongodb_db}; embeddings=omitted for Lane A's Voyage path.")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report existing counts and planned inserts/skips without writing")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.dry_run))
