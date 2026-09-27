"""Runs one tool call end to end: authorise, budget, execute, cap, trace, wrap.

Every tool, whether called by a Bob agent over MCP or by a fallback agent in-process,
goes through `execute()`, so both paths get identical checks and identical outputs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from narcobob.common.ids import new_id, wall_now
from narcobob.harness.authz import check_active_step, check_allowed
from narcobob.harness.errors import ToolFailure

log = logging.getLogger(__name__)

MAX_CALLS_PER_STEP = 40
MAX_RESPONSE_BYTES = 32 * 1024


@dataclass(frozen=True)
class CallContext:
    """Who is calling: the three ids every tool requires, plus the output source."""

    run_id: str
    agent_id: str
    step_id: str
    source: str = "bob"  # "bob" over MCP, "fallback" in-process


ToolFn = Callable[[sqlite3.Connection, CallContext, dict[str, Any]], dict[str, Any]]


def _args_hash(args: dict[str, Any]) -> str:
    blob = json.dumps(args, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _check_budget(conn: sqlite3.Connection, step_id: str) -> None:
    row = conn.execute(
        "SELECT tool_calls FROM agent_steps WHERE step_id = ?", (step_id,)
    ).fetchone()
    if row is not None and int(row["tool_calls"]) >= MAX_CALLS_PER_STEP:
        raise ToolFailure("BUDGET_EXCEEDED", f"step used its {MAX_CALLS_PER_STEP} tool calls")


def _cap(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Trim the largest list in `data` until the JSON fits the response cap."""
    if len(json.dumps(data, default=str)) <= MAX_RESPONSE_BYTES:
        return data, False
    data = dict(data)
    lists = [k for k, v in data.items() if isinstance(v, list)]
    while lists and len(json.dumps(data, default=str)) > MAX_RESPONSE_BYTES:
        key = max(lists, key=lambda k: len(data[k]))
        if not data[key]:
            break
        data[key] = data[key][: len(data[key]) // 2]
    return data, True


def _trace(
    conn: sqlite3.Connection,
    ctx: CallContext,
    tool: str,
    version: str,
    args: dict[str, Any],
    trace_id: str,
    error_code: str | None,
    duration_ms: int,
) -> None:
    conn.execute(
        "INSERT INTO tool_calls(call_id, trace_id, run_id, step_id, agent_id, tool, tool_version,"
        " args_hash, ok, error_code, duration_ms, wall_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id(),
            trace_id,
            ctx.run_id,
            ctx.step_id,
            ctx.agent_id,
            tool,
            version,
            _args_hash(args),
            int(error_code is None),
            error_code,
            duration_ms,
            wall_now(),
        ),
    )
    conn.execute(
        "UPDATE agent_steps SET tool_calls = tool_calls + 1 WHERE step_id = ?", (ctx.step_id,)
    )
    conn.commit()


def execute(
    conn: sqlite3.Connection,
    ctx: CallContext,
    tool: str,
    version: str,
    fn: ToolFn,
    args: dict[str, Any],
) -> dict[str, Any]:
    trace_id = new_id()
    started = time.perf_counter()
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    truncated = False
    try:
        check_allowed(tool, ctx.agent_id)
        check_active_step(conn, ctx.run_id, ctx.step_id, ctx.agent_id)
        _check_budget(conn, ctx.step_id)
        data, truncated = _cap(fn(conn, ctx, args))
    except ToolFailure as failure:
        conn.rollback()
        error = {"code": failure.code, "message": failure.message, "retryable": failure.retryable}
    except ValidationError as exc:
        conn.rollback()
        message = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        error = {"code": "VALIDATION_ERROR", "message": message, "retryable": False}
    except Exception:
        conn.rollback()
        log.exception("tool crashed", extra={"tool": tool, "trace_id": trace_id})
        error = {"code": "INTERNAL", "message": "internal error", "retryable": True}

    duration_ms = int((time.perf_counter() - started) * 1000)
    error_code = None if error is None else str(error["code"])
    _trace(conn, ctx, tool, version, args, trace_id, error_code, duration_ms)
    return {
        "ok": error is None,
        "data": data,
        "error": error,
        "meta": {
            "run_id": ctx.run_id,
            "agent_id": ctx.agent_id,
            "step_id": ctx.step_id,
            "trace_id": trace_id,
            "tool": tool,
            "tool_version": version,
            "duration_ms": duration_ms,
            "truncated": truncated,
        },
    }
