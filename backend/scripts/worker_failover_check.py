"""Live failover check for the learning worker against REAL Atlas change streams.

Runs two worker processes on a THROWAWAY database (name must end in "_it"), with mock LLM and
embeddings (no paid API calls), and verifies:
  1. one worker is active, the other in standby
  2. events are processed once; repeated wording becomes one phrase with uses == events
  3. hard-killing the active worker → standby takes over after the lease expires
  4. events inserted while the active worker is dead are still processed (resume / sweep)
  5. a claim abandoned mid-processing (crashed claimant) is retaken after its lease
  6. a failed event whose backoff has elapsed is retried to `done`
  7. a malformed event is recorded as `failed` with its error (not silently dropped)

Usage (from backend/):  python scripts/worker_failover_check.py
It never touches the real database and never deletes anything; it prints the scratch DB name so
it can be dropped by hand afterwards.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB = os.environ.get("IT_DB", "second_voice_worker_it")
USER = "usr_worker_it"
if not DB.endswith("_it"):
    raise SystemExit("refusing to run: IT_DB must end in _it (throwaway database)")

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
ENV = os.environ | {"MONGODB_DB": DB, "DEMO_USER_ID": USER, "MOCK_LLM": "true", "MOCK_EMBED": "true",
                    "PYTHONIOENCODING": "utf-8"}
os.environ.update({"MONGODB_DB": DB, "DEMO_USER_ID": USER})

from pymongo import AsyncMongoClient  # noqa: E402

from app.config import Settings  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}", flush=True)


def start_worker(tag: str, logdir: Path) -> subprocess.Popen:
    log = open(logdir / f"worker-{tag}.log", "w", encoding="utf-8")
    return subprocess.Popen([sys.executable, "-m", "app.learning.worker"], cwd=BACKEND, env=ENV,
                            stdout=log, stderr=subprocess.STDOUT)


def hard_kill(proc: subprocess.Popen) -> None:
    """Crash, not shutdown: no finally blocks, no lease release (whole process tree on Windows)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    proc.wait(10)


def evt(event_id: str, text: str, **extra) -> dict:
    return {"_id": event_id, "user_id": USER, "type": "reply_typed", "session_id": "ses_it",
            "person_id": "per_it", "relationship": "clinician", "text": text, "topics": [],
            "created_at": datetime.now(timezone.utc)} | extra


async def wait_for(pred, timeout: float, every: float = 1.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if await pred():
            return True
        await asyncio.sleep(every)
    return False


async def main() -> None:
    settings = Settings()
    client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice-worker-it", tz_aware=True)
    d = client[DB]
    logdir = Path(os.environ.get("IT_LOGDIR", "."))
    run = datetime.now(timezone.utc).strftime("%H%M%S")
    print(f"scratch database: {DB} (drop by hand when done); run {run}", flush=True)

    async def state(eid: str) -> dict:
        doc = await d.events.find_one({"_id": eid}, {"learning": 1})
        return (doc or {}).get("learning", {})

    async def lock_owner() -> str | None:
        doc = await d.worker_state.find_one({"_id": "learning_worker_lock"})
        return (doc or {}).get("owner") if doc and doc["expires_at"] > datetime.now(timezone.utc) else None

    async def done(*ids: str):
        async def pred():
            for i in ids:
                if (await state(i)).get("state") != "done":
                    return False
            return True
        return pred

    procs = {"A": start_worker("A", logdir), "B": start_worker("B", logdir)}

    def owner_of(tag: str) -> str | None:
        m = re.search(r"learning worker (\S+) starting", (logdir / f"worker-{tag}.log").read_text(encoding="utf-8"))
        return m.group(1) if m else None

    async def one_active():
        owners = {owner_of(t) for t in procs}
        return (await lock_owner()) in owners
    # a lease left by an earlier crashed run may still be live: wait it out (<= lease + heartbeat)
    ok = await wait_for(one_active, 60)
    current = await lock_owner()
    active = next((t for t in procs if owner_of(t) == current), None)
    standby = "B" if active == "A" else "A"
    standby_log = (logdir / f"worker-{standby}.log").read_text(encoding="utf-8")
    check("1 one active worker, the other in standby", ok and active is not None and "standby" in standby_log,
          f"active={active} owner={owner_of(active) if active else None}")

    same = f"See you Friday ({run})."
    await d.events.insert_many([evt(f"evt_{run}_1", same), evt(f"evt_{run}_2", same.upper()),
                                evt(f"evt_{run}_3", f"Thanks, that helps ({run}).")])
    ok = await wait_for(await done(f"evt_{run}_1", f"evt_{run}_2", f"evt_{run}_3"), 30)
    ph = await d.memories.find_one({"user_id": USER, "text": same})
    attempts = [(await state(f"evt_{run}_{i}")).get("attempts") for i in (1, 2, 3)]
    check("2 events done once, same wording merged", ok and ph and ph["uses"] == 2 and attempts == [1, 1, 1],
          f"uses={ph and ph['uses']} attempts={attempts}")

    hard_kill(procs[active])           # crash: no lease release, no cleanup
    t0 = time.monotonic()
    await d.events.insert_one(evt(f"evt_{run}_4", f"Inserted while the active worker is dead ({run})."))

    async def standby_active():
        return (await lock_owner()) == owner_of(standby)
    took_over = await wait_for(standby_active, 60)
    check("3 standby took over after lease expiry", took_over,
          f"after {time.monotonic() - t0:.0f}s (lease {30}s + heartbeat {10}s)")
    ok = await wait_for(await done(f"evt_{run}_4"), 60)
    check("4 event inserted during the outage processed", ok, str(await state(f"evt_{run}_4")))

    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    await d.events.insert_many([
        evt(f"evt_{run}_5", f"Claimed by a crashed worker ({run}).",
            learning={"state": "processing", "owner": "ghost:1", "attempts": 1, "lease_until": past}),
        evt(f"evt_{run}_6", f"Failed once, backoff elapsed ({run}).",
            learning={"state": "failed", "owner": "ghost:1", "attempts": 1, "lease_until": past,
                      "last_error": "TimeoutError: injected"}),
        evt(f"evt_{run}_7", "Malformed topics", topics=["not_a_topic"]),
    ])
    ok = await wait_for(await done(f"evt_{run}_5", f"evt_{run}_6"), 75)
    s5, s6 = await state(f"evt_{run}_5"), await state(f"evt_{run}_6")
    check("5 abandoned claim retaken", ok and s5.get("attempts") == 2 and s5.get("owner") != "ghost:1", str(s5)[:160])
    check("6 failed event retried to done", ok and s6.get("attempts") == 2, str(s6)[:160])
    s7 = await state(f"evt_{run}_7")
    check("7 malformed event recorded as failed", s7.get("state") == "failed" and "Validation" in s7.get("last_error", ""),
          str(s7)[:200])

    phrase_count = await d.memories.count_documents({"user_id": USER, "kind": "phrase", "text": {"$regex": run}})
    check("8 no duplicate phrases", phrase_count == 5, f"phrases this run={phrase_count} (expected 5 distinct)")

    for proc in procs.values():
        if proc.poll() is None:
            hard_kill(proc)
    await client.close()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed", flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
