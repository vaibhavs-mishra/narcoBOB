"""The `narcobob` MCP server: the only surface Bob agents can act through.

Each MCP tool below is a thin typed wrapper. The real work, and every safety check,
happens in `envelope.execute()` and the per-tool modules under `tools/`.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from narcobob.common.config import get_settings
from narcobob.common.db import init_db
from narcobob.common.logging import setup_logging
from narcobob.harness.envelope import CallContext, ToolFn, execute
from narcobob.harness.tools import get_run_context, submit_findings

log = logging.getLogger(__name__)

AgentId = Literal["steward", "analyst", "skeptic", "writer"]

settings = get_settings()
mcp = FastMCP(
    "narcobob",
    host="127.0.0.1",
    port=settings.mcp_port,
    streamable_http_path="/mcp",
    stateless_http=True,
)
_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = init_db(settings.db_file)
    return _conn


def _call(
    name: str, version: str, fn: ToolFn, run_id: str, agent_id: str, step_id: str, **args: Any
) -> dict[str, Any]:
    ctx = CallContext(run_id=run_id, agent_id=agent_id, step_id=step_id, source="bob")
    return execute(_db(), ctx, name, version, fn, args)


@mcp.tool(name=get_run_context.NAME)
def get_run_context_tool(run_id: str, agent_id: AgentId, step_id: str) -> dict[str, Any]:
    """Get this run's alerted cells, their alerts, the public config and the sim clock.
    Call this first."""
    m = get_run_context
    return _call(m.NAME, m.VERSION, m.run, run_id, agent_id, step_id)


@mcp.tool(name=submit_findings.NAME)
def submit_findings_tool(
    run_id: str,
    agent_id: AgentId,
    step_id: str,
    findings: list[dict[str, Any]],
    idempotency_key: str,
) -> dict[str, Any]:
    """Submit your findings. Each item is {"kind": ..., "payload": {...}}; the payload schema
    depends on kind (steward: data_quality, analyst: analysis, skeptic: verdict).
    Call exactly once at the end of your step."""
    m = submit_findings
    return _call(
        m.NAME,
        m.VERSION,
        m.run,
        run_id,
        agent_id,
        step_id,
        findings=findings,
        idempotency_key=idempotency_key,
    )


def run() -> None:
    setup_logging()
    _db()
    log.info("narcobob MCP listening", extra={"port": settings.mcp_port, "path": "/mcp"})
    mcp.run(transport="streamable-http")
