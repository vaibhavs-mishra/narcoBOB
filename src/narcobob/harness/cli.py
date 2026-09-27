"""`narcobob-harness`: call any harness tool from the terminal, exactly as an agent would.

    uv run narcobob-harness list
    uv run narcobob-harness call get_support --as skeptic --run <run_id> \\
        --json '{"cells": ["87424d225ffffff"]}'

A throwaway `running` step is created for the call (the harness only authorises calls
inside an active step), so every check — allowlist, budget, validation — applies.
"""

from __future__ import annotations

import argparse
import json
import sys

from narcobob.common.config import get_settings
from narcobob.common.db import init_db
from narcobob.common.ids import new_id, wall_now
from narcobob.harness.authz import ALLOWLIST
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

TOOLS = {
    m.NAME: m
    for m in (
        get_run_context,
        get_data_quality,
        get_cell_scores,
        get_cell_timeseries,
        get_neighbors,
        get_support,
        run_sensitivity,
        get_findings,
        submit_findings,
        submit_report,
    )
}


def main() -> None:
    parser = argparse.ArgumentParser(prog="narcobob-harness", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list tools and which agents may call them")
    call = sub.add_parser("call", help="call one tool")
    call.add_argument("tool", choices=sorted(TOOLS))
    call.add_argument(
        "--as", dest="agent", required=True, choices=["steward", "analyst", "skeptic", "writer"]
    )
    call.add_argument("--run", dest="run_id", help="run id (default: the latest run)")
    call.add_argument("--json", dest="args", default="{}", help="tool arguments as JSON")
    ns = parser.parse_args()

    if ns.command == "list":
        for name in TOOLS:
            print(f"{name:<22} {', '.join(sorted(ALLOWLIST[name]))}")
        return

    conn = init_db(get_settings().db_file)
    run_id = ns.run_id
    if run_id is None:
        row = conn.execute("SELECT run_id FROM agent_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        if row is None:
            sys.exit("no agent runs yet: pass --run, or wait for an alert")
        run_id = row["run_id"]
    step_id = f"cli-{new_id()}"
    conn.execute(
        "INSERT INTO agent_steps(step_id, run_id, agent_id, status, source, wall_started_at,"
        " log) VALUES (?,?,?,?,?,?,?)",
        (step_id, run_id, ns.agent, "running", "fallback", wall_now(), "narcobob-harness CLI"),
    )
    conn.commit()
    try:
        tool = TOOLS[ns.tool]
        ctx = CallContext(run_id=run_id, agent_id=ns.agent, step_id=step_id, source="fallback")
        print(
            json.dumps(
                execute(conn, ctx, tool.NAME, tool.VERSION, tool.run, json.loads(ns.args)),
                indent=2,
                default=str,
            )
        )
    finally:
        conn.execute("DELETE FROM tool_calls WHERE step_id = ?", (step_id,))
        conn.execute("DELETE FROM agent_steps WHERE step_id = ?", (step_id,))
        conn.commit()
