"""The three trend components (SPEC §6.3), computed on smoothed series.

- Acceleration: is harm rising faster now than before?
- Divergence: is harm (overdoses) growing faster than enforcement (seizures + arrests)?
  Seizure counts measure police activity, not drug activity, so this gap reveals places
  where harm is outpacing the enforcement response.
- Spillover: are the neighbours accelerating?
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from narcobob.engine.cells import CellGrid
from narcobob.engine.windows import ARREST, OD, SEIZURE

Floats = npt.NDArray[np.float64]
WINDOW = 7


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


def spillover(accel: Floats, grid: CellGrid) -> Floats:
    """Mean positive acceleration of each cell's in-area neighbours."""
    total = grid.neighbour_sum(np.maximum(accel, 0.0))
    count = np.maximum(grid.ring1_count, 1).astype(np.float64)
    result: Floats = total / count
    return result


def od_series(smoothed: Floats) -> Floats:
    result: Floats = smoothed[:, OD, :]
    return result
