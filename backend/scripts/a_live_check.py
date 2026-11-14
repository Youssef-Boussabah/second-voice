"""Lane A live check: real Nebius inference + real Voyage embeddings + Atlas $vectorSearch,
then the full suggestion pipeline for a clinician vs an acquaintance.

    cd backend && python scripts/a_live_check.py            # needs NEBIUS_API_KEY + VOYAGE_API_KEY
    python scripts/a_live_check.py --keep                   # leave the check data in Atlas

All data is written under user_id=usr_lanea_check (never touches Maya's demo data) and deleted
at the end unless --keep. Exits non-zero if any check fails.
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MOCK_LLM"] = "false"
os.environ["MOCK_EMBED"] = "false"
os.environ.setdefault("LLM_PROVIDER", "nebius")

from app import db, llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.contracts import (  # noqa: E402
    SENSITIVE_TOPICS, Boundary, BoundaryScope, GeneratedCandidates, Memory, OpenThread, Person,
    SpeakerMatch, Utterance,
)
from app.embeddings import embed  # noqa: E402
from app.graph import pipeline  # noqa: E402
from app.memory import retrieval  # noqa: E402

UID = "usr_lanea_check"
DANA, MIKE = "per_chk_dana", "per_chk_mike"
FAILS: list[str] = []


def check(ok: bool, label: str) -> None:
    print(("  PASS " if ok else "  FAIL ") + label)
    if not ok:
        FAILS.append(label)


async def step_models() -> None:
    print(f"\n[1] Nebius models  provider={settings.llm_provider} base={settings.nebius_base_url}")
    models = await llm.list_nebius_models()
    print(f"  {len(models)} models available")
    for m in models:
        print("   -", m)
    print(f"  {settings.nebius_model} listed: {settings.nebius_model in models}")
    chosen = await llm.resolve_nebius_model(settings.nebius_model)
    print(f"  using: {chosen}")
    check(bool(chosen), "a chat model is resolvable")


async def step_inference() -> None:
    print("\n[2] Real inference (GeneratedCandidates)")
    t = time.perf_counter()
    out = await llm.complete_json(
        pipeline.PERSONA,
        "PARTNER: Dana Okafor (Pharmacist)\nRELATIONSHIP: clinician\n"
        'THEY JUST SAID: "Hi Maya, here for your refill?"\n'
        "Write 6 distinct candidate replies, tag topics from the taxonomy.",
        GeneratedCandidates, model=settings.suggest_model)
    ms = int((time.perf_counter() - t) * 1000)
    for c in out.candidates:
        print(f"   - {c.text}  {c.topics}")
    print(f"  {ms} ms, model={llm._nebius_resolved.get(settings.nebius_model)}, json_mode={llm._json_mode_ok}")
    check(len(out.candidates) >= 4, "schema-valid with >= 4 candidates")
    check(ms < 5000, f"suggestion model fast enough for the hot path ({ms} ms)")

    print("\n[2b] Summary model (Lane D's EpisodeSummary path)")
    from app.contracts import EpisodeSummary
    t = time.perf_counter()
    summ = await llm.complete_json(
        "Summarize this conversation for Maya's memory. Use the fixed topic taxonomy.",
        "Dana: Hi Maya, here for your refill?\nMaya: Yes please, same as October.\n"
        "Dana: I'll check if blister packs are in by Friday.", EpisodeSummary,
        model=settings.summary_model)
    ms = int((time.perf_counter() - t) * 1000)
    print(f"  {ms} ms, model={llm._nebius_resolved.get(settings.nebius_summary_model)}: {summ.summary[:140]!r} "
          f"topics={summ.topics} threads={[th.text for th in summ.open_threads_new]}")
    check(bool(summ.summary.strip()), "EpisodeSummary schema-valid")


async def step_embed_and_seed() -> None:
    print("\n[3] Real Voyage embeddings → Atlas")
    d = db.db()
    await cleanup()
    now = Person(user_id=UID, name="x", relationship="stranger").created_at
    await d[db.PEOPLE].insert_many([
        Person(id=DANA, user_id=UID, name="Dana Okafor", relationship="clinician",
               label="Pharmacist at Shoppers", consent={"voice": True, "at": now}).to_mongo(),
        Person(id=MIKE, user_id=UID, name="Mike Russo", relationship="acquaintance",
               label="Neighbour, walks his dog Biscuit", consent={"voice": True, "at": now}).to_mongo(),
    ])
    mems = [
        Memory(id="mem_chk_dana_ep", user_id=UID, person_id=DANA, kind="episode",
               text="Oct 28: Picked up Riluzole refill. Dana said the new generic looks different. "
                    "Maya joked about the line.", topics=["medication", "small_talk"],
               open_threads=[OpenThread(id="thr_chk_1", text="Dana to check if blister packs are available",
                                        owner="partner")]),
        Memory(id="mem_chk_mike_ep", user_id=UID, person_id=MIKE, kind="episode",
               text="Nov 2: Mike's dog Biscuit had surgery on her paw. Talked about the Leafs losing again.",
               topics=["small_talk", "hobbies"],
               open_threads=[OpenThread(id="thr_chk_2", text="Ask how Biscuit's paw is healing", owner="user")]),
        Memory(id="mem_chk_mike_ph", user_id=UID, person_id=MIKE, kind="phrase",
               text="Ha, the Leafs will break our hearts again.", topics=["humour", "hobbies"], uses=4),
        Memory(id="mem_chk_dana_ph", user_id=UID, person_id=DANA, kind="phrase",
               text="Same as last month, thanks Dana.", topics=["medication"], uses=5),
    ]
    t = time.perf_counter()
    vecs = await embed([m.text for m in mems], "document")
    print(f"  embedded {len(vecs)} docs, dim={len(vecs[0])}, {int((time.perf_counter() - t) * 1000)} ms")
    check(len(vecs[0]) == settings.embed_dim, f"Voyage returns {settings.embed_dim}-d vectors")
    for m, v in zip(mems, vecs):
        m.embedding = v
    await d[db.MEMORIES].insert_many([m.to_mongo() for m in mems])
    await d[db.BOUNDARIES].insert_one(Boundary(
        id="bnd_chk_acq", user_id=UID, status="active", origin="seed",
        scope=BoundaryScope(type="relationship", value="acquaintance"),
        topics=["health", "medication", "distress"]).to_mongo())

    qv = (await embed(["How is your dog's paw?"], "query"))[0]
    for i in range(30):  # Atlas Search syncs new docs within seconds
        hits = await retrieval.vector_search(UID, [MIKE], "episode", qv, limit=3)
        if hits and "score" in hits[0]:
            break
        await asyncio.sleep(2)
    print(f"  $vectorSearch hits: {[(h['_id'], round(h.get('score', 0), 3)) for h in hits]}")
    check(bool(hits) and hits[0]["_id"] == "mem_chk_mike_ep" and "score" in hits[0],
          "$vectorSearch finds Mike's episode (real index, scored)")
    leak = await retrieval.vector_search(UID, [DANA], "episode", qv, limit=3)
    check(all(h["person_id"] == DANA for h in leak), "Dana-scoped search never returns Mike's memories")


async def step_pipeline() -> None:
    print("\n[4] Full pipeline: contextual + schema-valid + privacy-filtered")
    results = {}
    for pid, text in [(DANA, "Hi Maya, here for your refill?"),
                      (MIKE, "Hey Maya! How have you been feeling lately?")]:
        utt = Utterance(session_id=f"ses_chk_{pid}", user_id=UID, text=text, source="text",
                        speaker=SpeakerMatch(kind="partner", person_id=pid, method="forced"))
        await db.db()[db.UTTERANCES].insert_one(utt.to_mongo())
        t = time.perf_counter()
        s = await pipeline.run(utt)
        ms = int((time.perf_counter() - t) * 1000)
        results[pid] = s
        print(f"\n  {pid}: \"{text}\"  ({ms} ms, latency={s.latency_ms})")
        for c in s.candidates:
            print(f"    ✓ {c.text}  {c.topics}  mem={c.memory_ids}  src={c.source}")
        for c in s.blocked:
            print(f"    🔒 {c.text}  {c.topics}  by={c.blocked_by}")
        check(len(s.candidates) == 4, f"{pid}: 4 suggestions")
        check(ms < 8000, f"{pid}: under 8 s end-to-end ({ms} ms)")

    mike = results[MIKE]
    bad = [c.text for c in mike.candidates if set(c.topics) & {"health", "medication", "distress"}]
    check(not bad, f"Mike (acquaintance): no health/medication/distress shown {bad}")
    dana = results[DANA]
    dana_text = " ".join(c.text.lower() for c in dana.candidates)
    check(any(set(c.topics) & SENSITIVE_TOPICS for c in dana.candidates)
          or any(w in dana_text for w in ("refill", "generic", "blister", "riluzole", "same")),
          "Dana (clinician): medication context still allowed / grounded")
    mike_text = " ".join(c.text.lower() for c in [*mike.candidates, *mike.blocked])
    check(any(w in mike_text for w in ("biscuit", "paw", "dog", "leafs")) or
          any(c.memory_ids for c in mike.candidates),
          "Mike: suggestions grounded in Mike's own memories")


async def cleanup() -> None:
    d = db.db()
    for coll in (db.PEOPLE, db.MEMORIES, db.BOUNDARIES, db.UTTERANCES, db.SUGGESTION_SETS, db.EVENTS):
        await d[coll].delete_many({"user_id": UID})


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    missing = [k for k, v in (("NEBIUS_API_KEY", settings.nebius_api_key),
                              ("VOYAGE_API_KEY", settings.voyage_api_key)) if not v]
    if missing:
        print("missing in .env:", ", ".join(missing))
        return 2
    try:
        await step_models()
        await step_inference()
        await step_embed_and_seed()
        await step_pipeline()
    finally:
        if not a.keep:
            await cleanup()
        await db.close()
    print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: {FAILS}'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
