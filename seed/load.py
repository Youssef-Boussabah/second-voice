"""Idempotently load the Second Voice demo records into Atlas."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pymongo import AsyncMongoClient, UpdateOne

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
load_dotenv(ROOT / ".env")

from app.config import settings
from app.embeddings import embed

COLLECTIONS = ("people", "memories", "boundaries", "events")


def read_json(name: str) -> list[dict]:
    return json.loads((ROOT / "seed" / name).read_text())


def parse_dates(record: dict) -> dict:
    for key in ("created_at", "activated_at", "last_seen"):
        if isinstance(record.get(key), str):
            record[key] = datetime.fromisoformat(record[key].replace("Z", "+00:00"))
    return record


async def main(reset: bool) -> None:
    client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice-seed", tz_aware=True)
    try:
        database = client[settings.mongodb_db]
        if reset:
            seed_ids = {
                "people": [item["_id"] for item in read_json("people.json")],
                "memories": [item["_id"] for item in read_json("memories.json")],
                "boundaries": [item["_id"] for item in read_json("boundaries.json")],
                "events": [item["_id"] for item in read_json("history_events.json")],
            }
            for collection, ids in seed_ids.items():
                await database[collection].delete_many({"_id": {"$in": ids}})

        user = {"_id": "usr_maya", "name": "Maya Chen", "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)}
        await database.users.update_one({"_id": user["_id"]}, {"$setOnInsert": user}, upsert=True)
        people = read_json("people.json")
        boundaries = read_json("boundaries.json")
        memories = read_json("memories.json")
        events = [parse_dates(item) for item in read_json("history_events.json")]
        for memory in memories:
            memory["user_id"] = "usr_maya"
            memory["topics"] = memory.get("topics", [])
            if not settings.mock_embed:
                memory["embedding"] = (await embed([memory["text"]], "document"))[0]
        payloads = {
            "people": [parse_dates(item) | {"user_id": "usr_maya"} for item in people],
            "memories": [parse_dates(item) for item in memories],
            "boundaries": [parse_dates(item) | {"user_id": "usr_maya"} for item in boundaries],
            "events": events,
        }
        for name, documents in payloads.items():
            if documents:
                await database[name].bulk_write([
                    UpdateOne({"_id": document["_id"]}, {"$set": document}, upsert=True)
                    for document in documents
                ])
        print(f"Loaded {len(people)} demo partners, {len(memories)} memories, {len(boundaries)} seed policies, and {len(events)} history events into {settings.mongodb_db}.")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete demo-prefixed people, memories, boundaries, and events before loading")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.reset))
