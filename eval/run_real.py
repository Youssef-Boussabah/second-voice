"""Single-command real preflight, seed-vector backfill, and cold/warm evaluation."""
from __future__ import annotations

import argparse
import os
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
    steps = [
        [sys.executable, "eval/preflight.py"],
        [sys.executable, "seed/backfill_embeddings.py"],
        [sys.executable, "eval/run_eval.py", "--repeats", str(args.repeats)],
    ]
    for step in steps:
        subprocess.run(step, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
