"""Contract-level checks for the shared schemas, config and database."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from narcobob.common.config import Settings
from narcobob.common.db import data_version, init_db, kv_get, kv_set
from narcobob.common.schemas import Event, FindingIn, ReportIn

EVENT = {
    "event_id": "e1",
    "type": "overdose",
    "lat": 31.5,
    "lon": 74.9,
    "ts": "2026-08-14T03:20:00Z",
    "source": "hospital:civil_tarntaran",
}


def test_event_accepts_contract_example() -> None:
    assert Event.model_validate(EVENT).type == "overdose"


@pytest.mark.parametrize(
    "patch",
    [{"type": "theft"}, {"lat": 91}, {"source": "Hospital civil"}, {"ts": "yesterday"}],
)
def test_event_rejects_invalid_fields(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(EVENT | patch)


def rec(track: str) -> dict[str, object]:
    return {"track": track, "cells": ["872a1072bffffff"], "action": "a", "priority": "monitor"}


def test_report_needs_both_recommendation_tracks() -> None:
    with pytest.raises(ValidationError):
        ReportIn.model_validate({"markdown": "x", "recommendations": [rec("enforcement")]})
    ok = ReportIn.model_validate(
        {"markdown": "x", "recommendations": [rec("enforcement"), rec("treatment")]}
    )
    assert len(ok.recommendations) == 2


def test_finding_payload_validated_by_kind() -> None:
    bad = FindingIn(kind="verdict", payload={"cell": "x"})
    with pytest.raises(ValidationError):
        bad.parsed()


def test_settings_parse_csv_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARCOBOB_WEIGHTS", "0.4,0.2,0.2,0.2")
    monkeypatch.setenv("NARCOBOB_THRESHOLDS", "50,70,90")
    settings = Settings()
    assert settings.weights == (0.4, 0.2, 0.2, 0.2)
    assert settings.thresholds == (50, 70, 90)


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "t.db"
    init_db(path).close()
    conn = init_db(path)
    assert data_version(conn) == 0
    kv_set(conn, "sim_now", "2026-08-14T00:00:00Z")
    assert kv_get(conn, "sim_now") == "2026-08-14T00:00:00Z"
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
