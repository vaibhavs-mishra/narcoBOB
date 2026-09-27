"""Contract tests for the harness envelope and the first two tools."""

from __future__ import annotations

import sqlite3
from typing import Any

from narcobob.harness import envelope
from narcobob.harness.envelope import CallContext, execute
from narcobob.harness.tools import get_run_context, submit_findings
from tests.harness.conftest import CELL, add_step, ctx_for


def call(conn: sqlite3.Connection, ctx: CallContext, module: Any, **args: Any) -> dict[str, Any]:
    return execute(conn, ctx, module.NAME, module.VERSION, module.run, args)


def dq(issue: str = "ok") -> dict[str, Any]:
    return {
        "kind": "data_quality",
        "payload": {"cell": CELL, "issue": issue, "detail": "d", "affects_recent_window": False},
    }


def test_get_run_context_happy_path(conn: sqlite3.Connection) -> None:
    out = call(conn, ctx_for(conn, "steward"), get_run_context)
    assert out["ok"] and out["error"] is None
    assert out["data"]["cells"] == [CELL]
    assert out["data"]["alerts"][0]["alert_id"] == "a1"
    assert out["data"]["data_version"] == 3
    assert out["meta"]["tool"] == "get_run_context"


def test_call_is_traced_and_counted(conn: sqlite3.Connection) -> None:
    ctx = ctx_for(conn, "steward")
    call(conn, ctx, get_run_context)
    assert conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0] == 1
    steps = conn.execute("SELECT tool_calls FROM agent_steps WHERE step_id=?", (ctx.step_id,))
    assert steps.fetchone()[0] == 1


def test_forbidden_agent(conn: sqlite3.Connection) -> None:
    out = call(conn, ctx_for(conn, "writer"), submit_findings, findings=[dq()], idempotency_key="k")
    assert not out["ok"] and out["error"]["code"] == "FORBIDDEN_TOOL"


def test_step_not_active(conn: sqlite3.Connection) -> None:
    step = add_step(conn, "r1", "steward", status="done")
    ctx = CallContext(run_id="r1", agent_id="steward", step_id=step)
    out = call(conn, ctx, get_run_context)
    assert out["error"]["code"] == "STEP_NOT_ACTIVE"
    wrong_agent = CallContext(
        run_id="r1", agent_id="skeptic", step_id=ctx_for(conn, "analyst").step_id
    )
    assert call(conn, wrong_agent, get_run_context)["error"]["code"] == "STEP_NOT_ACTIVE"


def test_submit_findings_validation_error(conn: sqlite3.Connection) -> None:
    ctx = ctx_for(conn, "steward")
    bad = {"kind": "data_quality", "payload": {"cell": CELL, "issue": "nonsense"}}
    out = call(conn, ctx, submit_findings, findings=[bad], idempotency_key="k")
    assert out["error"]["code"] == "VALIDATION_ERROR"
    assert not out["error"]["retryable"]


def test_agent_can_only_submit_its_own_kind(conn: sqlite3.Connection) -> None:
    ctx = ctx_for(conn, "skeptic")
    out = call(conn, ctx, submit_findings, findings=[dq()], idempotency_key="k")
    assert out["error"]["code"] == "VALIDATION_ERROR"


def test_submit_findings_idempotent_and_conflict(conn: sqlite3.Connection) -> None:
    ctx = ctx_for(conn, "steward")
    first = call(conn, ctx, submit_findings, findings=[dq()], idempotency_key="k")
    again = call(conn, ctx, submit_findings, findings=[dq()], idempotency_key="k")
    assert first["ok"] and again["data"] == first["data"]
    assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1
    changed = call(conn, ctx, submit_findings, findings=[dq("duplicates")], idempotency_key="k")
    assert changed["error"]["code"] == "CONFLICT"


def test_budget_exceeded(conn: sqlite3.Connection) -> None:
    ctx = ctx_for(conn, "steward")
    conn.execute(
        "UPDATE agent_steps SET tool_calls = ? WHERE step_id = ?",
        (envelope.MAX_CALLS_PER_STEP, ctx.step_id),
    )
    assert call(conn, ctx, get_run_context)["error"]["code"] == "BUDGET_EXCEEDED"
