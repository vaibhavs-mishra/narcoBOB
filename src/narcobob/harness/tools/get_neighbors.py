"""`get_neighbors`: scores of the cells around a cell (rings 1..k), for clustering and spillover."""

from __future__ import annotations

import sqlite3
from typing import Any

import h3

from narcobob.harness.data import check_cells, score_rows
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_neighbors"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cell = check_cells([str(args.get("cell", ""))])[0]
    k = int(args.get("k", 1))
    if not 1 <= k <= 2:
        raise ToolFailure("VALIDATION_ERROR", "k must be 1 or 2")
    around = sorted(set(h3.grid_disk(cell, k)) - {cell})
    rows = score_rows(conn, around)
    return {
        "cell": cell,
        "neighbors": [
            {"cell": c, "ring": h3.grid_distance(cell, c), "score": rows[c]["score"],
             "severity": rows[c]["severity"]}
            for c in around if c in rows
        ],
    }  # fmt: skip
