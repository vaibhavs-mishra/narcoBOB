"""Feeds generated events into the API as if they were arriving live.

1. Backfill: POST the first `backfill_buckets` sim-days in bulk, so every window is full.
2. Live: a sim clock runs at `sim_seconds_per_wall_second`; every tick, all events whose
   timestamp has passed are POSTed to `/api/ingest`.
The API never sees the generator, only events, exactly as with a real feed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

from narcobob.common.config import Settings
from narcobob.common.ids import iso, parse_ts
from narcobob.engine.cells import CellGrid
from narcobob.simulator.generator import Generator
from narcobob.simulator.scenario import InjectionSpec, Scenario, load_scenario

log = logging.getLogger(__name__)

TICK_S = 0.5
BATCH = 5000


class Streamer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.api = f"http://127.0.0.1:{settings.api_port}"
        self.speed = settings.sim_seconds_per_wall_second
        self._task: asyncio.Task[None] | None = None
        self._load(settings.scenario, settings.seed)

    def _load(self, scenario_name: str, seed: int) -> None:
        self.scenario_name = scenario_name
        self.seed = seed
        self.scenario: Scenario = load_scenario(
            self.settings.scenario_file.parent / f"{scenario_name}.yaml"
        )
        grid = CellGrid.from_bbox(self.scenario.area.bbox, self.scenario.area.h3_res)
        self.gen = Generator(self.scenario, grid, seed)
        self.backfilled = False
        self.running = False
        self.sim_now: datetime | None = None
        self._pending: list[dict[str, Any]] = []  # today's events not yet sent
        self._pending_day = -1
        self._live_surges = 0

    # ── status ───────────────────────────────────────────────────────────────

    @property
    def day(self) -> int:
        return 0 if self.sim_now is None else self.gen.day_of(self.sim_now)

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "scenario": self.scenario_name,
            "seed": self.seed,
            "sim_now": None if self.sim_now is None else iso(self.sim_now),
            "speed": self.speed,
            "injections": self.gen.injection_status(self.day),
        }

    # ── control ──────────────────────────────────────────────────────────────

    def start(self, scenario: str | None = None, seed: int | None = None) -> None:
        if (scenario and scenario != self.scenario_name) or (
            seed is not None and seed != self.seed
        ):
            self.reset(scenario or self.scenario_name, self.seed if seed is None else seed)
        self.running = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def pause(self) -> None:
        self.running = False

    def reset(self, scenario: str | None = None, seed: int | None = None) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._load(scenario or self.scenario_name, self.seed if seed is None else seed)

    def surge(self, body: dict[str, Any]) -> None:
        """Start a surge tomorrow (sim time): a scenario injection id, or an ad-hoc surge."""
        start_day = self.day + 1
        injection_id = body.get("injection_id")
        if injection_id:
            self.gen.inject(str(injection_id), start_day)
            return
        self._live_surges += 1
        spec = InjectionSpec(
            id=f"LIVE{self._live_surges}",
            kind="surge",
            at_day=start_day,
            lat=float(body["lat"]),
            lon=float(body["lon"]),
            radius_cells=int(body.get("radius_cells", 1)),
            types=list(body.get("types", ["overdose"])),
            multiplier=float(body.get("multiplier", 3.0)),
            ramp_days=int(body.get("ramp_days", 5)),
        )
        self.gen.inject_spec(spec, start_day)

    # ── the loop ─────────────────────────────────────────────────────────────

    async def _post(self, client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
        for i in range(0, len(events), BATCH):
            chunk = events[i : i + BATCH]
            for attempt in range(30):
                try:
                    r = await client.post(f"{self.api}/api/ingest", json={"events": chunk})
                    r.raise_for_status()
                    break
                except httpx.HTTPError as exc:
                    if attempt == 29:
                        raise
                    log.warning("ingest failed, retrying", extra={"error": str(exc)})
                    await asyncio.sleep(1.0)

    async def _backfill(self, client: httpx.AsyncClient) -> None:
        days = self.settings.backfill_buckets
        events: list[dict[str, Any]] = []
        for day in range(days):
            events.extend(self.gen.events_for_day(day))
        await self._post(client, events)
        self.sim_now = self.gen.day_start(days)
        self.backfilled = True
        log.info("backfill done", extra={"days": days, "events": len(events)})

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if not self.backfilled:
                await self._backfill(client)
            last = time.monotonic()
            while True:
                await asyncio.sleep(TICK_S)
                now = time.monotonic()
                elapsed, last = now - last, now
                if not self.running or self.sim_now is None:
                    continue
                self.sim_now += timedelta(seconds=elapsed * self.speed)
                due = self._due_events(self.sim_now)
                if due:
                    await self._post(client, due)

    def _due_events(self, sim_now: datetime) -> list[dict[str, Any]]:
        """Every event with ts ≤ sim_now, generating each new sim-day as the clock reaches it."""
        due: list[dict[str, Any]] = []
        today = self.gen.day_of(sim_now)
        while self._pending_day < today:
            if self._pending_day < 0:
                self._pending_day = self.settings.backfill_buckets - 1
            self._pending_day += 1
            self._pending.extend(self.gen.events_for_day(self._pending_day))
        while self._pending and parse_ts(self._pending[0]["ts"]) <= sim_now:
            due.append(self._pending.pop(0))
        return due
