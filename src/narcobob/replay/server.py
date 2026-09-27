"""`narcobob-replay`: serve a recorded real run as if it were live (SPEC §10, demo insurance).

Streams `NARCOBOB_REPLAY_FILE` (WebSocket messages recorded by the live API) at the
original timing, looping forever, on the same `/ws` + `/api/state` interface, so the
frontend cannot tell the difference except for the REPLAY badge. REST lookups (cell
drawer, briefs) are answered from the SQLite snapshot saved next to the recording
(`<name>.db`, written by `scripts/save_recording.py`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from narcobob.api import queries
from narcobob.api.state import AppState
from narcobob.common.config import get_settings, public_config
from narcobob.common.ids import wall_now
from narcobob.common.logging import setup_logging

log = logging.getLogger(__name__)
settings = get_settings()
RECORDING = settings.resolve(settings.replay_file)
SNAPSHOT_DB = RECORDING.with_suffix(".db")
LOOP_PAUSE_S = 10.0
MAX_GAP_S = 20.0  # long idle stretches in the recording are shortened to this


class Player:
    """Plays the recording to all clients and keeps a folded snapshot of what was played."""

    def __init__(self, path: Path, speed: float) -> None:
        self.frames = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.speed = speed
        self.clients: set[WebSocket] = set()
        self.seq = 0
        self.reset_fold()

    def reset_fold(self) -> None:
        self.cells: dict[str, dict[str, Any]] = {}
        self.alerts: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.kpis: dict[str, Any] | None = None
        self.sim: dict[str, Any] = {
            "running": True,
            "scenario": "recording",
            "seed": 0,
            "sim_now": None,
            "speed": 0.0,
            "injections": [],
        }

    def fold(self, msg: dict[str, Any]) -> None:
        kind, p = msg["type"], msg["payload"]
        if kind == "scores.update":
            self.cells.update({c["cell"]: c for c in p["cells"]})
            self.kpis = p["kpis"]
        elif kind in ("alert.raised", "alert.updated"):
            self.alerts[p["alert_id"]] = p
        elif kind in ("run.queued", "run.started", "run.finished"):
            self.runs[p["run_id"]] = p
        elif kind == "sim.status":
            self.sim = p

    def snapshot(self) -> dict[str, Any]:
        alerts = sorted(self.alerts.values(), key=lambda a: a["wall_created_at"], reverse=True)
        runs = sorted(self.runs.values(), key=lambda r: r["run_id"], reverse=True)
        cells = [c for c in self.cells.values() if c["severity"] != "NORMAL" or c["score"] >= 40]
        kpis = self.kpis or {
            "events_per_min": 0,
            "active_alerts": 0,
            "cells_monitored": 0,
            "cells_elevated": 0,
            "sim_now": None,
            "data_version": 0,
        }
        return {
            "config": public_config(settings),
            "sim": self.sim,
            "kpis": kpis,
            "cells": cells,
            "alerts": alerts[:50],
            "runs": runs[:10],
            "seq": self.seq,
        }

    async def send(self, msg: dict[str, Any]) -> None:
        text = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)

    async def play_forever(self) -> None:
        while True:
            self.reset_fold()
            await self.send(
                {
                    "type": "hello",
                    "seq": self.seq,
                    "wall_ts": wall_now(),
                    "payload": {"server_session": "replay", "mode": "replay", "seq": self.seq},
                }
            )
            last_t = 0.0
            for frame in self.frames:
                gap = min(MAX_GAP_S, max(0.0, frame["t"] - last_t)) / self.speed
                last_t = frame["t"]
                if gap:
                    await asyncio.sleep(gap)
                self.seq += 1
                msg = dict(frame["msg"], seq=self.seq, wall_ts=wall_now())
                self.fold(msg)
                await self.send(msg)
            await asyncio.sleep(LOOP_PAUSE_S)


player: Player | None = None
db_state: AppState | None = None


def _db() -> AppState:
    if db_state is None:
        raise HTTPException(404, f"no snapshot database next to the recording ({SNAPSHOT_DB.name})")
    return db_state


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global player, db_state
    if not RECORDING.exists():
        raise SystemExit(f"recording not found: {RECORDING} (see docs/setup-guide.md)")
    player = Player(RECORDING, settings.replay_speed)
    if SNAPSHOT_DB.exists():
        db_state = AppState.create(settings.model_copy(update={"db_path": SNAPSHOT_DB}))
        for row in db_state.conn.execute("SELECT * FROM cell_scores"):
            from narcobob.harness.data import score_row_to_dict

            db_state.scores[row["cell"]] = score_row_to_dict(row)
        last = db_state.conn.execute("SELECT MAX(bucket) FROM events").fetchone()[0]
        db_state.scored_bucket = int(last or 0) - 1
    task = asyncio.create_task(player.play_forever())
    log.info("replaying", extra={"file": RECORDING.name, "frames": len(player.frames)})
    yield
    task.cancel()


app = FastAPI(title="NarcoBob replay", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "api": True, "mcp": False, "bob": "disabled", "mode": "replay"}


@app.get("/api/state")
def state() -> dict[str, Any]:
    assert player is not None
    return player.snapshot()


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    assert player is not None
    await socket.accept()
    player.clients.add(socket)
    await socket.send_text(
        json.dumps(
            {
                "type": "hello",
                "seq": player.seq,
                "wall_ts": wall_now(),
                "payload": {"server_session": "replay", "mode": "replay", "seq": player.seq},
            }
        )
    )
    try:
        while True:
            await socket.receive_text()
    except Exception:
        pass
    finally:
        player.clients.discard(socket)


@app.get("/api/cells/{cell}")
def cell(cell: str) -> dict[str, Any]:
    detail = queries.cell_detail(_db(), cell)
    if detail is None:
        raise HTTPException(404, "cell not in the recording")
    return detail


@app.get("/api/cells/{cell}/timeseries")
def timeseries(
    cell: str, types: str = "overdose,seizure,arrest", buckets: int = Query(28, ge=1, le=60)
) -> dict[str, Any]:
    return queries.timeseries(_db(), cell, types.split(","), buckets)


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    found = queries.full_run(_db(), run_id)
    if found is None:
        raise HTTPException(404, "run not found")
    return found


@app.get("/api/reports/{run_id}")
def report(run_id: str) -> dict[str, Any]:
    found = queries.report(_db(), run_id)
    if found is None:
        raise HTTPException(404, "no report for this run")
    return found


@app.post("/api/sim/{action}")
def sim_disabled(action: str) -> None:
    raise HTTPException(409, f"'{action}' is not available in replay mode")


def run() -> None:
    setup_logging()
    uvicorn.run(app, host="127.0.0.1", port=settings.api_port, log_level="warning")
