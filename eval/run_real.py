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
    parser.add_argument("--expect-suggest-model", default="Qwen/Qwen3-30B-A3B-Instruct-2507",
                        help="refuse to run unless the resolved suggestion model is exactly this")
    args = parser.parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    command = f"source .venv/bin/activate && python eval/run_real.py --repeats {args.repeats}"
    env = os.environ.copy()
    env["EVAL_COMMAND"] = command
    env["LLM_PROVIDER"] = "nebius"
    env["EXPECT_SUGGEST_MODEL"] = args.expect_suggest_model
    preflight = subprocess.run(
        [sys.executable, "eval/preflight.py"], cwd=ROOT, env=env,
        check=False, text=True, capture_output=True,
    )
    print(preflight.stdout, end="")
    if preflight.returncode:
        raise SystemExit(preflight.returncode)
    suggest = re.search(r"^PASS Nebius suggestion model: (.+)$", preflight.stdout, re.MULTILINE)
    summary = re.search(r"^PASS Nebius summary model: (.+)$", preflight.stdout, re.MULTILINE)
    if not suggest or not summary:
        raise SystemExit("Preflight passed without reporting resolved suggestion and summary models.")
    env["NEBIUS_MODEL"] = suggest.group(1).strip()
    env["NEBIUS_SUMMARY_MODEL"] = summary.group(1).strip()
    print(f"Models: suggestions={env['NEBIUS_MODEL']} summaries={env['NEBIUS_SUMMARY_MODEL']}", flush=True)
    for step in (
        [sys.executable, "seed/backfill_embeddings.py"],
        [sys.executable, "eval/run_eval.py", "--repeats", str(args.repeats)],
    ):
        subprocess.run(step, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    main()
