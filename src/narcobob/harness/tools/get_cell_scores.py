"""`get_cell_scores`: the engine's score, severity and per-component evidence for cells."""

from __future__ import annotations

import sqlite3
from typing import Any

from narcobob.harness.data import check_cells, score_row_to_dict, score_rows
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_cell_scores"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cells, top_k = args.get("cells"), args.get("top_k")
    if cells:
        rows = score_rows(conn, check_cells(list(cells)))
        return {"cells": [score_row_to_dict(rows[c]) for c in cells if c in rows]}
    if top_k:
        k = int(top_k)
        if not 1 <= k <= 50:
            raise ToolFailure("VALIDATION_ERROR", "top_k must be between 1 and 50")
        top = conn.execute("SELECT * FROM cell_scores ORDER BY score DESC LIMIT ?", (k,))
        return {"cells": [score_row_to_dict(r) for r in top]}
    raise ToolFailure("VALIDATION_ERROR", "give cells or top_k")
