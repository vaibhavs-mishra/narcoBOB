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
