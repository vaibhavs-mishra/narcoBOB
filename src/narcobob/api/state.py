"""Process-wide state for the API: one DB connection, the cell grid, and in-memory caches."""

from __future__ import annotations

import sqlite3
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from narcobob.common.config import Settings
from narcobob.common.db import init_db, kv_get, kv_set
from narcobob.common.ids import iso, parse_ts
from narcobob.engine.cells import CellGrid

DEFAULT_EPOCH0 = "2026-01-01T00:00:00Z"


@dataclass
class AppState:
    settings: Settings
    conn: sqlite3.Connection
    grid: CellGrid
    epoch0: datetime
    # latest CellScore dict per cell (all cells), and the data_version it was computed at
    scores: dict[str, dict[str, object]] = field(default_factory=dict)
    scored_version: int = -1
    scored_bucket: int = -1
    # (wall monotonic time, events) per accepted ingest batch, for events/min
    ingest_log: deque[tuple[float, int]] = field(default_factory=deque)

    @classmethod
    def create(cls, settings: Settings) -> AppState:
        conn = init_db(settings.db_file)
        if kv_get(conn, "epoch0") is None:
            kv_set(conn, "epoch0", DEFAULT_EPOCH0)
            conn.commit()
        grid = CellGrid.from_bbox(settings.area_bbox, settings.h3_res)
        return cls(settings, conn, grid, parse_ts(kv_get(conn, "epoch0") or DEFAULT_EPOCH0))

    def bucket_of(self, ts: datetime) -> int:
        return int((ts - self.epoch0).total_seconds() // self.settings.bucket_sim_seconds)

    def bucket_start(self, bucket: int) -> str:
        return iso(self.epoch0 + timedelta(seconds=bucket * self.settings.bucket_sim_seconds))

    def sim_now(self) -> str | None:
        return kv_get(self.conn, "sim_now")

    def events_per_min(self) -> float:
        cutoff = time.monotonic() - 60
        while self.ingest_log and self.ingest_log[0][0] < cutoff:
            self.ingest_log.popleft()
        return float(sum(n for _, n in self.ingest_log))
