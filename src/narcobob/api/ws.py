"""WebSocket hub: every live update goes out through `broadcast`, stamped with a `seq`.

Clients fetch `GET /api/state` first, then apply deltas; a gap in `seq` means they missed
something and should refetch. Every message is also appended to a JSONL recording
(with its wall-clock offset), which `make replay` can serve later.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from narcobob.common.ids import new_id, wall_now

log = logging.getLogger(__name__)
HEARTBEAT_S = 10


class Hub:
    def __init__(self, recording_dir: Path | None) -> None:
        self.session = new_id()
        self.seq = 0
        self.clients: set[WebSocket] = set()
        self.started = time.monotonic()
        self.recording: Path | None = None
        if recording_dir is not None:
            recording_dir.mkdir(parents=True, exist_ok=True)
            self.recording = recording_dir / f"session_{self.session}.jsonl"

    def envelope(self, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        return {"type": type_, "seq": self.seq, "wall_ts": wall_now(), "payload": payload}

    async def broadcast(self, type_: str, payload: dict[str, Any]) -> None:
        message = self.envelope(type_, payload)
        text = json.dumps(message, default=str)
        if self.recording is not None and type_ != "heartbeat":
            offset = round(time.monotonic() - self.started, 3)
            with self.recording.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": offset, "msg": message}, default=str) + "\n")
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:  # a closed socket must never break the broadcast
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def serve(self, ws: WebSocket, mode: str = "live") -> None:
        await ws.accept()
        self.clients.add(ws)
        payload = {"server_session": self.session, "mode": mode, "seq": self.seq}
        hello = {"type": "hello", "seq": self.seq, "wall_ts": wall_now(), "payload": payload}
        await ws.send_text(json.dumps(hello))
        try:
            while True:
                await ws.receive_text()  # clients only listen; this detects disconnects
        except Exception:
            pass
        finally:
            self.clients.discard(ws)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await self.broadcast("heartbeat", {})
