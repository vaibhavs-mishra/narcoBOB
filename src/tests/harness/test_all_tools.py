"""Contract tests for every MCP tool: happy path, VALIDATION_ERROR, FORBIDDEN_TOOL."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import h3
import pytest

from narcobob.api import pipeline
from narcobob.api.alerts import AlertEngine
from narcobob.api.ingest import ingest
from narcobob.api.state import AppState
from narcobob.api.ws import Hub
from narcobob.common.config import SRC_DIR, get_settings
from narcobob.common.ids import new_id
from narcobob.engine.cells import CellGrid
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
from narcobob.simulator.generator import Generator
from narcobob.simulator.scenario import load_scenario

CELL = h3.latlng_to_cell(31.55, 74.62, 7)
TOOLS = [
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
]


@pytest.fixture(scope="module")
def conn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[sqlite3.Connection]:
    """A database with 40 sim-days of scored data and one run over CELL."""
    path: Path = tmp_path_factory.mktemp("tools") / "t.db"
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCOBOB_DB_PATH", str(path))
    get_settings.cache_clear()
    state = AppState.create(get_settings())
    scenario = load_scenario(SRC_DIR / "scenarios" / "demo_border_surge.yaml")
    gen = Generator(scenario, CellGrid.from_bbox(scenario.area.bbox, 7), 1)
    ingest(state, [e for d in range(40) for e in gen.events_for_day(d)])

    import asyncio

    asyncio.run(pipeline.score_once(state, Hub(None), AlertEngine()))
    state.conn.execute(
        "INSERT INTO agent_runs(run_id, status, alert_ids, cells, data_version)"
        " VALUES ('r1', 'RUNNING', '[]', ?, 1)",
        (json.dumps([CELL]),),
    )
    state.conn.commit()
    yield state.conn
    mp.undo()
    get_settings.cache_clear()


def call(conn: sqlite3.Connection, tool: ModuleType, agent: str, **args: Any) -> dict[str, Any]:
    step = new_id()
    conn.execute(
        "INSERT OR IGNORE INTO agent_steps(step_id, run_id, agent_id, status, wall_started_at)"
        " VALUES (?, 'r1', ?, 'running', 'w')",
        (step, agent),
    )
    conn.commit()
    ctx = CallContext(run_id="r1", agent_id=agent, step_id=step, source="fallback")
    return execute(conn, ctx, tool.NAME, tool.VERSION, tool.run, args)


def allowed(tool: ModuleType) -> str:
    if tool is submit_findings:
        return "steward"  # the happy-path payload is a data_quality finding
    return sorted(ALLOWLIST[tool.NAME])[0]


def forbidden(tool: ModuleType) -> str | None:
    others = {"steward", "analyst", "skeptic", "writer"} - ALLOWLIST[tool.NAME]
    return sorted(others)[0] if others else None


HAPPY: dict[str, dict[str, Any]] = {
    "get_run_context": {},
    "get_data_quality": {"cells": [CELL]},
    "get_cell_scores": {"cells": [CELL]},
    "get_cell_timeseries": {"cell": CELL, "buckets": 14},
    "get_neighbors": {"cell": CELL, "k": 2},
    "get_support": {"cells": [CELL]},
    "run_sensitivity": {"cells": [CELL], "samples": 10},
    "get_findings": {},
    "submit_findings": {
        "idempotency_key": "k1",
        "findings": [
            {
                "kind": "data_quality",
                "payload": {
                    "cell": CELL,
                    "issue": "ok",
                    "detail": "fine",
                    "affects_recent_window": False,
                },
            }
        ],
    },
    "submit_report": {
        "idempotency_key": "k1",
        "report": {
            "markdown": "# Brief",
            "recommendations": [
                {"track": "enforcement", "cells": [CELL], "action": "a", "priority": "monitor"},
                {"track": "treatment", "cells": [CELL], "action": "b", "priority": "monitor"},
            ],
        },
    },
}
BAD: dict[str, dict[str, Any]] = {
    "get_data_quality": {"cells": ["not-a-cell"]},
    "get_cell_scores": {},
    "get_cell_timeseries": {"cell": CELL, "buckets": 500},
    "get_neighbors": {"cell": CELL, "k": 3},
    "get_support": {"cells": []},
    "run_sensitivity": {"cells": [CELL], "samples": 1},
    "get_findings": {"kind": "gossip"},
    "submit_findings": {"idempotency_key": "k2", "findings": []},
    "submit_report": {
        "idempotency_key": "k3",
        "report": {
            "markdown": "x",
            "recommendations": [
                {"track": "enforcement", "cells": [], "action": "a", "priority": "monitor"}
            ],
        },
    },
}


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.NAME)
def test_happy_path(conn: sqlite3.Connection, tool: ModuleType) -> None:
    out = call(conn, tool, allowed(tool), **HAPPY[tool.NAME])
    assert out["ok"], out["error"]
    assert out["meta"]["tool"] == tool.NAME and out["meta"]["duration_ms"] >= 0


@pytest.mark.parametrize("tool", [t for t in TOOLS if t.NAME in BAD], ids=lambda t: t.NAME)
def test_validation_error(conn: sqlite3.Connection, tool: ModuleType) -> None:
    out = call(conn, tool, allowed(tool), **BAD[tool.NAME])
    assert not out["ok"] and out["error"]["code"] == "VALIDATION_ERROR", out


@pytest.mark.parametrize("tool", [t for t in TOOLS if forbidden(t)], ids=lambda t: t.NAME)
def test_forbidden_agent(conn: sqlite3.Connection, tool: ModuleType) -> None:
    agent = forbidden(tool)
    assert agent is not None
    out = call(conn, tool, agent, **HAPPY[tool.NAME])
    assert out["error"]["code"] == "FORBIDDEN_TOOL"


def test_report_needs_both_tracks_and_is_single(conn: sqlite3.Connection) -> None:
    out = call(conn, submit_report, "writer", **BAD["submit_report"])
    assert "treatment" in out["error"]["message"]
    again = call(conn, submit_report, "writer", **HAPPY["submit_report"])
    assert again["ok"]  # same key + payload → idempotent
    other = dict(HAPPY["submit_report"], idempotency_key="different")
    assert call(conn, submit_report, "writer", **other)["error"]["code"] == "CONFLICT"


def test_sensitivity_and_support_shapes(conn: sqlite3.Connection) -> None:
    sens = call(conn, run_sensitivity, "skeptic", cells=[CELL])["data"]["cells"][0]
    assert 0.0 <= sens["stability"] <= 1.0 and sens["min_score"] <= sens["max_score"]
    sup = call(conn, get_support, "skeptic", cells=[CELL])["data"]["cells"][0]
    assert sum(sup["by_source"].values()) == sum(sup["by_type"].values())
    assert 0.0 <= sup["top_source_share"] <= 1.0


def test_evidence_is_as_of_the_alert(conn: sqlite3.Connection) -> None:
    """Agents review a cell as it was when it alerted, even after the world moved on."""
    old_end = "2026-07-26T00:00:00Z"  # end of sim day 24; the data runs to day 39
    conn.execute(
        "INSERT INTO agent_runs(run_id, status, alert_ids, cells, data_version)"
        " VALUES ('r_old', 'RUNNING', '[\"a_old\"]', ?, 1)",
        (json.dumps([CELL]),),
    )
    conn.execute(
        "INSERT INTO alerts(alert_id, cell, severity, score, reason, run_id, sim_ts,"
        " wall_created_at) VALUES ('a_old', ?, 'HIGH', 90, 'entered HIGH', 'r_old', ?, 'w')",
        (CELL, old_end),
    )
    step = new_id()
    conn.execute(
        "INSERT INTO agent_steps(step_id, run_id, agent_id, status, wall_started_at)"
        " VALUES (?, 'r_old', 'analyst', 'running', 'w')",
        (step,),
    )
    conn.commit()
    ctx = CallContext(run_id="r_old", agent_id="analyst", step_id=step, source="fallback")
    then = execute(conn, ctx, get_cell_scores.NAME, "1.0", get_cell_scores.run, {"cells": [CELL]})
    now = call(conn, get_cell_scores, "analyst", cells=[CELL])
    assert then["data"]["cells"][0]["sim_ts"] == old_end
    assert now["data"]["cells"][0]["sim_ts"] > old_end
    ctx_run = execute(conn, ctx, get_run_context.NAME, "1.0", get_run_context.run, {})
    assert ctx_run["data"]["as_of"] == {CELL: old_end}
