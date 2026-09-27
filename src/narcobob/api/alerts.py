"""The alert engine: turns severity changes into alerts, and batches alerts into agent runs.

- An alert fires when a cell enters HIGH/CRITICAL or escalates (`engine.alerting`).
- The first scoring pass only seeds the state: cells that were already hot when the
  system started (the end of the backfill) do not all alert at once.
- Per-cell cooldown (wall seconds) stops a flickering cell from re-alerting;
  escalations bypass it.
- Alerts raised within NARCOBOB_ALERT_COALESCE_S are gathered into one agent run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from narcobob.api.state import AppState
from narcobob.common.ids import new_id, wall_now
from narcobob.engine.alerting import alert_reason, bypasses_cooldown


@dataclass
class AlertEngine:
    previous: dict[str, str] | None = None
    last_alert_at: dict[str, float] = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)  # alert ids awaiting a run
    pending_since: float | None = None

    def reset(self) -> None:
        self.previous = None
        self.last_alert_at.clear()
        self.pending.clear()
        self.pending_since = None

    def check(
        self, state: AppState, scores: dict[str, dict[str, object]]
    ) -> list[dict[str, object]]:
        """Compare new severities with the previous pass; insert and return new alerts."""
        current = {cell: str(s["severity"]) for cell, s in scores.items()}
        if self.previous is None:
            self.previous = current
            return []
        now = time.monotonic()
        cooldown = state.settings.alert_cooldown_s
        raised: list[dict[str, object]] = []
        for cell, severity in current.items():
            reason = alert_reason(self.previous.get(cell, "NORMAL"), severity)
            if reason is None:
                continue
            last = self.last_alert_at.get(cell)
            if last is not None and now - last < cooldown and not bypasses_cooldown(reason):
                continue
            self.last_alert_at[cell] = now
            s = scores[cell]
            alert: dict[str, object] = {
                "alert_id": new_id(), "cell": cell, "severity": severity,
                "score": s["score"], "reason": reason, "run_id": None,
                "final_severity": None, "verdict": None, "sim_ts": s["sim_ts"],
                "wall_created_at": wall_now(),
            }  # fmt: skip
            state.conn.execute(
                "INSERT INTO alerts(alert_id, cell, severity, score, reason, sim_ts,"
                " wall_created_at) VALUES (?,?,?,?,?,?,?)",
                (alert["alert_id"], cell, severity, s["score"], reason, s["sim_ts"],
                 alert["wall_created_at"]),
            )  # fmt: skip
            raised.append(alert)
            self.pending.append(str(alert["alert_id"]))
            self.pending_since = self.pending_since or now
        state.conn.commit()
        self.previous = current
        return raised

    def take_batch(self, state: AppState) -> list[str] | None:
        """Alert ids for a new run, once the oldest pending alert has waited long enough."""
        if not self.pending or self.pending_since is None:
            return None
        if time.monotonic() - self.pending_since < state.settings.alert_coalesce_s:
            return None
        batch, self.pending, self.pending_since = self.pending, [], None
        return batch


def create_run(state: AppState, alert_ids: list[str], data_version: int) -> dict[str, object]:
    """Insert a QUEUED run for these alerts and link the alerts to it."""
    marks = ",".join("?" * len(alert_ids))
    rows = state.conn.execute(
        f"SELECT alert_id, cell FROM alerts WHERE alert_id IN ({marks})", alert_ids
    ).fetchall()
    cells = sorted({r["cell"] for r in rows})
    run_id = new_id()
    state.conn.execute(
        "INSERT INTO agent_runs(run_id, status, alert_ids, cells, data_version) VALUES (?,?,?,?,?)",
        (run_id, "QUEUED", json.dumps(alert_ids), json.dumps(cells), data_version),
    )
    state.conn.execute(
        f"UPDATE alerts SET run_id = ? WHERE alert_id IN ({marks})", [run_id, *alert_ids]
    )
    state.conn.commit()
    return {"run_id": run_id, "status": "QUEUED", "cells": cells, "wall_started_at": None,
            "wall_finished_at": None, "steps": []}  # fmt: skip
