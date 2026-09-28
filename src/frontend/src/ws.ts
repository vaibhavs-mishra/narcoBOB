// WebSocket client: snapshot first, then deltas. A gap in `seq` triggers a snapshot refetch.
import { api, WS_URL } from "./api";
import type { WsMessage } from "./contracts";
import { useStore } from "./store";

let socket: WebSocket | null = null;
let retry = 0;
let stopped = false;

async function refetch(): Promise<void> {
  try {
    useStore.getState().applySnapshot(await api.state());
  } catch {
    /* the reconnect loop will try again */
  }
}

export function connect(): () => void {
  stopped = false;
  open();
  return () => {
    stopped = true;
    socket?.close();
  };
}

function open(): void {
  const ws = new WebSocket(WS_URL);
  socket = ws;
  ws.onopen = () => {
    retry = 0;
    useStore.getState().setConnected(true);
    void refetch();
  };
  ws.onmessage = (ev: MessageEvent<string>) => {
    if (ws !== socket) return; // a superseded socket still draining
    const msg = JSON.parse(ev.data) as WsMessage;
    const { seq } = useStore.getState();
    if (msg.type === "hello") {
      // a new server session (or a replay loop restarting): resync from the snapshot
      useStore.getState().applyMessage(msg);
      void refetch();
      return;
    }
    if (seq && msg.seq <= seq) return; // already applied (or already in the snapshot)
    if (seq && msg.seq > seq + 1) {
      void refetch(); // missed messages: resync from the snapshot
      return;
    }
    useStore.getState().applyMessage(msg);
  };
  ws.onclose = () => {
    if (ws !== socket) return; // only the current socket reconnects
    useStore.getState().setConnected(false);
    if (stopped) return;
    const delay = Math.min(10_000, 500 * 2 ** retry++);
    setTimeout(open, delay);
  };
}
