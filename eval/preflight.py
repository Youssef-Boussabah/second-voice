"""Credential-safe preflight for the real Nebius + Atlas + Voyage evaluation."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db
from app.config import settings
from app.embeddings import embed
from app.llm import resolve_nebius_model


async def main() -> None:
    failures = []

    def report(check: str, ok: bool, detail: str) -> None:
        print(f"{'PASS' if ok else 'FAIL'} {check}: {detail}")
        if not ok:
            failures.append(check)

    report("NEBIUS_API_KEY", bool(settings.nebius_api_key), "present" if settings.nebius_api_key else "missing")
    report("VOYAGE_API_KEY", bool(settings.voyage_api_key), "present" if settings.voyage_api_key else "missing")
    report("MOCK_LLM", not settings.mock_llm, "false" if not settings.mock_llm else "must be false")
    report("MOCK_EMBED", not settings.mock_embed, "false" if not settings.mock_embed else "must be false")
    report("LLM_PROVIDER", settings.llm_provider == "nebius", settings.llm_provider)
    report("embedding index dimension", settings.embed_dim == 1024, str(settings.embed_dim))
    if failures:
        raise SystemExit("Preflight failed; no backfill or evaluation was started.")

    try:
        await db.db().command("ping")
        report("Atlas ping", True, settings.mongodb_db)
    except Exception as error:
        report("Atlas ping", False, type(error).__name__)

    try:
        model = await resolve_nebius_model(settings.nebius_model)
        report("Nebius model", True, model)
    except Exception as error:
        report("Nebius model", False, type(error).__name__)

    try:
        vectors = await embed(["Second Voice vector dimension preflight."], "document")
        valid = len(vectors) == 1 and len(vectors[0]) == 1024
        report("Voyage embedding dimensions", valid, str(len(vectors[0]) if vectors else 0))
    except Exception as error:
        report("Voyage embedding dimensions", False, type(error).__name__)

    await db.close()
    if failures:
        raise SystemExit("Preflight failed; no backfill or evaluation was started.")
    print("Preflight passed.")


if __name__ == "__main__":
    asyncio.run(main())
