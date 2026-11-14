"""Single-command real preflight, seed-vector backfill, and cold/warm evaluation."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    command = f"source .venv/bin/activate && python eval/run_real.py --repeats {args.repeats}"
    env = os.environ.copy()
    env["EVAL_COMMAND"] = command
    env["LLM_PROVIDER"] = "nebius"
    preflight = subprocess.run(
        [sys.executable, "eval/preflight.py"], cwd=ROOT, env=env,
        check=False, text=True, capture_output=True,
    )
    print(preflight.stdout, end="")
    if preflight.returncode:
        raise SystemExit(preflight.returncode)
    resolved = re.search(r"^PASS Nebius model: (.+)$", preflight.stdout, re.MULTILINE)
    if not resolved:
        raise SystemExit("Preflight passed without reporting a resolved Nebius model.")
    env["NEBIUS_MODEL"] = resolved.group(1).strip()
    for step in (
        [sys.executable, "seed/backfill_embeddings.py"],
        [sys.executable, "eval/run_eval.py", "--repeats", str(args.repeats)],
    ):
        subprocess.run(step, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
