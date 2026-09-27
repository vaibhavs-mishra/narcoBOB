"""`run_sensitivity`: does the alert survive other reasonable weightings of the evidence?

Evaluated as of each cell's alert in this run.

Re-scores each cell's stored component z-scores under N Dirichlet-perturbed weight vectors
(engine.sensitivity). Seeded by the data version, so the same data gives the same answer.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import numpy as np

from narcobob.common.config import get_settings
from narcobob.common.db import data_version
from narcobob.engine.sensitivity import sensitivity
from narcobob.harness.data import DRIVERS, check_cells, scores_for
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "run_sensitivity"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    cells = check_cells(list(args.get("cells") or []))
    samples = int(args.get("samples", 30))
    if not 5 <= samples <= 200:
        raise ToolFailure("VALIDATION_ERROR", "samples must be between 5 and 200")
    settings = get_settings()
    rows = scores_for(conn, settings, ctx.run_id, cells)
    missing = [c for c in cells if c not in rows]
    if missing:
        raise ToolFailure("NOT_FOUND", f"no scores for {missing}")
    z = np.array([[float(rows[c]["components"][d]["z"]) for d in DRIVERS] for c in cells])
    result = sensitivity(z, settings.weights, settings.thresholds[1], samples, data_version(conn))
    return {
        "samples": samples,
        "high_threshold": settings.thresholds[1],
        "cells": [
            {"cell": c, "stability": round(r.stability, 3), "min_score": r.min_score,
             "max_score": r.max_score, "median_score": r.median_score}
            for c, r in zip(cells, result, strict=True)
        ],
    }  # fmt: skip
