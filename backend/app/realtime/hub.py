"""Lane A: WebSocket fan-out + change-stream tails. See docs/04-api-contracts.md §2.

# DECISION: in-process writes (suggestion_sets, utterances: written by this API process,
# including Lane B's voice routes via pipeline.on_partner_utterance) are pushed with a direct
# `emit()` from the write site. That keeps them low-latency and works without change streams.
# Cross-process writes (boundaries + memories, written by Lane D's worker) arrive via change
# streams when USE_CHANGE_STREAMS=true. That way no message is ever delivered twice.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.config import settings
from app.contracts import Boundary, WSMessage

log = logging.getLogger(__name__)

_connections: dict[str, set[WebSocket]] = defaultdict(set)
_tasks: list[asyncio.Task] = []


async def startup() -> None:
    _tasks.append(asyncio.create_task(_warm(), name="warmup"))
    if not settings.use_change_streams:
        log.info("change streams disabled; WS uses direct broadcast only")
        return
    _tasks.append(asyncio.create_task(_tail("boundaries", _on_boundary), name="tail-boundaries"))
    _tasks.append(asyncio.create_task(_tail("memories", _on_memory), name="tail-memories"))


async def shutdown() -> None:
    for t in _tasks:
        t.cancel()
    for t in _tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _tasks.clear()


def register(session_id: str, ws: WebSocket) -> None:
    _connections[session_id].add(ws)


def unregister(session_id: str, ws: WebSocket) -> None:
    _connections[session_id].discard(ws)
    if not _connections[session_id]:
        _connections.pop(session_id, None)


def connection_count() -> int:
    return sum(len(c) for c in _connections.values())


async def broadcast(msg: WSMessage, *, all_sessions: bool = False) -> None:
    targets = (
        [ws for conns in _connections.values() for ws in conns]
        if all_sessions or msg.session_id is None
        else list(_connections.get(msg.session_id, ()))
    )
    payload = msg.model_dump(mode="json")
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001: a dead socket must not break fan-out
            log.warning("dropping dead websocket")
            for conns in _connections.values():
                conns.discard(ws)


async def emit(type_: str, session_id: str | None, data: Any, *, all_sessions: bool = False) -> None:
    """Build + broadcast a WSMessage. Accepts pydantic models or dicts. Never raises."""
    try:
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json", by_alias=True)
        await broadcast(WSMessage(type=type_, session_id=session_id, data=data),
                        all_sessions=all_sessions)
    except Exception:  # noqa: BLE001
        log.exception("emit %s failed", type_)


def emit_boundary_direct_needed() -> bool:
    """Write sites that change boundaries in-process call emit() themselves only when
    change streams are off (otherwise the tail delivers it)."""
    return not settings.use_change_streams


async def _warm() -> None:
    """Background warm-up (never blocks startup): Atlas connection pool + LLM model check."""
    import asyncio as _aio
    import time as _time

    from app import db, llm
    from app.memory import retrieval

    await db.warmup()
    # Run the instant stage's exact queries once per known person (query plans + server cache),
    # so the first real utterance after a restart is as fast as the rest.
    t = _time.perf_counter()
    try:
        uid = settings.demo_user_id
        people = await retrieval.list_people(uid)
        for pid in [None, *[p.id for p in people]]:
            await _aio.gather(retrieval.load_person(pid), retrieval.active_boundaries(uid),
                              retrieval.saved_phrases(uid, pid))
        log.info("instant-path warmup %d people %d ms", len(people), (_time.perf_counter() - t) * 1000)
    except Exception as e:  # noqa: BLE001
        log.warning("instant-path warmup failed: %s", str(e)[:200])
    if settings.llm_provider == "nebius" and not settings.mock_llm and settings.nebius_api_key:
        try:
            for m in {settings.nebius_model, settings.nebius_summary_model or settings.nebius_model,
                      *([settings.llm_hedge_model] if settings.llm_hedge_model else [])}:
                await llm.resolve_nebius_model(m)
        except Exception as e:  # noqa: BLE001
            log.warning("llm warmup failed: %s", str(e)[:200])


# ───────────────────────── change-stream tails ─────────────────────────
async def _tail(coll_name: str, handler) -> None:
    from app import db

    pipeline = [{"$match": {"$or": [
        {"fullDocument.user_id": settings.demo_user_id},
        {"operationType": "delete"},
    ]}}]
    backoff = 1.0
    resume_token = None
    while True:
        try:
            coll = db.db()[coll_name]
            async with await coll.watch(pipeline, full_document="updateLookup",
                                        resume_after=resume_token) as stream:
                log.info("tailing change stream on %s", coll_name)
                backoff = 1.0
                async for change in stream:
                    resume_token = stream.resume_token
                    try:
                        await handler(change)
                    except Exception:  # noqa: BLE001
                        log.exception("change handler %s failed", coll_name)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("change stream %s dropped (%s); retry in %.0fs", coll_name, str(e)[:200], backoff)
            resume_token = None if "resume" in str(e).lower() else resume_token
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def boundary_change_is_news(change: dict[str, Any], status: str) -> bool:
    """Only a NEW rule (insert) or a status flip is worth a toast. A demo reset re-applying the
    seed (replace) or an unrelated field update must not announce "Learned: ..." again."""
    op = change.get("operationType")
    if op == "insert":
        return status in ("active", "proposed")
    if op == "update":
        fields = (change.get("updateDescription") or {}).get("updatedFields") or {}
        return "status" in fields
    return False


async def _on_boundary(change: dict[str, Any]) -> None:
    doc = change.get("fullDocument")
    if not doc:
        return
    try:
        b = Boundary.model_validate(doc)
    except Exception:  # noqa: BLE001
        log.warning("malformed boundary in change stream %s", doc.get("_id"))
        return
    status = b.status if isinstance(b.status, str) else b.status.value
    if not boundary_change_is_news(change, status):
        return
    if status == "active":
        await emit("boundary.activated", None, b.model_dump(mode="json", by_alias=True), all_sessions=True)
    elif status == "proposed":
        await emit("boundary.proposed", None, b.model_dump(mode="json", by_alias=True), all_sessions=True)


async def _on_memory(change: dict[str, Any]) -> None:
    doc = change.get("fullDocument")
    if not doc:
        return
    await emit("memory.updated", None, {"person_id": doc.get("person_id"), "kind": doc.get("kind")},
               all_sessions=True)
