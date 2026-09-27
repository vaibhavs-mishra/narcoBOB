"""M1 gate: one real headless Bob agent call through the MCP harness.

Creates a synthetic run with an active Steward step, runs the `narcobob-steward` mode
headless, then checks that a finding row arrived through `submit_findings`.
Starts `narcobob-mcp` itself if it is not already running.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time

from narcobob.common.config import SRC_DIR, get_settings
from narcobob.common.db import data_version, init_db
from narcobob.common.ids import new_id, wall_now
from narcobob.common.logging import setup_logging
from narcobob.orchestrator.bob_runner import run_agent
from narcobob.orchestrator.prompts import build_prompt

SMOKE_CELL = "87424d225ffffff"  # H3 res-7 cell at the S1 surge site (31.55, 74.62)


def port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    setup_logging()
    settings = get_settings()
    conn = init_db(settings.db_file)

    server = None
    if not port_open(settings.mcp_port):
        server = subprocess.Popen(["uv", "run", "narcobob-mcp"], cwd=SRC_DIR)
        for _ in range(50):
            if port_open(settings.mcp_port):
                break
            time.sleep(0.2)

    run_id, step_id, alert_id = f"smoke-{new_id()}", new_id(), new_id()
    now = wall_now()
    conn.execute(
        "INSERT INTO alerts(alert_id, cell, severity, score, reason, run_id, sim_ts,"
        " wall_created_at) VALUES (?,?,?,?,?,?,?,?)",
        (alert_id, SMOKE_CELL, "HIGH", 80, "smoke test", run_id, now, now),
    )
    conn.execute(
        "INSERT INTO agent_runs(run_id, status, alert_ids, cells, data_version, wall_started_at)"
        " VALUES (?,?,?,?,?,?)",
        (run_id, "RUNNING", json.dumps([alert_id]), json.dumps([SMOKE_CELL]),
         data_version(conn), now),
    )  # fmt: skip
    conn.execute(
        "INSERT INTO agent_steps(step_id, run_id, agent_id, status, source, wall_started_at)"
        " VALUES (?,?,?,?,?,?)",
        (step_id, run_id, "steward", "running", "bob", now),
    )
    conn.commit()

    try:
        prompt = build_prompt("steward", run_id, step_id, [SMOKE_CELL])
        result = asyncio.run(run_agent(settings, "steward", prompt))
    finally:
        if server is not None:
            server.terminate()

    rows = conn.execute(
        "SELECT kind, payload FROM findings WHERE step_id = ?", (step_id,)
    ).fetchall()
    calls = conn.execute(
        "SELECT tool, ok, error_code FROM tool_calls WHERE step_id = ? ORDER BY wall_at",
        (step_id,),
    ).fetchall()
    status = "done" if rows else "failed"
    conn.execute(
        "UPDATE agent_steps SET status = ?, log = ?, wall_finished_at = ? WHERE step_id = ?",
        (status, result.log, wall_now(), step_id),
    )
    conn.execute("UPDATE agent_runs SET status = 'DONE' WHERE run_id = ?", (run_id,))
    conn.commit()

    print(f"exit={result.exit_code} timed_out={result.timed_out} wall={result.duration_s:.1f}s")
    for c in calls:
        print(f"  tool {c['tool']:<18} ok={c['ok']} {c['error_code'] or ''}")
    for r in rows:
        print(f"  finding {r['kind']}: {r['payload'][:160]}")
    if not rows:
        print("FAIL: no finding written. Bob output tail:\n" + result.log[-3000:])
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
