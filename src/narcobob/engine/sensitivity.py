"""How robust is a cell's alert to the choice of weights? (SPEC §6.8)

Re-weight the cell's fixed component z-scores with N weight vectors drawn from a Dirichlet
centred on the configured weights. `stability` is the share of draws that keep the cell
at HIGH or above. A low stability means the alert hinges on one arbitrary weight choice.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from narcobob.engine.composite import score_from_r

CONCENTRATION = 20.0


@dataclass(frozen=True)
class Sensitivity:
    stability: float
    min_score: int
    max_score: int
    median_score: int


def sensitivity(
    z: npt.NDArray[np.float64],
    weights: tuple[float, float, float, float],
    high_threshold: int,
    samples: int = 30,
    seed: int = 0,
) -> list[Sensitivity]:
    """z: [cell, 4] component z-scores in driver order (accel, div, spill, gi)."""
    rng = np.random.default_rng(seed)
    alpha = CONCENTRATION * np.asarray(weights, dtype=np.float64) / float(sum(weights))
    draws = rng.dirichlet(alpha, size=samples) * float(sum(weights))  # [samples, 4]
    scores = score_from_r(z @ draws.T)  # [cell, samples]
    return [
        Sensitivity(
            stability=float((row >= high_threshold).mean()),
            min_score=int(row.min()),
            max_score=int(row.max()),
            median_score=int(np.median(row)),
        )
        for row in scores
    ]
