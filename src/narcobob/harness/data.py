"""Shared reads for the harness tools: scores, counts and time buckets straight from SQLite.

The MCP server is its own process, so it reads what the API persisted (cell_scores,
events) rather than any in-memory state.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

import h3

from narcobob.common.config import Settings
from narcobob.common.db import kv_get
from narcobob.common.ids import parse_ts
from narcobob.harness.errors import ToolFailure

DRIVERS = ("accel", "div", "spill", "gi")
Z_COLUMNS = {"accel": "z_accel", "div": "z_div", "spill": "z_spill", "gi": "gi_star"}
C_COLUMNS = {"accel": "c_accel", "div": "c_div", "spill": "c_spill", "gi": "c_gi"}
RECENT = 7


def last_complete_bucket(conn: sqlite3.Connection, settings: Settings) -> int:
    sim_now = kv_get(conn, "sim_now")
    epoch0 = kv_get(conn, "epoch0")
    if sim_now is None or epoch0 is None:
        raise ToolFailure("NOT_FOUND", "no data ingested yet")
    delta: float = (parse_ts(sim_now) - parse_ts(epoch0)).total_seconds()
    return int(delta // settings.bucket_sim_seconds) - 1


def bucket_start(conn: sqlite3.Connection, settings: Settings, bucket: int) -> datetime:
    epoch0 = parse_ts(kv_get(conn, "epoch0") or "2026-01-01T00:00:00Z")
    return datetime.fromtimestamp(
        epoch0.timestamp() + bucket * settings.bucket_sim_seconds, epoch0.tzinfo
    )


def check_cells(cells: list[str], limit: int = 50) -> list[str]:
    if not cells:
        raise ToolFailure("VALIDATION_ERROR", "cells must not be empty")
    if len(cells) > limit:
        raise ToolFailure("VALIDATION_ERROR", f"at most {limit} cells per call")
    for c in cells:
        if not isinstance(c, str) or not h3.is_valid_cell(c):
            raise ToolFailure("VALIDATION_ERROR", f"{c!r} is not a valid H3 cell")
    return cells


def score_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "cell": row["cell"],
        "score": row["score"],
        "severity": row["severity"],
        "confidence": row["confidence"],
        "support": row["support"],
        "components": {d: {"z": row[Z_COLUMNS[d]], "contrib": row[C_COLUMNS[d]]} for d in DRIVERS},
        "sim_ts": row["sim_ts"],
    }


def score_rows(conn: sqlite3.Connection, cells: list[str]) -> dict[str, sqlite3.Row]:
    marks = ",".join("?" * len(cells))
    rows = conn.execute(f"SELECT * FROM cell_scores WHERE cell IN ({marks})", cells).fetchall()
    return {r["cell"]: r for r in rows}


def footprint(cell: str) -> list[str]:
    """The cell and its ring-1 neighbours: the area a score and its support describe."""
    return sorted(h3.grid_disk(cell, 1))


def counts_by(
    conn: sqlite3.Connection, cells: list[str], first: int, last: int, column: str
) -> dict[str, int]:
    """Event counts grouped by `column` ('type' or 'source') over cells and buckets."""
    assert column in ("type", "source")
    marks = ",".join("?" * len(cells))
    rows = conn.execute(
        f"SELECT {column} AS k, COUNT(*) AS n FROM events WHERE cell IN ({marks})"
        " AND bucket BETWEEN ? AND ? GROUP BY k",
        [*cells, first, last],
    ).fetchall()
    return {r["k"]: int(r["n"]) for r in rows}


# ── evidence "as of the alert" ───────────────────────────────────────────────
# The world keeps moving while agents think (one sim-day every few seconds, reviews take
# minutes). So agents review each cell as it was when it alerted: the engine is
# deterministic and every event is stored, so the scores at any past bucket can be
# recomputed exactly. Verdicts are then reproducible and never judge a moved-on world.

HISTORY = 60
_SCORE_CACHE: dict[tuple[str, int, int], dict[str, dict[str, Any]]] = {}


def bucket_of_ts(conn: sqlite3.Connection, settings: Settings, ts: str) -> int:
    epoch0 = parse_ts(kv_get(conn, "epoch0") or "2026-01-01T00:00:00Z")
    return int((parse_ts(ts) - epoch0).total_seconds() // settings.bucket_sim_seconds)


def run_as_of(conn: sqlite3.Connection, settings: Settings, run_id: str) -> dict[str, int]:
    """Per alerted cell: the last complete bucket when its most severe alert fired."""
    rank = {"HIGH": 1, "CRITICAL": 2}
    best: dict[str, tuple[int, int]] = {}
    for a in conn.execute("SELECT cell, severity, sim_ts FROM alerts WHERE run_id = ?", (run_id,)):
        # an alert's sim_ts is the end of the day that was scored: bucket = that day
        key = (rank.get(a["severity"], 0), bucket_of_ts(conn, settings, a["sim_ts"]) - 1)
        best[a["cell"]] = max(best.get(a["cell"], key), key)
    return {cell: bucket for cell, (_, bucket) in best.items()}


def as_of_bucket(
    conn: sqlite3.Connection, settings: Settings, run_id: str, cell: str | None = None
) -> int:
    """The bucket to evaluate `cell` at in this run (latest alert bucket for other cells;
    the last complete bucket if the run has no alerts)."""
    buckets = run_as_of(conn, settings, run_id)
    if cell is not None and cell in buckets:
        return buckets[cell]
    if buckets:
        return max(buckets.values())
    return last_complete_bucket(conn, settings)


def scores_at(
    conn: sqlite3.Connection, settings: Settings, bucket: int
) -> dict[str, dict[str, Any]]:
    """Every cell's score as it was at `bucket`, recomputed by the engine (cached)."""
    from narcobob.common.db import data_version
    from narcobob.engine.cells import CellGrid
    from narcobob.engine.composite import score_cells
    from narcobob.engine.windows import TYPES

    key = (str(settings.db_file), bucket, data_version(conn))
    if key in _SCORE_CACHE:
        return _SCORE_CACHE[key]
    first_event = conn.execute("SELECT MIN(bucket) FROM events").fetchone()[0]
    if first_event is None:
        raise ToolFailure("NOT_FOUND", "no data ingested yet")
    n_buckets = min(HISTORY, bucket - int(first_event) + 1)
    if n_buckets < 14:
        raise ToolFailure("NOT_FOUND", "not enough history to score yet")
    first = bucket - n_buckets + 1
    grid = CellGrid.from_bbox(settings.area_bbox, settings.h3_res)
    import numpy as np

    counts = np.zeros((grid.n, len(TYPES), n_buckets))
    for r in conn.execute(
        "SELECT cell, type, bucket, COUNT(*) AS n FROM events WHERE bucket BETWEEN ? AND ?"
        " GROUP BY cell, type, bucket",
        (first, bucket),
    ):
        i = grid.index.get(r["cell"])
        if i is not None:
            counts[i, TYPES.index(r["type"]), r["bucket"] - first] = r["n"]
    result = score_cells(counts, grid, settings.weights, settings.thresholds)
    end = bucket_start(conn, settings, bucket + 1).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, dict[str, Any]] = {}
    for i, cell in enumerate(grid.cells):
        out[cell] = {
            "cell": cell,
            "score": int(result.score[i]),
            "severity": result.severity[i],
            "confidence": result.confidence[i],
            "support": int(result.support[i]),
            "components": {
                d: {
                    "z": round(float(result.z[d][i]), 3),
                    "contrib": round(float(result.contrib[d][i]), 3),
                }
                for d in DRIVERS
            },
            "sim_ts": end,
        }
    if len(_SCORE_CACHE) > 16:
        _SCORE_CACHE.clear()
    _SCORE_CACHE[key] = out
    return out


def scores_for(
    conn: sqlite3.Connection, settings: Settings, run_id: str, cells: list[str]
) -> dict[str, dict[str, Any]]:
    """Each requested cell's score as of its own alert in this run."""
    out: dict[str, dict[str, Any]] = {}
    for cell in cells:
        at = scores_at(conn, settings, as_of_bucket(conn, settings, run_id, cell))
        if cell in at:
            out[cell] = at[cell]
    return out
