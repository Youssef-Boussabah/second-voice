"""Lane A: WebSocket endpoint /ws?session_id=..."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime import hub

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await ws.accept()
    hub.register(session_id, ws)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(session_id, ws)
