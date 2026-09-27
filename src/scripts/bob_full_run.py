"""M5 gate: one complete agent run (Steward → Analyst → Skeptic → Writer) on IBM Bob.

Builds a fresh database from the demo scenario up to the first run that covers the
planted hotspot (S1), starts `narcobob-mcp` on that database, and lets the real
orchestrator run the four Bob agents. Prints each step's source and the report.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time

from narcobob.common.config import SRC_DIR, get_settings

DB = "var/bob_full_run.db"


def port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


async def main() -> int:
    from narcobob.api import pipeline
    from narcobob.api.alerts import AlertEngine
    from narcobob.api.ingest import ingest
    from narcobob.api.state import AppState
    from narcobob.api.ws import Hub
    from narcobob.engine.cells import CellGrid
    from narcobob.orchestrator.worker import Worker
    from narcobob.simulator.generator import Generator
    from narcobob.simulator.scenario import load_scenario

    settings = get_settings()
    for suffix in ("", "-wal", "-shm"):
        (SRC_DIR / f"{DB}{suffix}").unlink(missing_ok=True)
    state = AppState.create(settings)
    scenario = load_scenario(settings.scenario_file)
    scenario.auto_injections = True
    gen = Generator(scenario, CellGrid.from_bbox(scenario.area.bbox, scenario.area.h3_res), 42)
    s1 = {gen.grid.cells[i] for a in gen.injections if a.spec.id == "S1" for i in a.cells}
    hub, engine = Hub(None), AlertEngine()
    events = [e for day in range(60) for e in gen.events_for_day(day)]
    for i in range(0, len(events), 5000):
        ingest(state, events[i : i + 5000])
    await pipeline.score_once(state, hub, engine)

    run_id = None
    for day in range(60, 80):
        ingest(state, gen.events_for_day(day))
        await pipeline.score_once(state, hub, engine)
        candidate = await pipeline.dispatch(state, hub, engine)
        cells = state.conn.execute("SELECT cells FROM agent_runs WHERE run_id = ?", (candidate,))
        row = cells.fetchone()
        if candidate and row and s1 & set(__import__("json").loads(row["cells"])):
            run_id = candidate
            break
    if run_id is None:
        print("FAIL: no run covering S1")
        return 1
    print(f"run {run_id} on sim day {day}: cells {row['cells']}")

    server = None
    if not port_open(settings.mcp_port):
        server = subprocess.Popen(["uv", "run", "narcobob-mcp"], cwd=SRC_DIR, env=os.environ.copy())
        while not port_open(settings.mcp_port):
            time.sleep(0.2)
    started = time.monotonic()
    try:
        status = await Worker(state, hub).execute_run(run_id)
    finally:
        if server is not None:
            server.terminate()
    print(f"status {status} in {time.monotonic() - started:.0f}s")
    for s in state.conn.execute(
        "SELECT agent_id, status, source, attempt, tool_calls FROM agent_steps WHERE run_id = ?"
        " ORDER BY wall_started_at", (run_id,)
    ):  # fmt: skip
        print(f"  {s['agent_id']:<8} {s['status']:<8} source={s['source']} attempt={s['attempt']}"
              f" tool_calls={s['tool_calls']}")  # fmt: skip
    for a in state.conn.execute("SELECT cell, severity, verdict, final_severity FROM alerts"
                                " WHERE run_id = ?", (run_id,)):  # fmt: skip
        print(f"  alert {a['cell']} {a['severity']} → {a['verdict']} {a['final_severity']}")
    report = state.conn.execute("SELECT markdown, source FROM reports WHERE run_id = ?", (run_id,))
    r = report.fetchone()
    print(
        f"\n--- report (source={r['source'] if r else None}) ---\n{r['markdown'] if r else 'none'}"
    )
    return 0 if status == "DONE" else 1


if __name__ == "__main__":
    os.environ.setdefault("NARCOBOB_DB_PATH", DB)
    os.environ["NARCOBOB_AGENTS_MODE"] = "bob"
    os.environ["NARCOBOB_ALERT_COALESCE_S"] = "0"
    os.environ["NARCOBOB_RECORD"] = "false"
    get_settings.cache_clear()
    sys.exit(asyncio.run(main()))
