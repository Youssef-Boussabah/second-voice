"""Backfill real Voyage vectors onto lane-d owned memories (seed + learned) that lack one."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings
from app.db import MEMORIES, db
from app.embeddings import embed


# lane-d seed docs plus lane-d learned docs (episodes/phrases saved while Voyage was down)
OWNED = {"$or": [{"seed_source": "lane-d"}, {"written_by": "lane-d"}]}


def missing_embedding_filter() -> dict:
    return {"$or": [{"embedding": {"$exists": False}}, {"embedding": None}]}


async def main(dry_run: bool) -> None:
    if not settings.voyage_api_key:
        raise SystemExit("VOYAGE_API_KEY is required; no Atlas writes were made.")
    if settings.mock_embed:
        raise SystemExit("MOCK_EMBED=true is unsafe for Atlas backfill; set MOCK_EMBED=false. No writes were made.")
    if settings.embed_dim != 1024:
        raise SystemExit(f"Expected Lane A's 1024-D memories index, configured dimension is {settings.embed_dim}. No writes were made.")

    collection = db()[MEMORIES]
    query = {"$and": [OWNED, missing_embedding_filter()]}
    count = await collection.count_documents(query)
    print(f"memories: lane-d (seed+learned) missing embeddings={count}; dry_run={dry_run}; model={settings.embed_model}; dimensions={settings.embed_dim}")
    if dry_run or count == 0:
        return

    cursor = collection.find(query, {"_id": 1, "text": 1}).sort("_id", 1)
    batch: list[dict] = []
    async for record in cursor:
        batch.append(record)
        if len(batch) == 128:  # one Voyage call for the whole lane-d seed
            await write_batch(collection, batch)
            batch = []
    if batch:
        await write_batch(collection, batch)


async def write_batch(collection, batch: list[dict]) -> None:
    vectors = None
    for attempt in range(6):  # free tier is 3 RPM: back off 25s, 40s, 55s... between tries
        try:
            vectors = await embed([record["text"] for record in batch], "document")
            break
        except Exception as error:  # noqa: BLE001
            if "RateLimit" not in type(error).__name__ or attempt == 5:
                raise
            wait = 25 + 15 * attempt
            print(f"Voyage rate limited; retrying in {wait}s (attempt {attempt + 2}/6)")
            await asyncio.sleep(wait)
    if len(vectors) != len(batch) or any(len(vector) != 1024 for vector in vectors):
        raise RuntimeError("Voyage returned an unexpected vector count or dimension; refusing writes.")
    for record, vector in zip(batch, vectors, strict=True):
        result = await collection.update_one(
            {"$and": [{"_id": record["_id"]}, OWNED, missing_embedding_filter()]},
            {"$set": {"embedding": vector}},
        )
        if result.modified_count:
            print(f"embedded {record['_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count eligible lane-d memories without embedding or writing")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.dry_run))
