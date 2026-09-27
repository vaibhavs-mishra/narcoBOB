"""The `narcobob` MCP server: the only surface Bob agents can act through.

Each MCP tool below is a thin typed wrapper so agents see an accurate schema. The real
work, and every safety check (allowlist, active step, budget, size cap, tracing), happens
in `envelope.execute()` and the per-tool modules under `tools/`.
"""

from __future__ import annotations

import logging
import sqlite3
from types import ModuleType
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from narcobob.common.config import get_settings
from narcobob.common.db import init_db
from narcobob.common.logging import setup_logging
from narcobob.harness.envelope import CallContext, execute
from narcobob.harness.tools import (
    get_cell_scores,
    get_cell_timeseries,
    get_data_quality,
    get_findings,
    get_neighbors,
    get_run_context,
    get_support,
    run_sensitivity,
    submit_findings,
    submit_report,
)

log = logging.getLogger(__name__)

AgentId = Literal["steward", "analyst", "skeptic", "writer"]
EventType = Literal["overdose", "seizure", "arrest"]

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
    tool: ModuleType, run_id: str, agent_id: str, step_id: str, **args: Any
) -> dict[str, Any]:
    ctx = CallContext(run_id=run_id, agent_id=agent_id, step_id=step_id, source="bob")
    return execute(_db(), ctx, tool.NAME, tool.VERSION, tool.run, args)


@mcp.tool(name=get_run_context.NAME)
def get_run_context_tool(run_id: str, agent_id: AgentId, step_id: str) -> dict[str, Any]:
    """This run's alerted cells, their alerts, the public config and the sim clock.
    Call this first."""
    return _call(get_run_context, run_id, agent_id, step_id)


@mcp.tool(name=get_data_quality.NAME)
def get_data_quality_tool(
    run_id: str, agent_id: AgentId, step_id: str, cells: list[str], window_buckets: int = 14
) -> dict[str, Any]:
    """Feed gaps (sources that went silent), the cells that depend on them, single-source
    dependence per cell, and duplicate/late-event totals."""
    return _call(get_data_quality, run_id, agent_id, step_id, cells=cells,
                 window_buckets=window_buckets)  # fmt: skip


@mcp.tool(name=get_cell_scores.NAME)
def get_cell_scores_tool(
    run_id: str, agent_id: AgentId, step_id: str,
    cells: list[str] | None = None, top_k: int | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Engine scores (0-100), severity, support, confidence and per-component evidence
    (z-score and contribution for accel, div, spill, gi). Give cells or top_k."""
    return _call(get_cell_scores, run_id, agent_id, step_id, cells=cells, top_k=top_k)


@mcp.tool(name=get_cell_timeseries.NAME)
def get_cell_timeseries_tool(
    run_id: str, agent_id: AgentId, step_id: str, cell: str,
    types: list[EventType] | None = None, buckets: int = 28,
) -> dict[str, Any]:  # fmt: skip
    """Daily event counts for one cell (one bucket = one sim-day), up to the last full day."""
    return _call(get_cell_timeseries, run_id, agent_id, step_id, cell=cell, types=types,
                 buckets=buckets)  # fmt: skip


@mcp.tool(name=get_neighbors.NAME)
def get_neighbors_tool(
    run_id: str, agent_id: AgentId, step_id: str, cell: str, k: int = 1
) -> dict[str, Any]:
    """Scores and severities of the cells within k rings (1 or 2) of a cell."""
    return _call(get_neighbors, run_id, agent_id, step_id, cell=cell, k=k)


@mcp.tool(name=get_support.NAME)
def get_support_tool(
    run_id: str, agent_id: AgentId, step_id: str, cells: list[str]
) -> dict[str, Any]:
    """Evidence behind each score over the last 7 sim-days (cell + ring-1): support,
    confidence, counts by event type and by source, and the top source's share."""
    return _call(get_support, run_id, agent_id, step_id, cells=cells)


@mcp.tool(name=run_sensitivity.NAME)
def run_sensitivity_tool(
    run_id: str, agent_id: AgentId, step_id: str, cells: list[str], samples: int = 30
) -> dict[str, Any]:
    """Re-score cells under randomly perturbed component weights. stability = share of
    samples in which the cell stays at HIGH or above."""
    return _call(run_sensitivity, run_id, agent_id, step_id, cells=cells, samples=samples)


@mcp.tool(name=get_findings.NAME)
def get_findings_tool(
    run_id: str, agent_id: AgentId, step_id: str,
    agent_id_filter: AgentId | None = None,
    kind: Literal["data_quality", "analysis", "verdict"] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Findings already submitted in this run, optionally filtered by agent or kind."""
    return _call(get_findings, run_id, agent_id, step_id, agent_id_filter=agent_id_filter,
                 kind=kind)  # fmt: skip


@mcp.tool(name=submit_findings.NAME)
def submit_findings_tool(
    run_id: str, agent_id: AgentId, step_id: str,
    findings: list[dict[str, Any]], idempotency_key: str,
) -> dict[str, Any]:  # fmt: skip
    """Submit your findings, once, at the end of your step. Each item is
    {"kind": ..., "payload": {...}}; steward → data_quality, analyst → analysis,
    skeptic → verdict. Payload schemas are in your mode rules."""
    return _call(submit_findings, run_id, agent_id, step_id, findings=findings,
                 idempotency_key=idempotency_key)  # fmt: skip


@mcp.tool(name=submit_report.NAME)
def submit_report_tool(
    run_id: str, agent_id: AgentId, step_id: str, report: dict[str, Any], idempotency_key: str
) -> dict[str, Any]:
    """Writer only: submit the brief, once. report = {"markdown": str, "recommendations":
    [{"track": "enforcement"|"treatment", "cells": [...], "action": str,
    "priority": "immediate"|"this_week"|"monitor"}]}. Needs ≥ 1 of each track."""
    return _call(submit_report, run_id, agent_id, step_id, report=report,
                 idempotency_key=idempotency_key)  # fmt: skip


def run() -> None:
    setup_logging()
    _db()
    log.info("narcobob MCP listening", extra={"port": settings.mcp_port, "path": "/mcp"})
    mcp.run(transport="streamable-http")
