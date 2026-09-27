"""Who may call what, and when.

Two independent checks run before every tool call:
1. the calling agent is on the tool's allowlist, and
2. the (run_id, step_id, agent_id) triple is a step the orchestrator marked `running`.
An agent therefore cannot act outside its own live step, even with a valid tool name.
"""

from __future__ import annotations

import sqlite3

from narcobob.harness.errors import ToolFailure

ALL = frozenset({"steward", "analyst", "skeptic", "writer"})

ALLOWLIST: dict[str, frozenset[str]] = {
    "get_run_context": ALL,
    "get_data_quality": frozenset({"steward", "skeptic"}),
    "get_cell_scores": frozenset({"analyst", "writer"}),
    "get_cell_timeseries": frozenset({"steward", "analyst", "skeptic"}),
    "get_neighbors": frozenset({"analyst"}),
    "get_support": frozenset({"skeptic"}),
    "run_sensitivity": frozenset({"skeptic"}),
    "get_findings": frozenset({"analyst", "skeptic", "writer"}),
    "submit_findings": frozenset({"steward", "analyst", "skeptic"}),
    "submit_report": frozenset({"writer"}),
}


def check_allowed(tool: str, agent_id: str) -> None:
    if agent_id not in ALL:
        raise ToolFailure("VALIDATION_ERROR", f"unknown agent_id {agent_id!r}")
    if agent_id not in ALLOWLIST.get(tool, frozenset()):
        raise ToolFailure("FORBIDDEN_TOOL", f"agent {agent_id!r} may not call {tool!r}")


def check_active_step(conn: sqlite3.Connection, run_id: str, step_id: str, agent_id: str) -> None:
    row = conn.execute(
        "SELECT status FROM agent_steps WHERE step_id = ? AND run_id = ? AND agent_id = ?",
        (step_id, run_id, agent_id),
    ).fetchone()
    if row is None or row["status"] != "running":
        raise ToolFailure(
            "STEP_NOT_ACTIVE",
            f"no running step {step_id!r} for agent {agent_id!r} in run {run_id!r}",
        )
