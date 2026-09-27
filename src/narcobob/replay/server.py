"""`narcobob-replay`: serve a recorded real run as if it were live (SPEC §10, demo insurance).

Streams `NARCOBOB_REPLAY_FILE` (WebSocket messages recorded by the live API) at the
original timing, looping forever, on the same `/ws` + `/api/state` interface, so the
frontend cannot tell the difference except for the REPLAY badge. REST lookups (cell
drawer, briefs) are answered from the SQLite snapshot saved next to the recording
(`<name>.db`, written by `scripts/save_recording.py`).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from narcobob.api import queries
from narcobob.api.state import AppState
from narcobob.common.config import get_settings, public_config
from narcobob.common.ids import iso, parse_ts, wall_now
from narcobob.common.logging import setup_logging

log = logging.getLogger(__name__)
settings = get_settings()
RECORDING = settings.resolve(settings.replay_file)
# demo_golden.jsonl.gz → demo_golden.db.gz (either may be gzipped or plain)
_STEM = RECORDING.name.removesuffix(".gz").removesuffix(".jsonl")
SNAPSHOT_DB = next(
    (
        p
        for p in (RECORDING.parent / f"{_STEM}.db.gz", RECORDING.parent / f"{_STEM}.db")
        if p.exists()
    ),
    RECORDING.parent / f"{_STEM}.db.gz",
)


def _open_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def _local_db(path: Path) -> Path:
    """The snapshot as a plain SQLite file (decompressed into var/ if gzipped)."""
    if path.suffix != ".gz":
        return path
    out = settings.resolve(Path("var")) / f"replay_{_STEM}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "rb") as src, out.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return out


LOOP_PAUSE_S = 10.0
MAX_GAP_S = 20.0  # long idle stretches in the recording are shortened to this


class Player:
    """Plays the recording to all clients and keeps a folded snapshot of what was played."""

    def __init__(self, path: Path, speed: float) -> None:
        self.frames = [json.loads(line) for line in _open_text(path).splitlines() if line.strip()]
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

    @staticmethod
    def _shift(value: Any, delta: timedelta, speed: float, origin: datetime) -> Any:
        """Move recorded wall-clock times (keys starting `wall_`) to 'now', compressing
        them by the replay speed so ages and durations look right."""
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if k.startswith("wall_") and isinstance(v, str) and v.endswith("Z"):
                    t = parse_ts(v)
                    out[k] = iso(origin + (t - origin) / speed + delta)
                else:
                    out[k] = Player._shift(v, delta, speed, origin)
            return out
        if isinstance(value, list):
            return [Player._shift(v, delta, speed, origin) for v in value]
        return value

    async def _link_alerts(self, run_id: str, delta: timedelta, origin: datetime) -> None:
        """Recordings made before runs announced their alerts: link them from the snapshot
        DB (verdicts blanked; they arrive later in the recording with the Skeptic)."""
        if db_state is None:
            return
        rows = db_state.conn.execute("SELECT * FROM alerts WHERE run_id = ?", (run_id,)).fetchall()
        for row in rows:
            alert = self._shift(
                dict(row) | {"final_severity": None, "verdict": None}, delta, self.speed, origin
            )
            if alert["alert_id"] in self.alerts and self.alerts[alert["alert_id"]].get("verdict"):
                continue
            self.seq += 1
            msg = {
                "type": "alert.updated",
                "seq": self.seq,
                "wall_ts": wall_now(),
                "payload": alert,
            }
            self.fold(msg)
            await self.send(msg)

    async def play_forever(self) -> None:
        origin = parse_ts(self.frames[0]["msg"]["wall_ts"]) if self.frames else datetime.now(UTC)
        while True:
            self.reset_fold()
            delta = datetime.now(UTC) - origin
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
                payload = self._shift(frame["msg"]["payload"], delta, self.speed, origin)
                msg = dict(frame["msg"], payload=payload, seq=self.seq, wall_ts=wall_now())
                self.fold(msg)
                await self.send(msg)
                if msg["type"] == "run.queued":
                    await self._link_alerts(str(msg["payload"]["run_id"]), delta, origin)
            await asyncio.sleep(LOOP_PAUSE_S)


player: Player | None = None
db_state: AppState | None = None


def _db() -> AppState:
    """The snapshot database, with scores recomputed as of the replay's current sim time,
    so the cell drawer matches what the map shows at this point of the recording."""
    if db_state is None:
        raise HTTPException(404, f"no snapshot database next to the recording ({SNAPSHOT_DB.name})")
    sim_now = (player.kpis or {}).get("sim_now") if player is not None else None
    if sim_now:
        from narcobob.harness.data import scores_at

        bucket = db_state.bucket_of(parse_ts(sim_now)) - 1
        if bucket != db_state.scored_bucket:
            db_state.scores = scores_at(db_state.conn, db_state.settings, bucket)
            db_state.scored_bucket = bucket
    return db_state


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global player, db_state
    if not RECORDING.exists():
        raise SystemExit(f"recording not found: {RECORDING} (see docs/setup-guide.md)")
    player = Player(RECORDING, settings.replay_speed)
    if SNAPSHOT_DB.exists():
        db_state = AppState.create(settings.model_copy(update={"db_path": _local_db(SNAPSHOT_DB)}))
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
    if detail is None or player is None:
        raise HTTPException(404, "cell not in the recording")
    # Reveal only what the replay has played so far: the snapshot DB knows the future.
    played = sorted(
        (a for a in player.alerts.values() if a["cell"] == cell),
        key=lambda a: a["wall_created_at"],
        reverse=True,
    )
    judged = next((a for a in played if a.get("verdict")), None)
    detail["alerts"] = played[:20]
    detail["final_severity"] = judged["final_severity"] if judged else None
    detail["verdict"] = judged["verdict"] if judged else None
    if judged is None:
        detail["latest_verdict"] = None
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
