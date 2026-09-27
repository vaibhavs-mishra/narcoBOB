"""`narcobob-sim`: the simulator process and its control API (port NARCOBOB_SIM_PORT).

The API proxies `/api/sim/*` here; the UI never talks to the simulator directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

from narcobob.common.config import get_settings
from narcobob.common.logging import setup_logging
from narcobob.common.schemas import SimControl, SimStatus, SurgeRequest
from narcobob.simulator.streamer import Streamer

settings = get_settings()
streamer = Streamer(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.sim_autostart:
        streamer.start()
    yield
    streamer.pause()


app = FastAPI(title="NarcoBob simulator (SIMULATED data)", lifespan=lifespan)


@app.get("/sim/status", response_model=SimStatus)
async def status() -> dict[str, Any]:
    return streamer.status()


@app.post("/sim/start", response_model=SimStatus)
async def start(body: SimControl | None = None) -> dict[str, Any]:
    body = body or SimControl()
    try:
        streamer.start(body.scenario, body.seed)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"unknown scenario {body.scenario!r}") from exc
    return streamer.status()


@app.post("/sim/pause", response_model=SimStatus)
async def pause() -> dict[str, Any]:
    streamer.pause()
    return streamer.status()


@app.post("/sim/reset", response_model=SimStatus)
async def reset(body: SimControl | None = None) -> dict[str, Any]:
    body = body or SimControl()
    streamer.reset(body.scenario, body.seed)
    return streamer.status()


@app.post("/sim/surge", response_model=SimStatus)
async def surge(body: SurgeRequest) -> dict[str, Any]:
    try:
        streamer.surge(body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(404, f"unknown injection {exc}") from exc
    return streamer.status()


def run() -> None:
    setup_logging()
    uvicorn.run(app, host="127.0.0.1", port=settings.sim_port, log_level="warning")
