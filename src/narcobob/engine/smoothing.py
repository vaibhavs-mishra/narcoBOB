"""Spatial smoothing to stabilise small counts (SPEC §6.2).

s = (x + β·Σ ring-1 neighbours) / (1 + k·β), where k is the number of in-area neighbours
(6 in the interior; fewer at the area edge, so edge cells are not biased low).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from narcobob.engine.cells import CellGrid

BETA = 0.5


def smooth(
    x: npt.NDArray[np.float64], grid: CellGrid, beta: float = BETA
) -> npt.NDArray[np.float64]:
    denom = 1.0 + beta * grid.ring1_count.astype(np.float64)
    shape = (grid.n,) + (1,) * (x.ndim - 1)
    result: npt.NDArray[np.float64] = (x + beta * grid.neighbour_sum(x)) / denom.reshape(shape)
    return result
