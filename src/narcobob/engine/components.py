"""The three trend components (SPEC §6.3), computed on smoothed series.

- Acceleration: is harm rising faster now than before?
- Divergence: is harm (overdoses) growing faster than enforcement (seizures + arrests)?
  Seizure counts measure police activity, not drug activity, so this gap reveals places
  where harm is outpacing the enforcement response.
- Spillover: are the neighbours accelerating?

Each component is expressed in units of its own Poisson noise ("how unusual is this for
this cell?"). Without that, a rural cell going from 0 to 2 events looks like a huge
acceleration, and a calm map always has a top 10% of cells that look alarming.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from narcobob.engine.cells import CellGrid
from narcobob.engine.windows import ARREST, OD, SEIZURE

Floats = npt.NDArray[np.float64]
WINDOW = 7
BASELINE = 28  # buckets before the recent window used as the cell's expected rate
RATE_FLOOR = 0.05  # events/bucket; stops empty cells from having zero noise
# Variance of a smoothed interior cell relative to a raw Poisson count: (1 + 6β²) / (1 + 6β)²
SMOOTHED_VARIANCE = (1 + 6 * 0.25) / 16


def baseline_rate(series: Floats, window: int = WINDOW) -> Floats:
    """Mean events per bucket over the BASELINE buckets before the recent window."""
    history = series[:, :-window][:, -BASELINE:]
    result: Floats = np.maximum(history.mean(axis=1), RATE_FLOOR)
    return result


def ols_slope(y: Floats) -> Floats:
    """OLS slope of each row of `y` against t = 0, 1, …, len-1."""
    t = np.arange(y.shape[-1], dtype=np.float64)
    tc = t - t.mean()
    result: Floats = (y - y.mean(axis=-1, keepdims=True)) @ tc / float(tc @ tc)
    return result


def acceleration(od: Floats, window: int = WINDOW) -> Floats:
    """Slope over the recent window minus slope over the window before it. od: [cell, bucket]."""
    recent = od[:, -window:]
    prior = od[:, -2 * window : -window]
    return ols_slope(recent) - ols_slope(prior)


def acceleration_z(od_smoothed: Floats, window: int = WINDOW) -> Floats:
    """Acceleration divided by its standard error under the cell's own baseline rate.

    Var(OLS slope) = σ² / Σ(t − t̄)²; the difference of two independent slopes doubles it.
    """
    t = np.arange(window, dtype=np.float64)
    sxx = float(((t - t.mean()) ** 2).sum())
    sigma2 = baseline_rate(od_smoothed, window) * SMOOTHED_VARIANCE
    result: Floats = acceleration(od_smoothed, window) / np.sqrt(2 * sigma2 / sxx)
    return result


def log_growth(series: Floats, window: int = WINDOW) -> Floats:
    """ln((recent sum + 1) / (prior sum + 1)) per cell. series: [cell, bucket]."""
    recent = series[:, -window:].sum(axis=1)
    prior = series[:, -2 * window : -window].sum(axis=1)
    result: Floats = np.log((recent + 1.0) / (prior + 1.0))
    return result


def divergence(smoothed: Floats, window: int = WINDOW) -> Floats:
    """Harm growth minus enforcement growth. smoothed: [cell, type, bucket]."""
    enforcement = smoothed[:, SEIZURE, :] + smoothed[:, ARREST, :]
    return log_growth(smoothed[:, OD, :], window) - log_growth(enforcement, window)


def _growth_variance(series: Floats, window: int) -> Floats:
    """Var of ln((r+1)/(p+1)) for Poisson counts ≈ 1/(r+1) + 1/(p+1) (delta method)."""
    recent = series[:, -window:].sum(axis=1)
    prior = series[:, -2 * window : -window].sum(axis=1)
    result: Floats = 1.0 / (recent + 1.0) + 1.0 / (prior + 1.0)
    return result


def divergence_z(counts: Floats, window: int = WINDOW) -> Floats:
    """Divergence on raw counts divided by its standard error. counts: [cell, type, bucket]."""
    enforcement = counts[:, SEIZURE, :] + counts[:, ARREST, :]
    od = counts[:, OD, :]
    variance = _growth_variance(od, window) + _growth_variance(enforcement, window)
    result: Floats = divergence(counts, window) / np.sqrt(variance)
    return result


def excess_z(od_raw: Floats, window: int = WINDOW) -> Floats:
    """Recent overdoses above the cell's own baseline, in Poisson standard deviations."""
    expected = window * baseline_rate(od_raw, window)
    result: Floats = (od_raw[:, -window:].sum(axis=1) - expected) / np.sqrt(expected)
    return result


def spillover(accel: Floats, grid: CellGrid) -> Floats:
    """Mean positive acceleration of each cell's in-area neighbours."""
    total = grid.neighbour_sum(np.maximum(accel, 0.0))
    count = np.maximum(grid.ring1_count, 1).astype(np.float64)
    result: Floats = total / count
    return result


def od_series(smoothed: Floats) -> Floats:
    result: Floats = smoothed[:, OD, :]
    return result
