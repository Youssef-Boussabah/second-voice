"""Read-only: list exactly what POST /api/admin/reset-demo would delete, and prove what it spares."""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.learning.demo_seed import SEEDED_AT, reset_demo, reset_filters  # noqa: E402

AGENT_A = {"sessions": "ses_db48f0c8f7b7", "utterances": "utt_12049ed62808",
           "suggestion_sets": "sug_8c6a98f3935e", "events": "evt_3e07110f9d5b"}


async def main() -> None:
    database = db.db()
    try:
        user = settings.demo_user_id
        filters = reset_filters(user)
        print(f"reset-demo preview: db={settings.mongodb_db} user={user} SEEDED_AT={SEEDED_AT.isoformat()}")
        print(f"collections reset may delete from: {sorted(filters)} (nothing else)")
        for name, flt in filters.items():
            docs = await database[name].find(flt, {"embedding": 0}).to_list(None)
            print(f"\n{name}: would delete {len(docs)}")
            if name == "events":
                print("  by type:", dict(Counter(d.get("type") for d in docs)))
            for d in docs:
                detail = d.get("text") or d.get("type") or d.get("person_ids") or d.get("scope")
                stamp = d.get("created_at") or d.get("started_at")
                tags = {k: d.get(k) for k in ("origin", "written_by", "kind", "person_id") if d.get(k)}
                print(f"  {d['_id']}  {stamp}  {tags}  {str(detail)[:70]!r}")
        print("\nSpared (verified by query):")
        for name in ("eval_runs", "worker_state", "utterances", "suggestion_sets", "audio_clips"):
            print(f"  {name}: never deleted or written; total docs={await database[name].count_documents({})}")
        print("  users/people: never deleted; only the 1+3 lane-d seed docs are restored in place")
        for name, doc_id in AGENT_A.items():
            exists = await database[name].count_documents({"_id": doc_id})
            hit = await database[name].count_documents({"_id": doc_id, **filters[name]}) if name in filters else 0
            print(f"  Agent A {name}/{doc_id}: exists={exists} would_delete={hit}")
        seed_hits = sum([await database[n].count_documents({"$and": [f, {"seed_source": "lane-d"}]}) for n, f in filters.items()])
        other_users = sum([await database[n].count_documents({"$and": [f, {"user_id": {"$ne": user}}]}) for n, f in filters.items()])
        print(f"  lane-d seed docs matched: {seed_hits}; other users' docs matched: {other_users}")
        emb = await database.memories.count_documents({"seed_source": "lane-d", "embedding.1023": {"$exists": True}})
        vp = await database.people.count_documents({"user_id": user, "voiceprints.0": {"$exists": True}})
        consent = await database.people.count_documents({"user_id": user, "consent.voice": True})
        print(f"  lane-d seed memories with 1024-d embedding: {emb} (restore keeps embedding unless seed text changed)")
        vp_all = await database.people.count_documents({"voiceprints.0": {"$exists": True}})
        print(f"  demo people with voiceprints: {vp}; with consent.voice=true: {consent} (restore always keeps both); "
              f"people with voiceprints in db: {vp_all} (non-seed people are never touched)")
        result = await reset_demo(database, dry_run=True)
        print(f"\nreset_demo(dry_run=True): deleted={result['deleted']} seed={result['seed']}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
