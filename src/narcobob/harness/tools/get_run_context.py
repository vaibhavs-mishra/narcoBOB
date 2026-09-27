"""`get_run_context`: what this run is about — its cells, alerts and the public config."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from narcobob.common.config import get_settings, public_config
from narcobob.common.db import kv_get
from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_run_context"
VERSION = "1.0"


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (ctx.run_id,)).fetchone()
    if row is None:
        raise ToolFailure("NOT_FOUND", f"run {ctx.run_id!r} not found")
    alert_ids: list[str] = json.loads(row["alert_ids"])
    marks = ",".join("?" * len(alert_ids))
    alerts = [
        dict(a)
        for a in conn.execute(
            f"SELECT * FROM alerts WHERE alert_id IN ({marks}) ORDER BY sim_ts", alert_ids
        )
    ]
    return {
        "run_id": ctx.run_id,
        "cells": json.loads(row["cells"]),
        "alerts": alerts,
        "config": public_config(get_settings()),
        "sim_now": kv_get(conn, "sim_now"),
        "data_version": int(row["data_version"]),
    }
