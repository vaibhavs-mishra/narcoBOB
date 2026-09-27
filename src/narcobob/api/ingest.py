"""`POST /api/ingest`: validate, dedupe, place in the grid, store. Idempotent on event_id."""

from __future__ import annotations

import json
import random
import time
from typing import Any

import h3
from pydantic import ValidationError

from narcobob.api.state import AppState
from narcobob.common.db import data_version, kv_get, kv_set
from narcobob.common.ids import iso, parse_ts, wall_now
from narcobob.common.schemas import Event, IngestResult, Rejection

MAX_PINGS = 200  # events sampled into one `event.batch` WebSocket message
LIVE_BATCH_MAX = 1000  # larger batches are backfill: stored, but not pinged on the map


def ingest(
    state: AppState, raw_events: list[dict[str, Any]]
) -> tuple[IngestResult, list[dict[str, Any]]]:
    """Store valid new events. Returns the result and a sample of events for map pings."""
    lat_min, lon_min, lat_max, lon_max = state.settings.area_bbox
    rejected: list[Rejection] = []
    rows: list[tuple[Any, ...]] = []
    seen: set[str] = set()
    now = wall_now()
    max_ts: str | None = kv_get(state.conn, "sim_now")

    for raw in raw_events:
        try:
            event = Event.model_validate(raw)
        except ValidationError as exc:
            reason = exc.errors()[0]
            rejected.append(
                Rejection(
                    event_id=str(raw.get("event_id", "?")),
                    reason=f"VALIDATION_ERROR: {'.'.join(str(p) for p in reason['loc'])}",
                )
            )
            continue
        if not (lat_min <= event.lat <= lat_max and lon_min <= event.lon <= lon_max):
            rejected.append(Rejection(event_id=event.event_id, reason="OUT_OF_AREA"))
            continue
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        ts = iso(event.ts)
        rows.append(
            (
                event.event_id, event.type, event.lat, event.lon,
                h3.latlng_to_cell(event.lat, event.lon, state.settings.h3_res), ts,
                state.bucket_of(event.ts), event.source, event.quantity_g, event.substance,
                json.dumps(event.meta) if event.meta else None, now,
            )
        )  # fmt: skip
        if max_ts is None or ts > max_ts:
            max_ts = ts

    before = state.conn.total_changes
    state.conn.executemany(
        "INSERT OR IGNORE INTO events(event_id, type, lat, lon, cell, ts, bucket, source,"
        " quantity_g, substance, meta, wall_ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    accepted = state.conn.total_changes - before
    version = data_version(state.conn)
    if accepted:
        version += 1
        kv_set(state.conn, "data_version", str(version))
        if max_ts is not None:
            kv_set(state.conn, "sim_now", max_ts)
    state.conn.commit()

    duplicates = len(raw_events) - len(rejected) - accepted
    _count_quality(state, rows, duplicates)
    if accepted:
        state.ingest_log.append((time.monotonic(), accepted))
    pings: list[dict[str, Any]] = []
    if 0 < len(rows) <= LIVE_BATCH_MAX:
        sample = rows if len(rows) <= MAX_PINGS else random.sample(rows, MAX_PINGS)
        pings = [{"type": r[1], "cell": r[4], "lat": r[2], "lon": r[3], "ts": r[5]} for r in sample]
    return IngestResult(accepted=accepted, duplicates=duplicates, rejected=rejected,
                        data_version=version), pings  # fmt: skip


def _count_quality(state: AppState, rows: list[tuple[Any, ...]], duplicates: int) -> None:
    """Running totals for the Steward: duplicate deliveries, and late events (arriving after
    their sim-day had already closed)."""
    sim_now = kv_get(state.conn, "sim_now")
    late = 0
    if sim_now is not None and len(rows) <= LIVE_BATCH_MAX:
        closed = state.bucket_of(parse_ts(sim_now)) - 1
        late = sum(1 for r in rows if r[6] < closed)
    for key, n in (("duplicates_total", duplicates), ("late_events_total", late)):
        if n:
            kv_set(state.conn, key, str(int(kv_get(state.conn, key) or 0) + n))
    state.conn.commit()
