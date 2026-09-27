"""`get_data_quality`: is the data behind these cells trustworthy?

- source gaps: a normally-reporting source that went silent for ≥ 2 sim-days
  (engine.quality.source_gaps), with the requested cells that depend on it (≥ 20% of
  their events in the preceding window)
- single-source dependence per cell (share of the top source in the last 7 sim-days)
- running totals of duplicate deliveries and late events seen at ingest
"""

from __future__ import annotations

import sqlite3
from typing import Any

import numpy as np

from narcobob.common.config import get_settings
from narcobob.common.db import kv_get
from narcobob.engine.quality import source_gaps
from narcobob.harness.data import RECENT, check_cells, counts_by, footprint, last_complete_bucket
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_data_quality"
VERSION = "1.0"
DEPENDS_SHARE = 0.2


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cells = check_cells(list(args.get("cells") or []))
    window = int(args.get("window_buckets", 14))
    if not 7 <= window <= 60:
        raise ToolFailure("VALIDATION_ERROR", "window_buckets must be between 7 and 60")
    last = last_complete_bucket(conn, get_settings())
    history_first = last - 28 - window + 1  # enough history to know a source's normal rate
    rows = conn.execute(
        "SELECT source, bucket, COUNT(*) AS n FROM events WHERE bucket BETWEEN ? AND ?"
        " GROUP BY source, bucket",
        (history_first, last),
    ).fetchall()
    sources = sorted({r["source"] for r in rows})
    per_source = np.zeros((len(sources), last - history_first + 1))
    for r in rows:
        per_source[sources.index(r["source"]), r["bucket"] - history_first] = r["n"]

    window_first = last - window + 1
    gaps = []
    for g in source_gaps(per_source):
        to_bucket = history_first + g.to_bucket
        if to_bucket < window_first:
            continue
        source = sources[g.source]
        from_bucket = history_first + g.from_bucket
        affected = []
        for cell in cells:
            before = counts_by(conn, footprint(cell), from_bucket - 14, from_bucket - 1, "source")
            total = sum(before.values())
            if total and before.get(source, 0) / total >= DEPENDS_SHARE:
                affected.append(cell)
        gaps.append(
            {
                "source": source,
                "from_bucket": from_bucket,
                "to_bucket": to_bucket,
                "in_recent_window": to_bucket > last - RECENT,
                "cells_affected": affected,
            }
        )

    single = []
    for cell in cells:
        recent = counts_by(conn, footprint(cell), last - RECENT + 1, last, "source")
        total = sum(recent.values())
        if total:
            top = max(recent, key=lambda k: recent[k])
            single.append({"cell": cell, "source": top, "share": round(recent[top] / total, 3)})
    return {
        "window_buckets": window,
        "last_bucket": last,
        "duplicates": int(kv_get(conn, "duplicates_total") or 0),
        "late_events": int(kv_get(conn, "late_events_total") or 0),
        "source_gaps": gaps,
        "single_source": single,
    }
