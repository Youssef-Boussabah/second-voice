"""Lane A: hybrid retrieval ($vectorSearch + $search, fused with RRF in Python).
See docs/tasks/A-brain.md step 4.

Everything here is relationship-scoped: every query filters on (user_id, person_id), so
memories about Dana can never leak into a conversation with Mike. Each Atlas Search stage
degrades to a plain `find` if the search index isn't queryable yet, so the demo never stalls.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import ValidationError

from app import db
from app.config import settings
from app.contracts import (
    Boundary, Memory, OpenThread, Person, PersonOut, RetrievedContext, Utterance,
)
from app.embeddings import embed_query

log = logging.getLogger(__name__)

_NO_VEC = {"embedding": 0}


def rrf(*ranked_id_lists: list[str], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion over lists of ids (best first)."""
    scores: dict[str, float] = {}
    for ids in ranked_id_lists:
        for rank, _id in enumerate(ids):
            scores[_id] = scores.get(_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


# ───────────────────────── small helpers ─────────────────────────
def _parse(model, docs: list[dict[str, Any]]) -> list:
    out = []
    for d in docs:
        try:
            out.append(model.model_validate(d))
        except ValidationError as e:
            log.warning("skipping malformed %s %s: %s", model.__name__, d.get("_id"), str(e)[:200])
    return out


def person_out(doc: dict[str, Any]) -> PersonOut:
    p = Person.model_validate(doc)
    return PersonOut(id=p.id, name=p.name, relationship=p.relationship, label=p.label,
                     enrolled=bool(p.voice_centroid), last_seen=p.last_seen)


async def load_person(person_id: str | None) -> PersonOut | None:
    if not person_id:
        return None
    doc = await db.db()[db.PEOPLE].find_one({"_id": person_id}, {"voiceprints": 0, "voice_centroid": 0})
    if not doc:
        return None
    try:
        return person_out(doc)
    except ValidationError:
        log.warning("malformed person %s", person_id)
        return None


async def list_people(user_id: str) -> list[PersonOut]:
    cur = db.db()[db.PEOPLE].find({"user_id": user_id}, {"voiceprints": 0})
    out: list[PersonOut] = []
    async for d in cur:
        try:
            out.append(person_out(d))
        except ValidationError:
            log.warning("malformed person %s", d.get("_id"))
    return out


async def active_boundaries(user_id: str) -> list[Boundary]:
    docs = await db.db()[db.BOUNDARIES].find({"user_id": user_id, "status": "active"}).to_list(200)
    return _parse(Boundary, docs)


async def recent_turns(session_id: str, limit: int = 10) -> list[Utterance]:
    docs = await (db.db()[db.UTTERANCES].find({"session_id": session_id})
                  .sort("created_at", -1).limit(limit).to_list(limit))
    return list(reversed(_parse(Utterance, docs)))


# ───────────────────────── Atlas Search ─────────────────────────
async def vector_search(user_id: str, person_ids: list[str], kind: str, qvec: list[float],
                        limit: int = 5, num_candidates: int = 100) -> list[dict[str, Any]]:
    """$vectorSearch over memories (index #2), scoped to the person(s). Returns docs + score."""
    flt: dict[str, Any] = {"user_id": user_id, "kind": kind, "status": "active"}
    flt["person_id"] = person_ids[0] if len(person_ids) == 1 else {"$in": person_ids}
    pipeline = [
        {"$vectorSearch": {"index": db.IDX_MEMORIES_VECTOR, "path": "embedding", "queryVector": qvec,
                           "numCandidates": num_candidates, "limit": limit, "filter": flt}},
        {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}},
    ]
    try:
        cur = await db.db()[db.MEMORIES].aggregate(pipeline)
        return await cur.to_list(limit)
    except Exception as e:  # noqa: BLE001 index building / unsupported → degrade
        log.warning("$vectorSearch failed (%s); falling back to find()", str(e)[:200])
        flt["status"] = "active"
        return await (db.db()[db.MEMORIES].find(flt, _NO_VEC)
                      .sort([("uses", -1), ("created_at", -1)]).limit(limit).to_list(limit))


async def text_search(user_id: str, person_id: str, kind: str, text: str,
                      limit: int = 5) -> list[dict[str, Any]]:
    """$search (index #3) full-text over memories, scoped to (user, person, kind)."""
    if not text.strip():
        return []
    pipeline = [
        {"$search": {"index": db.IDX_MEMORIES_TEXT, "compound": {
            "must": [{"text": {"query": text, "path": "text"}}],
            "filter": [
                {"equals": {"path": "user_id", "value": user_id}},
                {"equals": {"path": "person_id", "value": person_id}},
                {"equals": {"path": "kind", "value": kind}},
                {"equals": {"path": "status", "value": "active"}},
            ]}}},
        {"$limit": limit},
        {"$project": {"embedding": 0, "score": {"$meta": "searchScore"}}},
    ]
    try:
        cur = await db.db()[db.MEMORIES].aggregate(pipeline)
        return await cur.to_list(limit)
    except Exception as e:  # noqa: BLE001
        log.warning("$search failed (%s); skipping text leg", str(e)[:200])
        return []


async def phrase_candidates(user_id: str, person_id: str | None, qvec: list[float],
                            limit: int = 6) -> list[Memory]:
    """Instant stage: the user's own phrases for this person ∪ global, nearest to the utterance."""
    pids = [person_id, "global"] if person_id else ["global"]
    return _parse(Memory, await vector_search(user_id, pids, "phrase", qvec, limit=limit))


# ───────────────────────── main entry ─────────────────────────
async def get_context(user_id: str, person_id: str | None, utterance_text: str, *,
                      session_id: str | None = None, qvec: list[float] | None = None,
                      person: PersonOut | None = None, skip_embed: bool = False) -> RetrievedContext:
    """Everything the generator needs about this relationship, in one parallel fan-out."""
    t0 = time.perf_counter()
    mem = db.db()[db.MEMORIES]
    if qvec is None and utterance_text and not skip_embed:
        try:
            qvec = await embed_query(utterance_text)
        except Exception as e:  # noqa: BLE001  text search still runs without a vector
            log.warning("query embedding unavailable (%s); text-only retrieval", str(e)[:160])

    async def _person():
        return person if person is not None else await load_person(person_id)

    async def _hybrid() -> list[Memory]:
        if not person_id:
            return []
        async def _none() -> list:
            return []
        vec_docs, txt_docs = await asyncio.gather(
            vector_search(user_id, [person_id], "episode", qvec, limit=5) if qvec is not None else _none(),
            text_search(user_id, person_id, "episode", utterance_text, limit=5),
        )
        by_id = {d["_id"]: d for d in [*vec_docs, *txt_docs]}
        fused = rrf([d["_id"] for d in vec_docs], [d["_id"] for d in txt_docs])[:3]
        return _parse(Memory, [by_id[i] for i in fused])

    async def _recent() -> list[Memory]:
        if not person_id:
            return []
        docs = await (mem.find({"user_id": user_id, "person_id": person_id, "kind": "episode",
                                "status": "active"}, _NO_VEC)
                      .sort("created_at", -1).limit(3).to_list(3))
        return _parse(Memory, docs)

    async def _phrases() -> list[Memory]:
        pids = [person_id, "global"] if person_id else ["global"]
        docs = await (mem.find({"user_id": user_id, "person_id": {"$in": pids}, "kind": "phrase",
                                "status": "active"}, _NO_VEC)
                      .sort("uses", -1).limit(8).to_list(8))
        return _parse(Memory, docs)

    async def _facts() -> list[Memory]:
        pids = [person_id, "global"] if person_id else ["global"]
        docs = await (mem.find({"user_id": user_id, "person_id": {"$in": pids}, "kind": "fact",
                                "status": "active"}, _NO_VEC)
                      .sort("created_at", -1).limit(10).to_list(10))
        return _parse(Memory, docs)

    async def _turns() -> list[Utterance]:
        return await recent_turns(session_id) if session_id else []

    p, relevant, recent, phrases, facts, bnds, turns = await asyncio.gather(
        _person(), _hybrid(), _recent(), _phrases(), _facts(), active_boundaries(user_id), _turns(),
    )

    threads: list[OpenThread] = []
    seen: set[str] = set()
    for ep in [*recent, *relevant]:
        for th in ep.open_threads:
            if th.status == "open" and th.id not in seen:
                seen.add(th.id)
                threads.append(th)

    ctx = RetrievedContext(person=p, recent_episodes=recent, relevant_episodes=relevant,
                           open_threads=threads, phrases=phrases, facts=facts, boundaries=bnds,
                           recent_turns=turns)
    log.info("retrieve person=%s episodes=%d/%d phrases=%d facts=%d bnds=%d %dms", person_id,
             len(recent), len(relevant), len(phrases), len(facts), len(bnds),
             (time.perf_counter() - t0) * 1000)
    return ctx


def demo_user() -> str:
    return settings.demo_user_id
