"""Ingest, alert engine and coalescing, tested without the network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from narcobob.api.alerts import AlertEngine, create_run
from narcobob.api.ingest import ingest
from narcobob.api.state import AppState
from narcobob.common.config import Settings
from narcobob.common.db import data_version


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    settings = Settings(NARCOBOB_DB_PATH=tmp_path / "t.db", NARCOBOB_ALERT_COALESCE_S=0)  # type: ignore[call-arg]
    return AppState.create(settings)


def event(i: int, **kw: Any) -> dict[str, Any]:
    base = {"event_id": f"e{i}", "type": "overdose", "lat": 31.55, "lon": 74.62,
            "ts": "2026-08-14T03:20:00Z", "source": "hospital:civil_amritsar"}  # fmt: skip
    return base | kw


def test_ingest_is_idempotent(state: AppState) -> None:
    first, _ = ingest(state, [event(1), event(2)])
    again, _ = ingest(state, [event(1), event(2), event(3)])
    assert (first.accepted, first.duplicates) == (2, 0)
    assert (again.accepted, again.duplicates) == (1, 2)
    assert data_version(state.conn) == 2
    row = state.conn.execute("SELECT cell, bucket FROM events WHERE event_id = 'e1'").fetchone()
    assert row["cell"] == "87424d225ffffff"
    assert row["bucket"] == state.bucket_of(state.epoch0.replace(month=8, day=14))


def test_ingest_rejects_out_of_area_and_invalid(state: AppState) -> None:
    result, _ = ingest(state, [event(1, lat=28.6, lon=77.2), event(2, type="theft"), event(3)])
    reasons = {r.event_id: r.reason for r in result.rejected}
    assert reasons["e1"] == "OUT_OF_AREA"
    assert reasons["e2"].startswith("VALIDATION_ERROR")
    assert result.accepted == 1


def scores(**severity: str) -> dict[str, dict[str, object]]:
    return {
        c: {"severity": s, "score": 90, "sim_ts": "2026-08-14T00:00:00Z"}
        for c, s in severity.items()
    }


def test_alert_engine_warm_up_cooldown_and_escalation(state: AppState) -> None:
    engine = AlertEngine()
    assert engine.check(state, scores(a="HIGH", b="NORMAL")) == []  # first pass only seeds
    assert engine.check(state, scores(a="HIGH", b="NORMAL")) == []  # already HIGH: no alert
    raised = engine.check(state, scores(a="HIGH", b="HIGH"))
    assert [x["cell"] for x in raised] == ["b"] and raised[0]["reason"] == "entered HIGH"
    engine.check(state, scores(a="HIGH", b="WATCH"))
    assert engine.check(state, scores(a="HIGH", b="HIGH")) == []  # cooldown
    escalated = engine.check(state, scores(a="HIGH", b="CRITICAL"))
    assert [x["reason"] for x in escalated] == ["escalated to CRITICAL"]  # bypasses cooldown


def test_alerts_coalesce_into_one_run(state: AppState) -> None:
    engine = AlertEngine()
    engine.check(state, scores(a="NORMAL", b="NORMAL"))
    engine.check(state, scores(a="HIGH", b="CRITICAL"))
    batch = engine.take_batch(state)
    assert batch is not None and len(batch) == 2
    assert engine.take_batch(state) is None
    run = create_run(state, batch, 7)
    assert run["cells"] == ["a", "b"] and run["status"] == "QUEUED"
    linked = state.conn.execute("SELECT COUNT(*) FROM alerts WHERE run_id = ?", (run["run_id"],))
    assert linked.fetchone()[0] == 2
