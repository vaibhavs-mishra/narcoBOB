"""`get_support`: how much evidence stands behind each cell's score (last 7 sim-days).

Counts cover the cell plus its ring-1 neighbours, the same footprint the score uses.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from narcobob.common.config import get_settings
from narcobob.harness.data import (
    RECENT,
    check_cells,
    counts_by,
    footprint,
    last_complete_bucket,
    score_rows,
)
from narcobob.harness.envelope import CallContext

NAME = "get_support"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cells = check_cells(list(args.get("cells") or []))
    last = last_complete_bucket(conn, get_settings())
    scores = score_rows(conn, cells)
    out = []
    for cell in cells:
        area = footprint(cell)
        by_source = counts_by(conn, area, last - RECENT + 1, last, "source")
        total = sum(by_source.values())
        top = max(by_source, key=lambda k: by_source[k]) if by_source else None
        out.append(
            {
                "cell": cell,
                "support": scores[cell]["support"] if cell in scores else total,
                "confidence": scores[cell]["confidence"] if cell in scores else "low",
                "by_type": counts_by(conn, area, last - RECENT + 1, last, "type"),
                "by_source": by_source,
                "top_source": top,
                "top_source_share": round(by_source[top] / total, 3) if top else 0.0,
            }
        )
    return {"window_buckets": RECENT, "cells": out}
