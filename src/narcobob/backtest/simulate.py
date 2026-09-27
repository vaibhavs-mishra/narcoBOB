"""Run a scenario offline: every sim-day through the engine, alert rules and fallback Skeptic.

This is the same pipeline as the live system minus the network: generator → dense counts →
`score_cells` → `alert_reason` → Skeptic rules. Nothing here is specific to the backtest
except that injections are scheduled automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import h3
import numpy as np
import numpy.typing as npt

from narcobob.common.config import Settings
from narcobob.engine.alerting import alert_reason, bypasses_cooldown
from narcobob.engine.cells import CellGrid
from narcobob.engine.components import WINDOW
from narcobob.engine.composite import ScoreResult, score_cells
from narcobob.engine.quality import source_gaps, top_source_share
from narcobob.engine.sensitivity import sensitivity
from narcobob.orchestrator.skeptic_rules import CellFacts, SkepticVerdict, judge
from narcobob.simulator.generator import TYPES, Generator
from narcobob.simulator.scenario import Scenario

Floats = npt.NDArray[np.float64]
HISTORY = 60  # buckets fed to the engine, as in live mode
WARM_UP = 35  # the engine's 28-bucket baseline + 7-bucket window
GAP_SHARE = 0.2  # a gap matters to a cell if that source carried ≥ 20% of its prior events


@dataclass
class World:
    grid: CellGrid
    generator: Generator
    sources: list[str]
    counts: Floats  # [cell, type, day]
    cell_source: Floats  # [cell, source, day]


@dataclass
class AlertRecord:
    day: int
    cell: str
    severity: str
    reason: str
    verdict: SkepticVerdict


@dataclass
class DayRecord:
    day: int
    result: ScoreResult


@dataclass
class Replay:
    world: World
    days: list[DayRecord] = field(default_factory=list)
    alerts: list[AlertRecord] = field(default_factory=list)


def build_world(scenario: Scenario, seed: int, n_days: int) -> World:
    grid = CellGrid.from_bbox(scenario.area.bbox, scenario.area.h3_res)
    gen = Generator(scenario, grid, seed)
    sources = [f"hospital:{s.id}" for s in scenario.sources.hospital] + [
        f"police:{s.id}" for s in scenario.sources.police
    ]
    src_index = {s: i for i, s in enumerate(sources)}
    counts = np.zeros((grid.n, len(TYPES), n_days))
    cell_source = np.zeros((grid.n, len(sources), n_days))
    for day in range(n_days):
        for e in gen.events_for_day(day):
            cell = grid.index.get(h3.latlng_to_cell(e["lat"], e["lon"], scenario.area.h3_res))
            if cell is None:
                continue
            counts[cell, TYPES.index(e["type"]), day] += 1
            cell_source[cell, src_index[e["source"]], day] += 1
    return World(grid, gen, sources, counts, cell_source)


def _log_growth(series: Floats) -> Floats:
    recent = series[..., -WINDOW:].sum(axis=-1)
    prior = series[..., -2 * WINDOW : -WINDOW].sum(axis=-1)
    result: Floats = np.log((recent + 1) / (prior + 1))
    return result


def cell_facts(
    world: World,
    day: int,
    result: ScoreResult,
    cells: list[int],
    weights: tuple[float, float, float, float],
    high: int,
) -> list[CellFacts]:
    lo = max(0, day + 1 - HISTORY)
    counts = world.counts[cells, :, lo : day + 1]
    cs = world.cell_source[:, :, lo : day + 1]
    n_buckets = cs.shape[2]

    per_source = cs.sum(axis=0)
    recent_gaps = {g.source for g in source_gaps(per_source) if g.to_bucket >= n_buckets - WINDOW}
    prior = cs[cells, :, -2 * WINDOW : -WINDOW].sum(axis=2)
    prior_share = prior / np.maximum(prior.sum(axis=1, keepdims=True), 1)
    _, share = top_source_share(cs[cells, :, -WINDOW:].sum(axis=2))
    stab = sensitivity(result.z_matrix()[cells], weights, high, seed=day)
    od_growth = _log_growth(counts[:, 0, :])
    enf_growth = _log_growth(counts[:, 1, :] + counts[:, 2, :])

    facts = []
    for k, c in enumerate(cells):
        gap = any(prior_share[k, s] >= GAP_SHARE for s in recent_gaps)
        facts.append(
            CellFacts(
                cell=world.grid.cells[c],
                engine_severity=result.severity[c],
                support=int(result.support[c]),
                confidence=result.confidence[c],
                stability=stab[k].stability,
                gap_in_recent_window=gap,
                od_growth=float(od_growth[k]),
                enforcement_growth=float(enf_growth[k]),
                top_source_share=float(share[k]),
            )
        )
    return facts


def cooldown_days(settings: Settings) -> int:
    """The live per-cell cooldown (wall seconds) expressed in sim-days at demo speed."""
    sim_seconds = settings.alert_cooldown_s * settings.sim_seconds_per_wall_second
    return int(sim_seconds // settings.bucket_sim_seconds)


def replay(
    world: World,
    weights: tuple[float, float, float, float],
    thresholds: tuple[int, int, int],
    cooldown: int = 0,
    first_day: int = WARM_UP,
) -> Replay:
    """Score every day from `first_day`. The first day only seeds the state (no alerts),
    exactly as the live system treats the end of its backfill."""
    out = Replay(world)
    previous: list[str] | None = None
    last_alert: dict[int, int] = {}
    n_days = world.counts.shape[2]
    for day in range(first_day, n_days):
        lo = max(0, day + 1 - HISTORY)
        result = score_cells(world.counts[:, :, lo : day + 1], world.grid, weights, thresholds)
        out.days.append(DayRecord(day, result))
        if previous is not None:
            raised = [
                (i, reason)
                for i, (p, s) in enumerate(zip(previous, result.severity, strict=True))
                if (reason := alert_reason(p, s)) is not None
                and (bypasses_cooldown(reason) or day - last_alert.get(i, -cooldown - 1) > cooldown)
            ]
            if raised:
                cells = [i for i, _ in raised]
                facts = cell_facts(world, day, result, cells, weights, thresholds[1])
                for (i, reason), f in zip(raised, facts, strict=True):
                    last_alert[i] = day
                    out.alerts.append(
                        AlertRecord(day, world.grid.cells[i], result.severity[i], reason, judge(f))
                    )
        previous = result.severity
    return out
