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


def robust_z(v: Floats) -> Floats:
    """(v − median) / (1.4826·MAD + ε), clipped to ±4.

    When most cells are identical (MAD = 0) the ε keeps this finite; the clip then stops
    the handful of cells that differ from dominating everything.
    """
    median = float(np.median(v))
    mad = float(np.median(np.abs(v - median)))
    result: Floats = np.clip((v - median) / (1.4826 * mad + EPS), -Z_CLIP, Z_CLIP)
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
    od = comp.od_series(smoothed)
    accel = comp.acceleration(od, window)
    z = {
        "accel": robust_z(accel),
        "div": robust_z(comp.divergence(smoothed, window)),
        "spill": robust_z(comp.spillover(accel, grid)),
        "gi": np.clip(gi_star(od[:, -window:].sum(axis=1), grid), -Z_CLIP, Z_CLIP),
    }
    w = dict(zip(DRIVERS, weights, strict=True))
    contrib = {d: w[d] * z[d] for d in DRIVERS}
    score = score_from_r(sum(contrib.values(), np.zeros(grid.n)))
    support = counts[:, :, -window:].sum(axis=(1, 2)).astype(np.int64)
    confidence = [confidence_of(int(s)) for s in support]
    severity = [
        severity_of(int(s), float(g), c, thresholds)
        for s, g, c in zip(score, z["gi"], confidence, strict=True)
    ]
    return ScoreResult(score, severity, confidence, support, z, contrib)
