"""Normalise the components and combine them into a 0–100 score (SPEC §6.4–6.6)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from narcobob.engine import components as comp
from narcobob.engine.cells import CellGrid
from narcobob.engine.gistar import gi_star
from narcobob.engine.severity import confidence_of, severity_of
from narcobob.engine.smoothing import smooth

Floats = npt.NDArray[np.float64]
Z_CLIP = 4.0
EPS = 1e-6
DRIVERS = ("accel", "div", "spill", "gi")


SCALE_FLOOR = 1.0  # inputs are already in noise units, so nothing is sharper than 1


def robust_z(v: Floats, mask: npt.NDArray[np.bool_] | None = None) -> Floats:
    """(v − median) / max(1.4826·MAD, 1), clipped to ±4.

    The median and MAD come from `mask` (cells with any history), so the empty
    countryside does not collapse the spread. The scale floor keeps a MAD of 0 finite.
    """
    ref = v if mask is None or not mask.any() else v[mask]
    median = float(np.median(ref))
    mad = float(np.median(np.abs(ref - median)))
    scale = max(1.4826 * mad, SCALE_FLOOR) + EPS
    result: Floats = np.clip((v - median) / scale, -Z_CLIP, Z_CLIP)
    return result


def score_from_r(r: Floats) -> npt.NDArray[np.int64]:
    """score = round(100 · σ(1.2 · (R − 1)))."""
    result: npt.NDArray[np.int64] = np.rint(100.0 / (1.0 + np.exp(-1.2 * (r - 1.0)))).astype(
        np.int64
    )
    return result


@dataclass(frozen=True)
class ScoreResult:
    """Per-cell arrays, aligned with `CellGrid.cells`."""

    score: npt.NDArray[np.int64]
    severity: list[str]
    confidence: list[str]
    support: npt.NDArray[np.int64]
    z: dict[str, Floats]  # accel, div, spill (robust z) and gi (Gi*, clipped)
    contrib: dict[str, Floats]  # weight · z for each driver

    def z_matrix(self) -> Floats:
        return np.stack([self.z[d] for d in DRIVERS], axis=1)


def score_cells(
    counts: Floats,
    grid: CellGrid,
    weights: tuple[float, float, float, float],
    thresholds: tuple[int, int, int],
    window: int = comp.WINDOW,
) -> ScoreResult:
    """Score every cell from raw counts `[cell, type, bucket]` (last bucket = now).

    Needs at least 2 × window buckets of history.
    """
    if counts.shape[2] < 2 * window:
        raise ValueError(f"need at least {2 * window} buckets, got {counts.shape[2]}")
    smoothed = smooth(counts, grid)
    accel = comp.acceleration_z(comp.od_series(smoothed), window)
    active = counts.sum(axis=(1, 2)) > 0
    # Gi* pools neighbours itself, so it gets raw counts (smoothing first would double-count).
    excess = comp.excess_z(counts[:, 0, :], window)
    z = {
        "accel": robust_z(accel, active),
        "div": robust_z(comp.divergence_z(counts, window), active),
        "spill": robust_z(comp.spillover(accel, grid), active),
        "gi": np.clip(gi_star(excess, grid), -Z_CLIP, Z_CLIP),
    }
    w = dict(zip(DRIVERS, weights, strict=True))
    contrib = {d: w[d] * z[d] for d in DRIVERS}
    score = score_from_r(sum(contrib.values(), np.zeros(grid.n)))
    # Support uses the same footprint as the scores: the cell plus its ring-1 neighbours.
    own = counts[:, :, -window:].sum(axis=(1, 2))
    support = (own + grid.neighbour_sum(own)).astype(np.int64)
    confidence = [confidence_of(int(s)) for s in support]
    severity = [
        severity_of(int(s), float(g), c, thresholds)
        for s, g, c in zip(score, z["gi"], confidence, strict=True)
    ]
    return ScoreResult(score, severity, confidence, support, z, contrib)
