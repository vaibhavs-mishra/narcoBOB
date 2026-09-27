"""`get_findings`: what earlier agents in this run concluded (this run only)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from narcobob.harness.envelope import CallContext
from narcobob.harness.errors import ToolFailure

NAME = "get_findings"
VERSION = "1.0"
KINDS = ("data_quality", "analysis", "verdict")
AGENTS = ("steward", "analyst", "skeptic", "writer")


def run(conn: sqlite3.Connection, ctx: CallContext, args: dict[str, Any]) -> dict[str, Any]:
    sql = (
        "SELECT finding_id, run_id, step_id, agent_id, kind, cell, payload, source, wall_at"
        " FROM findings WHERE run_id = ?"
    )
    params: list[Any] = [ctx.run_id]
    agent, kind = args.get("agent_id_filter"), args.get("kind")
    if agent:
        if agent not in AGENTS:
            raise ToolFailure("VALIDATION_ERROR", f"agent_id_filter must be one of {AGENTS}")
        sql += " AND agent_id = ?"
        params.append(agent)
    if kind:
        if kind not in KINDS:
            raise ToolFailure("VALIDATION_ERROR", f"kind must be one of {KINDS}")
        sql += " AND kind = ?"
        params.append(kind)
    rows = conn.execute(sql + " ORDER BY wall_at, finding_id", params).fetchall()
    return {"findings": [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]}
