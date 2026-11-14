// Auto-reconnecting WebSocket (backoff 0.5 s → 5 s). Calls onReconnect after every re-open
// so the app can fetch /api/sessions/{id}/latest and catch up.
import type { WSMessage } from "../contracts";

export interface WsHandle {
  close(): void;
}

interface Callbacks {
  onMessage: (m: WSMessage) => void;
  onStatus: (s: "connecting" | "open" | "closed") => void;
  onReconnect: () => void;
}

export function connectReconnecting(url: string, cb: Callbacks): WsHandle {
  let ws: WebSocket | null = null;
  let delay = 500;
  let stopped = false;
  let opened = false;
  let retry: number | undefined;
  let ping: number | undefined;

  const open = () => {
    if (stopped) return;
    cb.onStatus("connecting");
    ws = new WebSocket(url);
    ws.onopen = () => {
      cb.onStatus("open");
      if (opened) cb.onReconnect();
      opened = true;
      delay = 500;
      ping = window.setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, 20000);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(String(ev.data)) as WSMessage;
        if (msg && typeof msg.type === "string") cb.onMessage(msg);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      window.clearInterval(ping);
      if (stopped) return;
      cb.onStatus("closed");
      retry = window.setTimeout(open, delay);
      delay = Math.min(delay * 2, 5000);
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return {
    close() {
      stopped = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      ws?.close();
    },
  };
}
