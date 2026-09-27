"""Getis-Ord Gi* hotspot statistic (SPEC §6.3), binary weights over ring-1 ∪ self.

G*_i = (Σ_j w_ij x_j − X̄ Σ_j w_ij) / (S · sqrt((n Σ_j w_ij² − (Σ_j w_ij)²) / (n − 1)))
where X̄ and S are the mean and standard deviation over all n cells in the universe.
With binary weights, Σ w_ij = Σ w_ij² = k_i + 1 (k_i = in-area neighbours).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from narcobob.engine.cells import CellGrid

Floats = npt.NDArray[np.float64]


def gi_star(x: Floats, grid: CellGrid) -> Floats:
    n = grid.n
    if n < 2:
        return np.zeros(n)
    mean = float(x.mean())
    std = float(np.sqrt(max((x**2).mean() - mean**2, 0.0)))
    if std == 0.0:
        return np.zeros(n)  # a perfectly flat map has no hotspots
    w_sum = grid.ring1_count.astype(np.float64) + 1.0
    local = x + grid.neighbour_sum(x)
    denom = std * np.sqrt((n * w_sum - w_sum**2) / (n - 1))
    result: Floats = np.where(
        denom > 0, (local - mean * w_sum) / np.where(denom > 0, denom, 1), 0.0
    )
    return result
