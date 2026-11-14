"""Lane A: WebSocket fan-out + change-stream tails. See docs/04-api-contracts.md §2."""
import logging
from collections import defaultdict

from fastapi import WebSocket

from app.contracts import WSMessage

log = logging.getLogger(__name__)

_connections: dict[str, set[WebSocket]] = defaultdict(set)


async def startup() -> None:
    """TODO(Lane A): if settings.use_change_streams, start asyncio tasks tailing
    suggestion_sets / boundaries / utterances / memories and call broadcast()."""
    return None


async def shutdown() -> None:
    return None


def register(session_id: str, ws: WebSocket) -> None:
    _connections[session_id].add(ws)


def unregister(session_id: str, ws: WebSocket) -> None:
    _connections[session_id].discard(ws)


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
