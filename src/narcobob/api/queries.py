"""Read models for the REST API and the WebSocket payloads (shapes per the contract)."""

from __future__ import annotations

import json
from typing import Any

import h3

from narcobob.api.state import AppState
from narcobob.common.config import public_config
from narcobob.common.db import data_version

SNAPSHOT_MIN_SCORE = 40


def alert_rows(state: AppState, limit: int = 50, cell: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM alerts", []  # type: ignore[var-annotated]
    if cell is not None:
        sql, args = sql + " WHERE cell = ?", [cell]
    sql += " ORDER BY wall_created_at DESC, alert_id DESC LIMIT ?"
    return [dict(r) for r in state.conn.execute(sql, [*args, limit])]


def latest_verdicts(state: AppState) -> dict[str, dict[str, Any]]:
    """Per cell: final severity and verdict from its most recent judged alert."""
    rows = state.conn.execute(
        "SELECT cell, final_severity, verdict FROM alerts WHERE verdict IS NOT NULL"
        " ORDER BY wall_created_at"
    ).fetchall()
    return {
        r["cell"]: {"final_severity": r["final_severity"], "verdict": r["verdict"]} for r in rows
    }


def with_verdict(score: dict[str, Any], verdicts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {**score, **verdicts.get(str(score["cell"]), {})}


def run_summary(state: AppState, run_id: str) -> dict[str, Any] | None:
    row = state.conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    steps = state.conn.execute(
        "SELECT agent_id, status, source FROM agent_steps WHERE run_id = ?"
        " ORDER BY wall_started_at, step_id",
        (run_id,),
    ).fetchall()
    return {
        "run_id": row["run_id"], "status": row["status"], "cells": json.loads(row["cells"]),
        "wall_started_at": row["wall_started_at"], "wall_finished_at": row["wall_finished_at"],
        "steps": [dict(s) for s in steps],
    }  # fmt: skip


def recent_runs(state: AppState, limit: int = 10) -> list[dict[str, Any]]:
    ids = state.conn.execute(
        "SELECT run_id FROM agent_runs ORDER BY run_id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [s for r in ids if (s := run_summary(state, r["run_id"])) is not None]


def kpis(state: AppState) -> dict[str, Any]:
    # alerts whose (final) severity is still HIGH+, raised in the last 15 wall-minutes
    active = state.conn.execute(
        "SELECT COUNT(*) FROM alerts"
        " WHERE COALESCE(final_severity, severity) IN ('HIGH', 'CRITICAL')"
        " AND wall_created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-15 minutes')"
    ).fetchone()[0]
    elevated = sum(1 for s in state.scores.values() if s["severity"] != "NORMAL")
    return {
        "events_per_min": state.events_per_min(),
        "active_alerts": int(active),
        "cells_monitored": state.grid.n,
        "cells_elevated": elevated,
        "sim_now": state.sim_now(),
        "data_version": data_version(state.conn),
    }


def snapshot(state: AppState, sim: dict[str, Any], seq: int) -> dict[str, Any]:
    verdicts = latest_verdicts(state)
    cells = [
        with_verdict(s, verdicts)
        for s in state.scores.values()
        if s["severity"] != "NORMAL" or int(str(s["score"])) >= SNAPSHOT_MIN_SCORE
    ]
    return {
        "config": public_config(state.settings),
        "sim": sim,
        "kpis": kpis(state),
        "cells": cells,
        "alerts": alert_rows(state),
        "runs": recent_runs(state),
        "seq": seq,
    }


def cell_detail(state: AppState, cell: str) -> dict[str, Any] | None:
    score = state.scores.get(cell)
    if score is None:
        return None
    neighbours = []
    for nb in sorted(h3.grid_ring(cell, 1)):
        s = state.scores.get(nb)
        if s is not None:
            neighbours.append({"cell": nb, "score": s["score"], "severity": s["severity"]})
    row = state.conn.execute(
        "SELECT payload FROM findings WHERE kind = 'verdict' AND cell = ?"
        " ORDER BY wall_at DESC LIMIT 1",
        (cell,),
    ).fetchone()
    return {
        **with_verdict(score, latest_verdicts(state)),
        "neighbors": neighbours,
        "latest_verdict": json.loads(row["payload"]) if row else None,
        "alerts": alert_rows(state, 20, cell),
    }


def timeseries(state: AppState, cell: str, types: list[str], buckets: int) -> dict[str, Any]:
    last = state.scored_bucket
    first = last - buckets + 1
    rows = state.conn.execute(
        "SELECT type, bucket, COUNT(*) AS n FROM events WHERE cell = ? AND bucket BETWEEN ? AND ?"
        " GROUP BY type, bucket",
        (cell, first, last),
    ).fetchall()
    series = {t: [0] * buckets for t in types}
    for r in rows:
        if r["type"] in series:
            series[r["type"]][r["bucket"] - first] = int(r["n"])
    return {"cell": cell, "buckets": list(range(first, last + 1)), "series": series}


def full_run(state: AppState, run_id: str) -> dict[str, Any] | None:
    row = state.conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    steps = [
        {k: v for k, v in dict(r).items() if k != "log"}
        for r in state.conn.execute(
            "SELECT * FROM agent_steps WHERE run_id = ? ORDER BY wall_started_at", (run_id,)
        )
    ]
    findings = [
        {**dict(r), "payload": json.loads(r["payload"])}
        for r in state.conn.execute(
            "SELECT finding_id, run_id, step_id, agent_id, kind, cell, payload, source, wall_at"
            " FROM findings WHERE run_id = ? ORDER BY wall_at",
            (run_id,),
        )
    ]
    return {
        "run_id": run_id, "status": row["status"], "alert_ids": json.loads(row["alert_ids"]),
        "cells": json.loads(row["cells"]), "data_version": row["data_version"],
        "wall_started_at": row["wall_started_at"], "wall_finished_at": row["wall_finished_at"],
        "steps": steps, "findings": findings, "report": report(state, run_id),
    }  # fmt: skip


def run_log(state: AppState, run_id: str) -> dict[str, Any] | None:
    """Each step's console output and every tool call of the run, oldest first."""
    if (
        state.conn.execute("SELECT 1 FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        is None
    ):
        return None
    steps = [
        dict(r)
        for r in state.conn.execute(
            "SELECT step_id, run_id, agent_id, status, source, attempt, tool_calls, log,"
            " wall_started_at, wall_finished_at FROM agent_steps WHERE run_id = ?"
            " ORDER BY wall_started_at",
            (run_id,),
        )
    ]
    calls = [
        {**dict(r), "ok": bool(r["ok"])}
        for r in state.conn.execute(
            "SELECT run_id, step_id, agent_id, tool, ok, error_code, duration_ms, wall_at"
            " FROM tool_calls WHERE run_id = ? ORDER BY wall_at",
            (run_id,),
        )
    ]
    return {"run_id": run_id, "steps": steps, "tool_calls": calls}


def report(state: AppState, run_id: str) -> dict[str, Any] | None:
    r = state.conn.execute(
        "SELECT report_id, run_id, markdown, recommendations, provenance_ratio, source, wall_at"
        " FROM reports WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if r is None:
        return None
    return {**dict(r), "recommendations": json.loads(r["recommendations"])}
