"""Detection metrics for a replayed scenario (SPEC §12), plus naive baselines."""

from __future__ import annotations

from typing import Any

import numpy as np

from narcobob.backtest.simulate import GAP_SHARE, Replay
from narcobob.engine.components import WINDOW

ALERT_LEVELS = ("HIGH", "CRITICAL")


def _truth_cells(rep: Replay) -> set[int]:
    return {c for a in rep.world.generator.injections if a.spec.id in ("S1", "S2") for c in a.cells}


def _decoy_cells(rep: Replay) -> dict[str, set[int]]:
    """Cells each decoy could plausibly trip. D2 (outage) affects cells that rely on the source."""
    world = rep.world
    decoys: dict[str, set[int]] = {}
    for a in world.generator.injections:
        if not a.spec.id.startswith("D"):
            continue
        if a.spec.kind == "outage" and a.spec.source in world.sources:
            s = world.sources.index(a.spec.source)
            totals = world.cell_source.sum(axis=2)
            share = totals[:, s] / np.maximum(totals.sum(axis=1), 1)
            decoys[a.spec.id] = set(np.nonzero(share >= GAP_SHARE)[0].tolist())
        else:
            decoys[a.spec.id] = set(a.cells)
    return decoys


def _first_day(rep: Replay, cells: set[int], onset: int, level: str) -> int | None:
    names = {rep.world.grid.cells[c] for c in cells}
    for rec in rep.days:
        if rec.day < onset:
            continue
        for c in cells:
            if rec.result.severity[c] == level or (
                level == "HIGH" and rec.result.severity[c] == "CRITICAL"
            ):
                return rec.day - onset
    del names
    return None


def _precision_at_5(rep: Replay, truth: set[int], onset: int) -> float | None:
    values = [
        len(set(np.argsort(-rec.result.score)[:5].tolist()) & truth) / 5
        for rec in rep.days
        if rec.day >= onset + WINDOW // 2
    ]
    return round(float(np.mean(values)), 3) if values else None


def _baseline_first_day(
    rep: Replay, type_idx: list[int], truth: set[int], onset: int
) -> int | None:
    """Naive ranking by raw recent counts: first day a truth cell reaches the top 5."""
    counts = rep.world.counts
    for day in range(onset, counts.shape[2]):
        raw = counts[:, type_idx, max(0, day + 1 - WINDOW) : day + 1].sum(axis=(1, 2))
        if set(np.argsort(-raw, kind="stable")[:5].tolist()) & truth:
            return day - onset
    return None


def _baseline_hits(rep: Replay, type_idx: list[int], cells: set[int], start: int) -> bool:
    counts = rep.world.counts
    for day in range(start, counts.shape[2]):
        raw = counts[:, type_idx, max(0, day + 1 - WINDOW) : day + 1].sum(axis=(1, 2))
        if set(np.argsort(-raw, kind="stable")[:5].tolist()) & cells:
            return True
    return False


def scenario_metrics(rep: Replay) -> dict[str, Any]:
    gen = rep.world.generator
    s1 = next((a for a in gen.injections if a.spec.id == "S1"), None)
    out: dict[str, Any] = {}
    if s1 is not None:
        truth = _truth_cells(rep)
        onset = s1.start_day
        out["detection"] = {
            "onset_day": onset,
            "days_to_high": _first_day(rep, set(s1.cells), onset, "HIGH"),
            "days_to_critical": _first_day(rep, set(s1.cells), onset, "CRITICAL"),
            "precision_at_5": _precision_at_5(rep, truth, onset),
            "s1_final_verdicts": sorted(
                {a.verdict.verdict for a in rep.alerts if rep.world.grid.index[a.cell] in s1.cells}
            ),
        }
        out["baselines"] = {
            "raw_overdose_rank_days_to_top5": _baseline_first_day(rep, [0], set(s1.cells), onset),
            "raw_seizure_rank_days_to_top5": _baseline_first_day(rep, [1], set(s1.cells), onset),
        }
    decoys: dict[str, Any] = {}
    for decoy_id, cells in _decoy_cells(rep).items():
        spec = next(a for a in gen.injections if a.spec.id == decoy_id)
        window = range(spec.start_day, spec.start_day + 3 * WINDOW)
        hits = [a for a in rep.alerts if a.day in window and rep.world.grid.index[a.cell] in cells]
        decoys[decoy_id] = {
            "kind": spec.spec.kind,
            "alerts_pre_skeptic": len(hits),
            "alerts_post_skeptic": sum(a.verdict.final_severity in ALERT_LEVELS for a in hits),
            "verdicts": sorted({a.verdict.verdict for a in hits}),
            "raw_seizure_rank_flags_it": _baseline_hits(rep, [1], cells, spec.start_day),
        }
    out["decoys"] = decoys
    return out


def false_alarm_metrics(rep: Replay) -> dict[str, Any]:
    days = len(rep.days)
    months = max(days / 30, 1e-9)
    pre = sum(a.severity in ALERT_LEVELS for a in rep.alerts)
    post = sum(a.verdict.final_severity in ALERT_LEVELS for a in rep.alerts)
    critical = sum(a.severity == "CRITICAL" for a in rep.alerts)
    return {
        "sim_days": days,
        "alerts_per_month_pre_skeptic": round(pre / months, 2),
        "alerts_per_month_post_skeptic": round(post / months, 2),
        "critical_alerts": critical,
    }
