from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from narcobob.common.db import init_db
from narcobob.harness.envelope import CallContext

CELL = "87424d225ffffff"


def add_step(conn: sqlite3.Connection, run_id: str, agent_id: str, status: str = "running") -> str:
    step_id = f"{run_id}-{agent_id}"
    conn.execute(
        "INSERT INTO agent_steps(step_id, run_id, agent_id, status, wall_started_at)"
        " VALUES (?,?,?,?,?)",
        (step_id, run_id, agent_id, status, "2026-09-27T00:00:00Z"),
    )
    conn.commit()
    return step_id


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = init_db(tmp_path / "h.db")
    c.execute(
        "INSERT INTO alerts(alert_id, cell, severity, score, reason, sim_ts, wall_created_at)"
        " VALUES ('a1', ?, 'HIGH', 80, 'entered HIGH', '2026-08-01T00:00:00Z', 'w')",
        (CELL,),
    )
    c.execute(
        "INSERT INTO agent_runs(run_id, status, alert_ids, cells, data_version)"
        " VALUES ('r1', 'RUNNING', ?, ?, 3)",
        (json.dumps(["a1"]), json.dumps([CELL])),
    )
    c.commit()
    return c


def ctx_for(conn: sqlite3.Connection, agent_id: str) -> CallContext:
    return CallContext(run_id="r1", agent_id=agent_id, step_id=add_step(conn, "r1", agent_id))
