"""Cold/warm evaluation through Lane A's in-process suggestion pipeline."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="force MOCK_LLM and MOCK_EMBED; output is labelled MOCK")
    parser.add_argument("--repeats", type=int, default=1)
    return parser.parse_args()


ARGS = arguments()
if ARGS.mock:
    os.environ["MOCK_LLM"] = "true"
    os.environ["MOCK_EMBED"] = "true"
os.environ["LLM_PROVIDER"] = "nebius"

from pymongo import AsyncMongoClient

from app import db
from app.config import settings
from app.contracts import (
    Event, EventType, RejectReason, Session, SpeakerKind, SpeakerMatch,
    SpeakerMethod, Topic, Utterance, UtteranceSource, new_id, utcnow,
)
from app.embeddings import embed
from app.graph import pipeline
from app.learning.boundaries import propose_and_validate
from app.memory import retrieval

FIXTURES = ROOT / "seed" / "conversations"
RELATIONSHIPS = {"per_dana": "clinician", "per_sam": "family", "per_mike": "acquaintance"}
ORDER = ("c02", "c03", "c08", "c06", "c07", "c01")
EXPECTED_MEMORY = {
    "per_dana": ("blister", "refill", "medication"),
    "per_mike": ("dog", "boots", "neighbourhood"),
    "per_sam": ("leafs", "hockey", "game"),
}


def load_scenarios() -> list[dict]:
    scenarios = []
    for conversation_id in ORDER:
        conversation = json.loads((FIXTURES / f"{conversation_id}.json").read_text())
        for index in range(0, len(conversation["turns"]), 2):
            partner_turn = conversation["turns"][index]
            user_turn = conversation["turns"][index + 1]
            scenarios.append({
                "conversation_id": conversation_id,
                "person_id": conversation["person_id"],
                "partner_text": partner_turn["text"],
                "intended": user_turn["intended"],
                "topics": user_turn["topics"],
            })
    return scenarios


def norm(value: str) -> str:
    return re.sub(r"\W+", " ", value.lower()).strip()


def enum_value(item) -> str:
    return item.value if hasattr(item, "value") else str(item)


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1)]


async def make_test_run(database, condition: str, run_number: int, scenarios: list[dict]) -> dict:
    user_id = new_id("usr")
    person_ids = {fixture_id: new_id("per") for fixture_id in RELATIONSHIPS}
    source_people = json.loads((ROOT / "seed" / "people.json").read_text())
    for person in source_people:
        original_id = person["_id"]
        person["_id"] = person_ids[original_id]
        person["user_id"] = user_id
        person["seed_source"] = "lane-d-eval"
        await database[db.PEOPLE].insert_one(person)

    await database[db.USERS].insert_one({
        "_id": user_id, "name": f"Evaluation {condition} {run_number}", "seed_source": "lane-d-eval",
        "created_at": utcnow(),
    })
    memory_ids: set[str] = set()
    if condition == "warm":
        for source in json.loads((ROOT / "seed" / "memories.json").read_text()):
            memory = dict(source)
            source_id = memory["_id"]
            memory["_id"] = new_id("mem")
            memory["user_id"] = user_id
            if memory.get("person_id") in person_ids:
                memory["person_id"] = person_ids[memory["person_id"]]
            memory["seed_source"] = "lane-d-eval"
            if settings.mock_embed:
                memory.pop("embedding", None)
            memory_ids.add(memory["_id"])
            await database[db.MEMORIES].insert_one(memory)
        for source in json.loads((ROOT / "seed" / "boundaries.json").read_text()):
            boundary = dict(source)
            boundary["_id"] = new_id("bnd")
            boundary["user_id"] = user_id
            boundary["seed_source"] = "lane-d-eval"
            await database[db.BOUNDARIES].insert_one(boundary)
        history = json.loads((ROOT / "seed" / "history_events.json").read_text())
        for source in history:
            event = dict(source)
            event["_id"] = new_id("evt")
            event["user_id"] = user_id
            event["person_id"] = person_ids[event["person_id"]]
            event["seed_source"] = "lane-d-eval"
            await database[db.EVENTS].insert_one(event)

    learned_blocked_topics = {"health", "medication"}
    latency: list[int] = []
    hits = leaks = shown = phrase_reuse = memory_hits = memory_eligible = false_positives = 0
    boundary_checked = boundary_blocked = 0
    turn_rows = []
    rejection_learned = False

    for turn_index, scenario in enumerate(scenarios):
        fixture_person_id = scenario["person_id"]
        person_id = person_ids[fixture_person_id]
        session = Session(user_id=user_id, person_ids=[person_id])
        await database[db.SESSIONS].insert_one(session.to_mongo())
        utterance = Utterance(
            session_id=session.id, user_id=user_id,
            speaker=SpeakerMatch(kind=SpeakerKind.partner, person_id=person_id, method=SpeakerMethod.forced),
            text=scenario["partner_text"], source=UtteranceSource.text,
        )
        await database[db.UTTERANCES].insert_one(utterance.to_mongo())

        person = await retrieval.load_person(person_id)
        context = await retrieval.get_context(
            user_id, person_id, scenario["partner_text"], session_id=session.id, person=person,
        )
        expected_terms = EXPECTED_MEMORY[fixture_person_id]
        memory_eligible += int(condition == "warm")
        memory_text = " ".join(memory.text.lower() for memory in [*context.relevant_episodes, *context.recent_episodes, *context.facts])
        memory_hit = condition == "warm" and any(term in memory_text for term in expected_terms)
        memory_hits += int(memory_hit)
        phrasebook_texts = {norm(memory.text) for memory in context.phrases}
        for boundary in context.boundaries:
            scope_type = enum_value(boundary.scope.type)
            scope_applies = (
                scope_type == "global"
                or (scope_type == "relationship" and boundary.scope.value == RELATIONSHIPS[fixture_person_id])
                or (scope_type == "person" and boundary.scope.value == person_id)
            )
            if scope_applies and {enum_value(topic) for topic in boundary.topics} & set(scenario["topics"]):
                false_positives += 1

        started = time.perf_counter()
        suggestion_set = await pipeline.run(utterance)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if suggestion_set is None:
            raise RuntimeError("Lane A pipeline.run returned no final suggestion set")
        latency.append(int(suggestion_set.latency_ms.get("total", elapsed_ms)))
        candidates = suggestion_set.candidates
        shown += len(candidates)
        phrasebook_matches = sum(1 for candidate in candidates if norm(candidate.text) in phrasebook_texts)
        phrase_reuse += phrasebook_matches
        leak_count = sum(
            bool({enum_value(topic) for topic in candidate.topics} & learned_blocked_topics)
            for candidate in candidates
        )
        leaks += leak_count
        if settings.mock_embed:
            exact_hit = any(norm(candidate.text) == norm(scenario["intended"]) for candidate in candidates)
            hit_method = "normalized exact-text match; no LLM judge"
        else:
            texts = [candidate.text for candidate in candidates] + [scenario["intended"]]
            vectors = await embed(texts, "query")
            intended_vector = vectors[-1]
            exact_hit = any(
                sum(left * right for left, right in zip(vector, intended_vector, strict=True)) >= 0.80
                for vector in vectors[:-1]
            )
            hit_method = "Voyage cosine similarity >= 0.80; no LLM judge"
        hits += int(exact_hit)
        row = {
            "condition": condition, "conversation_id": scenario["conversation_id"],
            "person_id": fixture_person_id, "partner_text": scenario["partner_text"],
            "intended": scenario["intended"], "candidate_count": len(candidates),
            "hit": exact_hit, "privacy_leaks": leak_count,
            "hit_method": hit_method,
            "retrieval_hit_at_3": memory_hit, "phrasebook_candidates": sum(
                1 for candidate in candidates if enum_value(candidate.source) == "phrasebook"),
            "phrasebook_reuses": phrasebook_matches,
            "candidates": [{"text": candidate.text, "topics": [enum_value(topic) for topic in candidate.topics],
                            "source": enum_value(candidate.source), "memory_ids": candidate.memory_ids}
                           for candidate in candidates],
            "latency_ms": latency[-1], "suggestion_set_id": suggestion_set.id,
        }
        turn_rows.append(row)

        if condition == "warm" and fixture_person_id == "per_mike" and not rejection_learned:
            rejected = next((candidate for candidate in candidates if {enum_value(topic) for topic in candidate.topics} & learned_blocked_topics), None)
            row["rejection_candidate_found"] = rejected is not None
            if rejected:
                rejection = Event(
                    user_id=user_id, session_id=session.id, type=EventType.suggestion_rejected,
                    person_id=person_id, relationship="acquaintance", suggestion_set_id=suggestion_set.id,
                    candidate_id=rejected.id, text=rejected.text,
                    topics=[Topic(enum_value(topic)) for topic in rejected.topics], reason=RejectReason.too_personal,
                )
                await database[db.EVENTS].insert_one(rejection.to_mongo())
                learned = await propose_and_validate(rejection)
                rejection_learned = learned is not None and enum_value(learned.status) == "active"
                row["learned_boundary_id"] = learned.id if learned else None
                row["learned_boundary_status"] = enum_value(learned.status) if learned else None
                follow_up = Utterance(
                    session_id=session.id, user_id=user_id,
                    speaker=utterance.speaker, text=scenario["partner_text"], source=UtteranceSource.text,
                )
                await database[db.UTTERANCES].insert_one(follow_up.to_mongo())
                after_reject = await pipeline.run(follow_up)
                if after_reject is None:
                    raise RuntimeError("Lane A pipeline returned no post-rejection set")
                boundary_checked += len(after_reject.candidates)
                boundary_blocked += sum(
                    bool({enum_value(topic) for topic in candidate.topics} & learned_blocked_topics)
                    for candidate in after_reject.candidates
                )

    active_rules = await database[db.BOUNDARIES].count_documents({
        "user_id": user_id, "origin": "learned", "status": "active",
    })
    metrics = {
        "hit_at_4": hits / len(scenarios),
        "taps_per_message": (hits + sum(math.ceil(len(row["intended"]) * 0.5) for row in turn_rows if not row["hit"])) / len(scenarios),
        "leaks_per_conversation": leaks / len({row["conversation_id"] for row in turn_rows}),
        "latency_p50_ms": percentile(latency, 0.50), "latency_p95_ms": percentile(latency, 0.95),
        "rules_learned": active_rules, "false_positive_rules": false_positives, "runs": 1,
        "privacy_leak_rate": leaks / shown if shown else 0.0,
        "boundary_enforcement_rate_after_rejection": 1 - boundary_blocked / boundary_checked if boundary_checked else None,
        "boundary_candidates_checked": boundary_checked,
        "partner_memory_retrieval_hit_at_3": memory_hits / memory_eligible if memory_eligible else None,
        "phrasebook_reuse_rate": phrase_reuse / shown if shown else 0.0,
        "hit_method": "normalized exact-text match; no LLM judge" if settings.mock_embed else "Voyage cosine similarity >= 0.80; no LLM judge",
    }
    return {"metrics": metrics, "per_turn": turn_rows, "user_id": user_id}


async def main() -> None:
    if ARGS.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    scenarios = load_scenarios()
    if len(scenarios) != 12:
        raise RuntimeError(f"Expected 12 fixed partner turns, found {len(scenarios)}")
    label = "MOCK" if settings.mock_llm or settings.mock_embed else "REAL"
    if label == "REAL" and (not settings.nebius_api_key or not settings.voyage_api_key):
        raise SystemExit("REAL evaluation requires NEBIUS_API_KEY and VOYAGE_API_KEY; no evaluation records were written.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    client = AsyncMongoClient(settings.mongodb_uri, appname="second-voice-eval", tz_aware=True)
    try:
        database = client[settings.mongodb_db]
        configs: dict[str, list[dict]] = {"cold": [], "warm": []}
        for condition in ("cold", "warm"):
            for repeat in range(1, ARGS.repeats + 1):
                configs[condition].append(await make_test_run(database, condition, repeat, scenarios))
        payload = {
            "label": label,
            "header": f"{label} EVALUATION — deterministic canned LLM and mock query embeddings" if label == "MOCK" else "REAL EVALUATION — Lane A Nebius/Voyage pipeline",
            "created_at": datetime.now(timezone.utc).isoformat(), "commit": commit,
            "command": os.environ.get(
                "EVAL_COMMAND",
                "source .venv/bin/activate && python eval/run_eval.py " + " ".join(sys.argv[1:]),
            ),
            "models": {"llm_provider": settings.llm_provider,
                       "suggest_model": settings.nebius_model if settings.llm_provider == "nebius" else settings.suggest_model,
                       "summary_model": settings.nebius_summary_model or settings.nebius_model,
                       "embed_model": settings.embed_model, "embed_dim": settings.embed_dim,
                       "temperature": 0.3},
            "mock_flags": {"MOCK_LLM": settings.mock_llm, "MOCK_EMBED": settings.mock_embed},
            "scenario_count": len(scenarios), "conditions": configs,
            "measurement_notes": ("No LLM judge. MOCK hit uses normalized exact text; REAL hit uses Voyage cosine >= 0.80. Phrasebook reuse is exact normalized candidate-to-retrieved-phrase matching. Mock query vectors are transient and never stored."),
        }
        results_dir = ROOT / "eval" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        suffix = "_MOCK" if label == "MOCK" else ""
        json_path = results_dir / f"{stamp}{suffix}.json"
        md_path = results_dir / f"{stamp}{suffix}.md"
        json_path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        summaries = {}
        for condition, repeats in configs.items():
            summaries[condition] = {
                key: statistics.mean(run["metrics"][key] for run in repeats if isinstance(run["metrics"].get(key), (int, float)))
                for key in ("hit_at_4", "taps_per_message", "leaks_per_conversation", "latency_p50_ms", "latency_p95_ms", "privacy_leak_rate", "phrasebook_reuse_rate")
            }
        lines = [f"# {label} Evaluation Results", "", f"Commit: `{commit}`", f"Command: `{payload['command']}`", "",
                 f"MOCK_LLM={settings.mock_llm} and MOCK_EMBED={settings.mock_embed}.", "",
                 "| Metric | COLD | WARM |", "|---|---:|---:|"]
        hit_title = "Exact-text hit@4" if settings.mock_embed else "Voyage cosine hit@4 (≥0.80)"
        for key, title in (("hit_at_4", hit_title), ("taps_per_message", "Taps/message"),
                           ("leaks_per_conversation", "Leaks/conversation"), ("privacy_leak_rate", "Privacy leak rate"),
                           ("phrasebook_reuse_rate", "Phrasebook reuse rate"), ("latency_p50_ms", "Latency p50 (ms)"),
                           ("latency_p95_ms", "Latency p95 (ms)")):
            lines.append(f"| {title} | {summaries['cold'].get(key, 'n/a')} | {summaries['warm'].get(key, 'n/a')} |")
        md_path.write_text("\n".join(lines) + "\n")
        for condition, repeats in configs.items():
            for run in repeats:
                await database[db.EVAL_RUNS].insert_one({
                    "_id": new_id("run"), "user_id": settings.demo_user_id, "config": condition,
                    "metrics": {key: value for key, value in run["metrics"].items() if key in {
                        "hit_at_4", "taps_per_message", "leaks_per_conversation", "latency_p50_ms",
                        "latency_p95_ms", "rules_learned", "false_positive_rules", "runs"}},
                    "label": label, "commit": commit, "mock_flags": payload["mock_flags"],
                    "created_at": datetime.now(timezone.utc),
                })
        print(f"{label} evaluation complete: {json_path.relative_to(ROOT)}")
        print(f"{label} summary: {md_path.relative_to(ROOT)}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
