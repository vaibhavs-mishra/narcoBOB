"""Synthetic narcotics events, calibrated to plausible aggregates. SIMULATED, never real.

How one sim-day is drawn:
1. Each cell gets a base rate from a Gaussian mixture of urban centres plus a rural floor.
2. Overdoses get a weekend bump. Seizures and arrests are *thinned* by an enforcement field
   centred on police stations, so enforcement counts reflect where police are, not where
   drugs are. That is the bias NarcoBob's divergence signal is built to see through.
3. Active injections change the rates (surges, raids) or drop a source (outages).
4. Counts are Poisson draws; the RNG is seeded by (seed, day), so any day can be
   regenerated identically, in any order, live or in the backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import h3
import numpy as np
import numpy.typing as npt

from narcobob.common.ids import iso
from narcobob.engine.cells import CellGrid
from narcobob.simulator.scenario import InjectionSpec, Scenario, Source

Floats = npt.NDArray[np.float64]
TYPES = ("overdose", "seizure", "arrest")
HOSPITAL_SHARES = (0.6, 0.3, 0.1)  # nearest, 2nd, 3rd hospital
SUBSTANCES = ("heroin", "opium", "synthetic", "pharma", "cannabis")
SUBSTANCE_P = (0.45, 0.2, 0.15, 0.12, 0.08)
KM_PER_DEG = 111.0


@dataclass
class ActiveInjection:
    """An injection scheduled for (or triggered at) a given sim day."""

    spec: InjectionSpec
    start_day: int
    cells: list[int] = field(default_factory=list)  # grid indices it affects

    def status(self, day: int) -> str:
        if day < self.start_day:
            return "pending"
        duration = self.spec.duration_days
        if duration is not None and day >= self.start_day + duration:
            return "done"
        return "active"


def _dist_km(grid_lat: Floats, grid_lon: Floats, lat: float, lon: float) -> Floats:
    dlat = (grid_lat - lat) * KM_PER_DEG
    dlon = (grid_lon - lon) * KM_PER_DEG * np.cos(np.radians(lat))
    result: Floats = np.sqrt(dlat**2 + dlon**2)
    return result


class Generator:
    def __init__(self, scenario: Scenario, grid: CellGrid, seed: int) -> None:
        self.scenario = scenario
        self.grid = grid
        self.seed = seed
        centres = np.array([h3.cell_to_latlng(c) for c in grid.cells])
        self.lat: Floats = centres[:, 0]
        self.lon: Floats = centres[:, 1]
        self.base = self._base_rates()
        self.enforcement = self._enforcement_field()
        self.hospitals = [s for s in scenario.sources.hospital]
        self.police = [s for s in scenario.sources.police]
        self.hospital_rank = self._nearest(self.hospitals, len(HOSPITAL_SHARES))
        self.police_rank = self._nearest(self.police, 1)
        self.injections: list[ActiveInjection] = []
        if scenario.auto_injections:
            for spec in scenario.injections:
                self.inject(spec.id, spec.at_day)

    # ── static fields ────────────────────────────────────────────────────────

    def _base_rates(self) -> Floats:
        """[cell, type] expected events per day before weekday, enforcement and injections."""
        bg = self.scenario.background
        mix = np.zeros(self.grid.n)
        for c in bg.centres:
            d = _dist_km(self.lat, self.lon, c.lat, c.lon)
            mix += c.weight * np.exp(-(d**2) / (2 * c.sigma_km**2))
        share = mix / mix.sum() if mix.sum() > 0 else np.full(self.grid.n, 1 / self.grid.n)
        rates = np.stack([share * bg.rates_per_day.get(t, 0.0) for t in TYPES], axis=1)  # type: ignore[call-overload]
        result: Floats = rates + bg.rural_rate / len(TYPES)
        return result

    def _enforcement_field(self) -> Floats:
        """Per-cell enforcement intensity in [min, max], highest near police stations."""
        ef = self.scenario.background.enforcement_field
        mix = np.zeros(self.grid.n)
        for s in self.scenario.sources.police:
            if s.lat is not None and s.lon is not None:
                d = _dist_km(self.lat, self.lon, s.lat, s.lon)
                mix = np.maximum(mix, np.exp(-(d**2) / (2 * ef.sigma_km**2)))
        result: Floats = ef.min + (ef.max - ef.min) * mix
        return result

    def _nearest(self, sources: list[Source], k: int) -> npt.NDArray[np.int64]:
        """[cell, k] indices of the k nearest located sources (unlocated: spread by hash)."""
        n = len(sources)
        dist = np.zeros((self.grid.n, n))
        for j, s in enumerate(sources):
            if s.lat is not None and s.lon is not None:
                dist[:, j] = _dist_km(self.lat, self.lon, s.lat, s.lon)
            else:
                dist[:, j] = (np.arange(self.grid.n) * 7919 + j * 104729) % 1000
        result: npt.NDArray[np.int64] = np.argsort(dist, axis=1)[:, : min(k, n)].astype(np.int64)
        return result

    # ── injections ───────────────────────────────────────────────────────────

    def inject(self, injection_id: str, start_day: int) -> ActiveInjection:
        """Schedule a scenario injection to start on `start_day` (idempotent per id)."""
        for existing in self.injections:
            if existing.spec.id == injection_id:
                return existing
        spec = self.scenario.injection(injection_id)
        active = ActiveInjection(spec, start_day, self._target_cells(spec))
        self.injections.append(active)
        return active

    def _target_cells(self, spec: InjectionSpec) -> list[int]:
        res = self.scenario.area.h3_res
        if spec.around is not None:
            anchor = self.scenario.injection(spec.around)
            assert anchor.lat is not None and anchor.lon is not None
            centre = h3.latlng_to_cell(anchor.lat, anchor.lon, res)
            inner = set(h3.grid_disk(centre, anchor.radius_cells))
            ring = set(h3.grid_disk(centre, anchor.radius_cells + spec.ring)) - inner
            return sorted(self.grid.index[c] for c in ring if c in self.grid.index)
        if spec.lat is None or spec.lon is None:
            return []
        centre = h3.latlng_to_cell(spec.lat, spec.lon, res)
        disk = h3.grid_disk(centre, spec.radius_cells if spec.kind == "surge" else 0)
        return sorted(self.grid.index[c] for c in disk if c in self.grid.index)

    def injection_status(self, day: int) -> list[dict[str, str]]:
        return [
            {"id": a.spec.id, "kind": a.spec.kind, "status": a.status(day)} for a in self.injections
        ]

    # ── one day ──────────────────────────────────────────────────────────────

    def day_start(self, day: int) -> datetime:
        start = self.scenario.start_date
        return datetime(start.year, start.month, start.day, tzinfo=UTC) + timedelta(days=day)

    def rates(self, day: int) -> tuple[Floats, set[str]]:
        """[cell, type] Poisson rates for `day`, and the set of silenced sources."""
        rates = self.base.copy()
        if self.day_start(day).weekday() >= 5:
            rates[:, 0] *= self.scenario.background.weekly_od_bump
        rates[:, 1:] *= self.enforcement[:, None]
        silenced: set[str] = set()
        for active in self.injections:
            spec, elapsed = active.spec, day - active.start_day
            if active.status(day) != "active":
                continue
            type_idx = [TYPES.index(t) for t in spec.types]
            cells = active.cells
            if spec.kind == "surge" and spec.absolute is not None:
                continue  # exact extra events, added in `extra_counts`
            if spec.kind in ("surge", "raid"):
                ramp = min(1.0, (elapsed + 1) / max(spec.ramp_days, 1))
                factor = 1.0 + (spec.multiplier - 1.0) * ramp
                for t in type_idx:
                    rates[cells, t] *= factor
            elif spec.kind == "outage" and spec.source is not None:
                silenced.add(spec.source)
        return rates, silenced

    def extra_counts(self, day: int) -> npt.NDArray[np.int64]:
        """[cell, type] exact extra events from `absolute` surges (N in total over ramp_days)."""
        extra = np.zeros((self.grid.n, len(TYPES)), dtype=np.int64)
        for active in self.injections:
            spec, elapsed = active.spec, day - active.start_day
            if spec.kind != "surge" or spec.absolute is None or not 0 <= elapsed < spec.ramp_days:
                continue
            total, days = int(spec.absolute), max(spec.ramp_days, 1)
            today = total // days + (1 if elapsed < total % days else 0)
            for t in spec.types:
                extra[active.cells, TYPES.index(t)] += today
        return extra

    def events_for_day(self, day: int) -> list[dict[str, Any]]:
        """All events for one sim-day, as Event dicts (ingest-ready), ordered by time."""
        rng = np.random.default_rng([self.seed, day])
        rates, silenced = self.rates(day)
        counts = rng.poisson(rates) + self.extra_counts(day)
        start = self.day_start(day)
        events: list[dict[str, Any]] = []
        for cell_i, type_i in zip(*np.nonzero(counts), strict=True):
            for _ in range(int(counts[cell_i, type_i])):
                source = self._source(rng, int(cell_i), int(type_i))
                if source in silenced:
                    continue
                events.append(self._event(rng, start, int(cell_i), int(type_i), source))
        events.sort(key=lambda e: e["ts"])
        for i, e in enumerate(events):
            e["event_id"] = f"sim-{self.scenario.name}-{self.seed}-d{day:04d}-{i:05d}"
        return events

    def _source(self, rng: np.random.Generator, cell: int, type_i: int) -> str:
        if type_i == 0:
            ranks = self.hospital_rank[cell]
            p = np.array(HOSPITAL_SHARES[: len(ranks)])
            pick = int(rng.choice(ranks, p=p / p.sum()))
            return f"hospital:{self.hospitals[pick].id}"
        return f"police:{self.police[int(self.police_rank[cell, 0])].id}"

    def _event(
        self, rng: np.random.Generator, start: datetime, cell: int, type_i: int, source: str
    ) -> dict[str, Any]:
        # jitter within ~400 m of the cell centre so the point stays in its cell
        lat = float(self.lat[cell] + rng.uniform(-0.0035, 0.0035))
        lon = float(self.lon[cell] + rng.uniform(-0.0035, 0.0035))
        ts = start + timedelta(seconds=float(rng.uniform(0, 86_400)))
        event: dict[str, Any] = {
            "event_id": "",
            "type": TYPES[type_i],
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "ts": iso(ts),
            "source": source,
            "substance": str(rng.choice(SUBSTANCES, p=SUBSTANCE_P)),
        }
        if type_i == 1:
            event["quantity_g"] = round(float(rng.lognormal(3.0, 1.2)), 1)
        return event
