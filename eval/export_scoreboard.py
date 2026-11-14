"""Export the scoreboard + every eval_runs doc for the demo user to eval/results/ (read-only on Atlas)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

from app import db  # noqa: E402
from app.api.learning_routes import eval_scoreboard  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> None:
    try:
        runs = await db.db()[db.EVAL_RUNS].find({"user_id": settings.demo_user_id}).sort("created_at", 1).to_list(None)
        scoreboard = await eval_scoreboard()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ROOT / "eval" / "results" / f"scoreboard_export_{stamp}.json"
        path.write_text(json.dumps({
            "exported_at": stamp, "database": settings.mongodb_db, "collection": db.EVAL_RUNS,
            "scoreboard_endpoint": scoreboard.model_dump(mode="json"), "eval_runs": runs,
        }, indent=2, default=str) + "\n")
        labels = {}
        for run in runs:
            labels[run.get("label")] = labels.get(run.get("label"), 0) + 1
        print(f"exported {len(runs)} eval_runs docs {labels} + scoreboard -> {path.relative_to(ROOT)}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
