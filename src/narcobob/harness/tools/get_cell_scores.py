"""`get_cell_scores`: the engine's score, severity and per-component evidence for cells,
as of each cell's alert in this run."""

from __future__ import annotations

import sqlite3
from typing import Any

from narcobob.common.config import get_settings
from narcobob.harness.data import as_of_bucket, check_cells, scores_at, scores_for
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_cell_scores"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cells, top_k = args.get("cells"), args.get("top_k")
    settings = get_settings()
    if cells:
        found = scores_for(conn, settings, ctx.run_id, check_cells(list(cells)))
        return {"cells": [found[c] for c in cells if c in found]}
    if top_k:
        k = int(top_k)
        if not 1 <= k <= 50:
            raise ToolFailure("VALIDATION_ERROR", "top_k must be between 1 and 50")
        at = scores_at(conn, settings, as_of_bucket(conn, settings, ctx.run_id))
        top = sorted(at.values(), key=lambda s: int(s["score"]), reverse=True)[:k]
        return {"cells": top}
    raise ToolFailure("VALIDATION_ERROR", "give cells or top_k")
