"""`get_cell_timeseries`: daily event counts for one cell, up to its alert in this run."""

from __future__ import annotations

import sqlite3
from typing import Any

from narcobob.common.config import get_settings
from narcobob.harness.data import as_of_bucket, check_cells
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_cell_timeseries"
VERSION = "1.0"
TYPES = ("overdose", "seizure", "arrest")


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cell = check_cells([str(args.get("cell", ""))])[0]
    types = list(args.get("types") or TYPES)
    if any(t not in TYPES for t in types):
        raise ToolFailure("VALIDATION_ERROR", f"types must be among {TYPES}")
    buckets = int(args.get("buckets", 28))
    if not 1 <= buckets <= 60:
        raise ToolFailure("VALIDATION_ERROR", "buckets must be between 1 and 60")
    last = as_of_bucket(conn, get_settings(), ctx.run_id, cell)
    first = last - buckets + 1
    series = {t: [0] * buckets for t in types}
    for r in conn.execute(
        "SELECT type, bucket, COUNT(*) AS n FROM events WHERE cell = ? AND bucket BETWEEN ? AND ?"
        " GROUP BY type, bucket",
        (cell, first, last),
    ):
        if r["type"] in series:
            series[r["type"]][r["bucket"] - first] = int(r["n"])
    return {"cell": cell, "buckets": list(range(first, last + 1)), "series": series}
