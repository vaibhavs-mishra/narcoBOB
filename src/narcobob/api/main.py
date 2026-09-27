"""`narcobob-api`: REST + WebSocket server and the real-time loops (SPEC §7).

Background tasks started with the app:
- scoring loop: rescore when new data arrives, broadcast changed cells, raise alerts
- coalescer: batch fresh alerts into one agent run and queue it
- orchestrator worker: runs the four agents for each queued run
- heartbeat
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import shutil
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from narcobob.api import queries
from narcobob.api.alerts import AlertEngine, create_run
from narcobob.api.ingest import ingest
from narcobob.api.scoring import cell_score_dicts, persist_scores, score_now
from narcobob.api.state import AppState
from narcobob.api.ws import Hub
from narcobob.common.config import SRC_DIR, get_settings
from narcobob.common.db import data_version
from narcobob.common.logging import setup_logging
from narcobob.common.schemas import IngestResult, SimControl, SurgeRequest
from narcobob.orchestrator.worker import Worker

log = logging.getLogger(__name__)
settings = get_settings()
state = AppState.create(settings)
hub = Hub(SRC_DIR / "recordings" if settings.record else None)
alert_engine = AlertEngine()
worker = Worker(state, hub)
SIM = f"http://127.0.0.1:{settings.sim_port}"
OFFLINE_SIM = {"running": False, "scenario": settings.scenario, "seed": settings.seed,
               "sim_now": None, "speed": 0.0, "injections": []}  # fmt: skip


# ── background loops ─────────────────────────────────────────────────────────


async def score_once() -> None:
    scored = score_now(state)
    if scored is None:
        return
    result, bucket = scored
    fresh = cell_score_dicts(state, result, bucket)
    changed = [
        s for cell, s in fresh.items()
        if (old := state.scores.get(cell)) is None
        or abs(int(str(old["score"])) - int(str(s["score"]))) >= 1
        or old["severity"] != s["severity"]
    ]  # fmt: skip
    state.scores = fresh
    if changed:
        persist_scores(state, changed)
        verdicts = queries.latest_verdicts(state)
        payload = [queries.with_verdict(s, verdicts) for s in changed]
        await hub.broadcast("scores.update", {"cells": payload, "kpis": queries.kpis(state)})
    for alert in alert_engine.check(state, fresh):
        await hub.broadcast("alert.raised", alert)


async def scoring_loop() -> None:
    while True:
        try:
            await score_once()
            batch = alert_engine.take_batch(state)
            if batch:
                run = create_run(state, batch, data_version(state.conn))
                await hub.broadcast("run.queued", run)
                worker.enqueue(str(run["run_id"]))
        except Exception:
            log.exception("scoring loop error")
        await asyncio.sleep(settings.score_interval_s)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    tasks = [
        asyncio.create_task(scoring_loop()),
        asyncio.create_task(hub.heartbeat()),
        asyncio.create_task(worker.run_forever()),
    ]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="NarcoBob API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── ingest ───────────────────────────────────────────────────────────────────


async def _ingest(events: list[dict[str, Any]]) -> IngestResult:
    result, pings = ingest(state, events)
    if pings:
        await hub.broadcast("event.batch", {"events": pings, "count": result.accepted})
    return result


@app.post("/api/ingest", response_model=IngestResult)
async def ingest_json(body: dict[str, Any]) -> IngestResult:
    events = body.get("events")
    if not isinstance(events, list):
        raise HTTPException(422, "body must be {events: Event[]}")
    if len(events) > 5000:
        raise HTTPException(413, "at most 5,000 events per request")
    return await _ingest(events)


@app.post("/api/ingest/csv", response_model=IngestResult)
async def ingest_csv(file: UploadFile) -> IngestResult:
    """Bring your own data: a CSV whose header uses the Event field names."""
    text = (await file.read()).decode("utf-8-sig")
    events: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        event: dict[str, Any] = {k: v for k, v in row.items() if v not in (None, "")}
        for key in ("lat", "lon", "quantity_g"):
            if key in event:
                event[key] = float(event[key])
        if "meta" in event:
            event["meta"] = json.loads(event["meta"])
        events.append(event)
    return await _ingest(events[:5000])  # each row is validated and rejected individually


# ── read API ─────────────────────────────────────────────────────────────────


async def sim_status() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{SIM}/sim/status")
            r.raise_for_status()
            return dict(r.json())
    except httpx.HTTPError:
        return OFFLINE_SIM


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


@app.get("/api/health")
def health() -> dict[str, Any]:
    mcp = _port_open(settings.mcp_port)
    if settings.agents_mode == "fallback":
        bob = "disabled"
    else:
        bob = "ok" if shutil.which(settings.bob_bin) and settings.bob_api_key else "unavailable"
    return {"ok": True, "api": True, "mcp": mcp, "bob": bob, "mode": "live"}


@app.get("/api/state")
async def get_state() -> dict[str, Any]:
    return queries.snapshot(state, await sim_status(), hub.seq)


@app.get("/api/cells/{cell}")
def get_cell(cell: str) -> dict[str, Any]:
    detail = queries.cell_detail(state, cell)
    if detail is None:
        raise HTTPException(404, "cell not in the monitored area")
    return detail


@app.get("/api/cells/{cell}/timeseries")
def get_timeseries(
    cell: str, types: str = "overdose,seizure,arrest", buckets: int = Query(28, ge=1, le=60)
) -> dict[str, Any]:
    return queries.timeseries(state, cell, types.split(","), buckets)


@app.get("/api/alerts")
def get_alerts(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return queries.alert_rows(state, limit)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = queries.full_run(state, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/api/reports/{run_id}")
def get_report(run_id: str) -> dict[str, Any]:
    report = queries.report(state, run_id)
    if report is None:
        raise HTTPException(404, "no report for this run yet")
    return report


@app.get("/api/backtest/latest")
def backtest_latest() -> dict[str, Any]:
    files = sorted(
        (SRC_DIR / "recordings").glob("backtest_*.json"), key=lambda p: p.stat().st_mtime
    )
    if not files:
        raise HTTPException(404, "run `make backtest` first")
    return dict(json.loads(files[-1].read_text()))


@app.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    await hub.serve(ws, "live")


# ── simulator proxy ──────────────────────────────────────────────────────────


async def _proxy(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{SIM}/sim/{path}", json=body or {})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "simulator is not running") from exc
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", "simulator error"))
    status = dict(r.json())
    await hub.broadcast("sim.status", status)
    return status


@app.get("/api/sim/status")
async def sim_status_route() -> dict[str, Any]:
    return await sim_status()


@app.post("/api/sim/start")
async def sim_start(body: SimControl | None = None) -> dict[str, Any]:
    return await _proxy("start", (body or SimControl()).model_dump(exclude_none=True))


@app.post("/api/sim/pause")
async def sim_pause() -> dict[str, Any]:
    return await _proxy("pause")


@app.post("/api/sim/reset")
async def sim_reset(body: SimControl | None = None) -> dict[str, Any]:
    """Reset the simulator AND clear all derived data, so the next start is a clean run."""
    status = await _proxy("reset", (body or SimControl()).model_dump(exclude_none=True))
    for table in ("events", "cell_scores", "alerts", "findings", "reports", "tool_calls",
                  "agent_steps", "agent_runs"):  # fmt: skip
        state.conn.execute(f"DELETE FROM {table}")
    state.conn.execute("DELETE FROM kv WHERE key = 'sim_now'")
    state.conn.execute("UPDATE kv SET value = '0' WHERE key = 'data_version'")
    state.conn.commit()
    state.scores.clear()
    state.scored_version = state.scored_bucket = -1
    alert_engine.reset()
    return status


@app.post("/api/sim/surge")
async def sim_surge(body: SurgeRequest) -> dict[str, Any]:
    return await _proxy("surge", body.model_dump(exclude_none=True))


def run() -> None:
    setup_logging()
    uvicorn.run(app, host="127.0.0.1", port=settings.api_port, log_level="warning")
