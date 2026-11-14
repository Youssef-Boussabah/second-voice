"""Idempotent demo seed + scoped demo reset (Lane D).

Ownership tags:
- `seed_source="lane-d"`   documents loaded from `seed/*.json` (restored, never deleted).
- `written_by="lane-d"`    documents Lane D's learning code wrote at runtime (learned
                           phrases, boundaries, episodes). Reset deletes these.

Reset only ever touches the demo user (`settings.demo_user_id`) and never deletes a
document carrying another lane's tag. It deletes:
  memories/boundaries   written_by="lane-d", no seed_source       (learned after seeding)
  events                no seed_source                            (demo session events)
  sessions              all of the demo user's sessions           (demo sessions)
then re-applies the seed, restoring each lane-d seed document to its JSON state while
keeping any backfilled embedding.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import BOUNDARIES, EVENTS, MEMORIES, PEOPLE, SESSIONS, USERS

log = logging.getLogger(__name__)

SEED_TAG = "lane-d"
LEARNED_TAG = {"written_by": "lane-d"}
# DECISION: seed JSON lives at the repo root (`seed/`), next to backend/. The API reads it from
# there so `seed/load.py` and `POST /api/admin/reset-demo` share one source of truth.
SEED_DIR = Path(__file__).resolve().parents[3] / "seed"
DATE_FIELDS = ("created_at", "activated_at", "last_seen", "last_used")


def _read(name: str) -> list[dict[str, Any]]:
    return json.loads((SEED_DIR / name).read_text())


def _dates(record: dict[str, Any]) -> dict[str, Any]:
    for key in DATE_FIELDS:
        if isinstance(record.get(key), str):
            record[key] = datetime.fromisoformat(record[key].replace("Z", "+00:00"))
    return record


def seed_payloads(user_id: str = "usr_maya") -> dict[str, list[dict[str, Any]]]:
    user = {"_id": user_id, "name": "Maya Chen", "created_at": datetime(2026, 9, 1, tzinfo=timezone.utc)}
    payloads = {
        USERS: [user],
        PEOPLE: [_dates(item) | {"user_id": user_id} for item in _read("people.json")],
        MEMORIES: [_dates(item) | {"user_id": user_id, "topics": item.get("topics", [])}
                   for item in _read("memories.json")],
        BOUNDARIES: [_dates(item) | {"user_id": user_id} for item in _read("boundaries.json")],
        EVENTS: [_dates(item) for item in _read("history_events.json")],
    }
    for documents in payloads.values():
        for document in documents:
            document["seed_source"] = SEED_TAG
    return payloads


async def apply_seed(database, *, dry_run: bool) -> dict[str, dict[str, int]]:
    """Insert missing seed docs, restore owned ones, skip ids owned by someone else."""
    report: dict[str, dict[str, int]] = {}
    for name, documents in seed_payloads().items():
        collection = database[name]
        inserted = restored = skipped = 0
        for document in documents:
            previous = await collection.find_one({"_id": document["_id"]})
            if previous and previous.get("seed_source") != SEED_TAG:
                skipped += 1
                log.warning("seed skip %s/%s: existing document not owned by lane-d", name, document["_id"])
                continue
            if previous:
                restored += 1
                if not dry_run:
                    replacement = dict(document)
                    # keep runtime-only fields that the JSON doesn't carry
                    # (embeddings from the backfill; Lane B voice enrollment + its consent flag,
                    # which a demo reset must never grant or revoke).
                    for keep in ("embedding", "voiceprints", "voice_centroid", "consent"):
                        if keep in previous:
                            replacement[keep] = previous[keep]
                    await collection.replace_one({"_id": document["_id"], "seed_source": SEED_TAG}, replacement)
            else:
                inserted += 1
                if not dry_run:
                    await collection.insert_one(document)
        report[name] = {"insert": inserted, "restore": restored, "skip_not_owned": skipped}
    return report


def reset_filters(user_id: str) -> dict[str, dict[str, Any]]:
    learned = {"user_id": user_id, **LEARNED_TAG, "seed_source": {"$exists": False}}
    return {
        MEMORIES: dict(learned),
        BOUNDARIES: dict(learned),
        EVENTS: {"user_id": user_id, "seed_source": {"$exists": False}},
        SESSIONS: {"user_id": user_id, "seed_source": {"$exists": False}},
    }


async def reset_demo(database, *, dry_run: bool, user_id: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    user_id = user_id or settings.demo_user_id
    deleted: dict[str, int] = {}
    for name, flt in reset_filters(user_id).items():
        if dry_run:
            deleted[name] = await database[name].count_documents(flt)
        else:
            deleted[name] = (await database[name].delete_many(flt)).deleted_count
    seed = await apply_seed(database, dry_run=dry_run)
    elapsed = int((time.perf_counter() - started) * 1000)
    log.info("reset-demo user=%s dry_run=%s deleted=%s seed=%s %dms", user_id, dry_run, deleted, seed, elapsed)
    return {"ok": True, "dry_run": dry_run, "user_id": user_id, "deleted": deleted, "seed": seed,
            "latency_ms": elapsed}
