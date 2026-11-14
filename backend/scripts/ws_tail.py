"""Lane A acceptance helper: start a session, send a text utterance, print WS messages.

    cd backend && python scripts/ws_tail.py --person per_dana --text "Hi Maya, here for your refill?"
    python scripts/ws_tail.py --session ses_x          # just tail an existing session
"""
import argparse
import asyncio
import json
import time

import httpx
import websockets


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--session")
    ap.add_argument("--person", default="per_dana")
    ap.add_argument("--text", default="Hi Maya, here for your refill?")
    ap.add_argument("--seconds", type=float, default=15)
    a = ap.parse_args()

    async with httpx.AsyncClient(base_url=a.base, timeout=10) as http:
        sid = a.session or (await http.post("/api/sessions", json={"person_id": a.person})).json()["_id"]
        print("session", sid)
        ws_url = a.base.replace("http", "ws", 1) + f"/ws?session_id={sid}"
        async with websockets.connect(ws_url) as ws:
            t0 = time.perf_counter()
            if not a.session:
                r = await http.post("/api/utterances/text", json={"session_id": sid, "text": a.text})
                print("utterance", r.status_code, r.json()["utterance"]["_id"])
            try:
                while time.perf_counter() - t0 < a.seconds:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=a.seconds))
                    dt = int((time.perf_counter() - t0) * 1000)
                    if msg["type"] == "suggestions.ready":
                        d = msg["data"]
                        print(f"[{dt}ms] suggestions.ready stage={d['stage']} latency={d['latency_ms']}")
                        for c in d["candidates"]:
                            print(f"    ✓ {c['text']}  {c['topics']}  {c['memory_ids']}")
                        for c in d["blocked"]:
                            print(f"    🔒 {c['text']}  {c['topics']}  by={c['blocked_by']}")
                        if d["stage"] == "final" and not a.session:
                            break
                    else:
                        print(f"[{dt}ms] {msg['type']}: {json.dumps(msg['data'])[:200]}")
            except asyncio.TimeoutError:
                print("timeout")


if __name__ == "__main__":
    asyncio.run(main())
