"""Golden end-to-end test: the demo scenario, at full speed, in fallback mode.

Runs the real live path in-process: generator → ingest → scoring → alert engine →
coalesced runs → orchestrator → four fallback agents acting through the harness.
Asserts the demo story holds: the planted hotspot (S1) is CONFIRMED at HIGH or above,
the small-count decoy (D1) is DOWNGRADED, and every report carries both an enforcement
and a treatment recommendation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from narcobob.api import pipeline, queries
from narcobob.api.alerts import AlertEngine
from narcobob.api.ingest import ingest
from narcobob.api.state import AppState
from narcobob.api.ws import Hub
from narcobob.common.config import SRC_DIR, get_settings
from narcobob.common.schemas import RunLog
from narcobob.engine.cells import CellGrid
from narcobob.orchestrator.worker import Worker
from narcobob.simulator.generator import Generator
from narcobob.simulator.scenario import load_scenario

BACKFILL = 60
LAST_DAY = 76
HEADINGS = (
    "## Executive summary",
    "## Escalating areas",
    "## Why these areas",
    "## What the Skeptic challenged",
    "## Recommended actions: Enforcement",
    "## Recommended actions: Treatment & prevention",
    "## Data caveats",
    "## Method note",
)


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppState]:
    for key, value in {
        "NARCOBOB_DB_PATH": str(tmp_path / "golden.db"),
        "NARCOBOB_AGENTS_MODE": "fallback",
        "NARCOBOB_ALERT_COALESCE_S": "0",
        "NARCOBOB_RECORD": "false",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()  # the harness tools read the cached settings
    yield AppState.create(get_settings())
    get_settings.cache_clear()


async def test_demo_scenario_end_to_end(state: AppState) -> None:
    scenario = load_scenario(SRC_DIR / "scenarios" / "demo_border_surge.yaml")
    scenario.auto_injections = True
    gen = Generator(scenario, CellGrid.from_bbox(scenario.area.bbox, scenario.area.h3_res), 42)
    hub, engine = Hub(None), AlertEngine()
    worker = Worker(state, hub)

    backfill = [e for day in range(BACKFILL) for e in gen.events_for_day(day)]
    for i in range(0, len(backfill), 5000):
        ingest(state, backfill[i : i + 5000])
    await pipeline.score_once(state, hub, engine)  # seeds severities, raises nothing

    runs = []
    for day in range(BACKFILL, LAST_DAY):
        ingest(state, gen.events_for_day(day))
        await pipeline.score_once(state, hub, engine)
        run_id = await pipeline.dispatch(state, hub, engine)
        if run_id is not None:
            assert await worker.execute_run(run_id) == "DONE"
            runs.append(run_id)

    conn = state.conn
    s1 = {gen.grid.cells[i] for a in gen.injections if a.spec.id == "S1" for i in a.cells}
    d1 = {gen.grid.cells[i] for a in gen.injections if a.spec.id == "D1" for i in a.cells}
    judged = conn.execute(
        "SELECT cell, verdict, final_severity FROM alerts WHERE verdict IS NOT NULL"
    )
    verdicts = [dict(r) for r in judged]

    assert runs, "no agent run was triggered"
    assert any(
        v["cell"] in s1
        and v["verdict"] == "CONFIRMED"
        and v["final_severity"] in ("HIGH", "CRITICAL")
        for v in verdicts
    ), f"S1 not confirmed: {[v for v in verdicts if v['cell'] in s1]}"
    assert any(v["cell"] in d1 and v["verdict"] == "DOWNGRADED" for v in verdicts), (
        f"D1 not downgraded: {[v for v in verdicts if v['cell'] in d1]}"
    )

    reports = conn.execute(
        "SELECT run_id, markdown, recommendations, source FROM reports"
    ).fetchall()
    assert len(reports) == len(runs)
    for r in reports:
        tracks = {rec["track"] for rec in json.loads(r["recommendations"])}
        assert tracks == {"enforcement", "treatment"}
        assert r["source"] == "fallback"
        for heading in HEADINGS:
            assert heading in r["markdown"]
        assert "simulated" in r["markdown"].lower()

    # every agent step went through the harness and was traced
    steps = conn.execute("SELECT agent_id, status, tool_calls FROM agent_steps").fetchall()
    assert len(steps) == 4 * len(runs)
    assert all(s["status"] == "fallback" and s["tool_calls"] > 0 for s in steps)
    failed_calls = conn.execute("SELECT tool, error_code FROM tool_calls WHERE ok = 0").fetchall()
    assert [dict(c) for c in failed_calls] == []

    # the observability log shows each run's four steps and all of its tool calls
    run_log = RunLog.model_validate(queries.run_log(state, runs[0]))
    assert [s.agent_id for s in run_log.steps] == ["steward", "analyst", "skeptic", "writer"]
    assert len(run_log.tool_calls) == sum(s.tool_calls for s in run_log.steps)
    assert queries.run_log(state, "no-such-run") is None
