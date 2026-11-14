"""READ-ONLY audit: which learning workers are attached to this database, and signs of an old one.

Usage (from backend/):  python scripts/worker_audit.py
Never writes, never kills anything. See docs/operations/learning-worker.md.

Reports:
  1. the active-worker lease (v2 workers only)
  2. every client with a change stream open on <db>.events, with appName, client IP:port and OS
     (needs the Atlas user to be allowed to run $currentOp; skipped with a note otherwise)
  3. data symptoms of a worker that predates the lease/claim design:
     - learned rules with a random id (v2 ids are "bnd_" + the triggering event id)
     - two learned rules from the same triggering event
     - two active phrases with the same wording for the same person
     - recent learnable events that no v2 worker has marked
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.learning.worker import LEARNABLE, LOCK_ID, STATE_ID  # noqa: E402


async def main() -> None:
    d = db.db()
    uid = settings.demo_user_id
    now = datetime.now(timezone.utc)
    print(f"database={settings.mongodb_db} user={uid}\n")

    lock = await d.worker_state.find_one({"_id": LOCK_ID})
    live = bool(lock and lock.get("expires_at") and lock["expires_at"] > now)
    print("1. v2 lease:", f"held by {lock['owner']} (expires {lock['expires_at']:%H:%M:%S} UTC)" if live
          else "free / expired")
    state = await d.worker_state.find_one({"_id": STATE_ID})
    print("   v2 sweep_since:", state.get("sweep_since") if state else "never run on this database")
    legacy = await d.worker_state.find_one({"_id": "learning_worker"})
    if legacy:
        print("   legacy v1 state doc 'learning_worker' last updated:", legacy.get("updated_at"))

    print("\n2. clients with a change stream on events:")
    try:
        cur = await db.client().admin.aggregate([{"$currentOp": {"allUsers": True, "idleCursors": True}}])
        found = 0
        for op in await cur.to_list(1000):
            # an awaiting change stream shows as a getMore; the $changeStream is in the originating command
            text = " ".join(str(x) for x in (op.get("command"), op.get("originatingCommand"),
                                               (op.get("cursor") or {}).get("originatingCommand")) if x)
            if op.get("ns") == f"{settings.mongodb_db}.events" and "changeStream" in text:
                found += 1
                os_ = (op.get("clientMetadata") or {}).get("os") or {}
                app = op.get("appName") or "?"
                if not (op.get("client") or op.get("client_s")):
                    print(f"   - idle cursor with no live client ({op.get('type')}): a worker that already disconnected")
                    continue
                kind = "v2 worker" if app.startswith("second-voice-worker-v2") else "UNKNOWN / pre-v2 worker?"
                print(f"   - appName={app!r} client={op.get('client') or op.get('client_s')} "
                      f"os={os_.get('type')} {os_.get('architecture', '')} -> {kind}")
        if not found:
            print("   none visible")
    except Exception as error:  # noqa: BLE001
        print(f"   $currentOp not permitted for this user ({type(error).__name__}); use the Atlas UI")

    print("\n3. data symptoms of a pre-v2 worker:")
    rules = await d.boundaries.find({"user_id": uid, "origin": "learned"},
                                    {"evidence.trigger_event_id": 1, "status": 1}).to_list(1000)
    random_ids = [r["_id"] for r in rules
                  if r.get("evidence", {}).get("trigger_event_id")
                  and r["_id"] != "bnd_" + r["evidence"]["trigger_event_id"].split("_", 1)[-1]]
    dup_triggers = [t for t, n in Counter(r.get("evidence", {}).get("trigger_event_id") for r in rules).items()
                    if t and n > 1]
    print(f"   learned rules with non-v2 (random) ids: {len(random_ids)}")
    print(f"   triggering events that produced >1 rule: {dup_triggers or 'none'}")
    phrases = await d.memories.find({"user_id": uid, "kind": "phrase", "status": "active"},
                                    {"person_id": 1, "text": 1}).to_list(5000)
    dup_phrases = [k for k, n in Counter((p["person_id"], " ".join(p["text"].lower().split()))
                                         for p in phrases).items() if n > 1]
    print(f"   duplicate active phrases (same person + wording): {len(dup_phrases)}")
    for person, text in dup_phrases[:5]:
        print(f"     - {person}: {text[:60]!r}")
    since = (state or {}).get("sweep_since") or now - timedelta(hours=1)
    unmarked = await d.events.count_documents({
        "user_id": uid, "type": {"$in": list(LEARNABLE)}, "seed_source": {"$exists": False},
        "created_at": {"$gte": since, "$lte": now - timedelta(minutes=2)},
        "learning.state": {"$exists": False}})
    print(f"   learnable events since {since:%Y-%m-%d %H:%M} UTC not marked by a v2 worker: {unmarked}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
