"""Engine math against hand-computed values."""

from __future__ import annotations

import math
import time

import h3
import numpy as np
import pytest

from narcobob.engine.cells import CellGrid
from narcobob.engine.components import acceleration, divergence, ols_slope, spillover
from narcobob.engine.composite import robust_z, score_cells, score_from_r
from narcobob.engine.gistar import gi_star
from narcobob.engine.sensitivity import sensitivity
from narcobob.engine.severity import confidence_of, severity_of
from narcobob.engine.smoothing import smooth
from narcobob.engine.windows import dense_counts

CENTRE = h3.latlng_to_cell(31.55, 74.62, 7)
SEVEN = CellGrid.from_cells([CENTRE, *h3.grid_ring(CENTRE, 1)])
BBOX = (31.20, 74.50, 31.90, 75.20)
THRESHOLDS = (60, 75, 88)
WEIGHTS = (0.35, 0.25, 0.20, 0.20)


def test_seven_cell_grid_adjacency() -> None:
    centre = SEVEN.index[CENTRE]
    assert SEVEN.ring1_count[centre] == 6
    # each outer cell touches the centre and its two outer neighbours (the rest is outside)
    assert all(SEVEN.ring1_count[i] == 3 for i in range(7) if i != centre)


def test_gi_star_hand_computed_seven_cells() -> None:
    # x = 10 at the centre, 1 elsewhere. n=7, X̄ = 16/7, S = sqrt(106/7 − (16/7)²).
    x = np.ones(7)
    centre = SEVEN.index[CENTRE]
    x[centre] = 10.0
    g = gi_star(x, SEVEN)
    s = math.sqrt(106 / 7 - (16 / 7) ** 2)
    # outer cell: window = self + centre + 2 outer = 4 cells, Σx = 13
    outer_expected = (13 - 16 / 7 * 4) / (s * math.sqrt((7 * 4 - 16) / 6))
    # the centre's window is the whole universe, so it cannot stand out from itself
    assert g[centre] == pytest.approx(0.0, abs=1e-12)
    for i in range(7):
        if i != centre:
            assert g[i] == pytest.approx(outer_expected, rel=1e-9)
    assert outer_expected == pytest.approx(0.8660254, rel=1e-6)


def test_gi_star_flat_map_is_zero() -> None:
    assert np.all(gi_star(np.full(7, 3.0), SEVEN) == 0.0)


def test_ols_slope_signs() -> None:
    assert ols_slope(np.array([[1.0, 2, 3, 4, 5]]))[0] == pytest.approx(1.0)
    assert ols_slope(np.array([[5.0, 4, 3, 2, 1]]))[0] == pytest.approx(-1.0)
    assert ols_slope(np.array([[2.0, 2, 2, 2]]))[0] == pytest.approx(0.0)


def test_acceleration_positive_when_ramp_starts() -> None:
    flat_then_ramp = np.array([[1.0] * 7 + [1, 2, 3, 4, 5, 6, 7]])
    steady_ramp = np.arange(14, dtype=float)[None, :]
    assert acceleration(flat_then_ramp)[0] == pytest.approx(1.0)
    assert acceleration(steady_ramp)[0] == pytest.approx(0.0)


def test_divergence_sign() -> None:
    x = np.zeros((1, 3, 14))
    x[0, 0, 7:] = 10  # overdoses rise, enforcement flat → positive
    assert divergence(x)[0] > 0
    y = np.zeros((1, 3, 14))
    y[0, 1, 7:] = 10  # seizure raid, overdoses flat → negative
    assert divergence(y)[0] < 0


def test_smoothing_preserves_flat_field_and_spreads_spike() -> None:
    flat = np.full((7, 1), 4.0)
    assert np.allclose(smooth(flat, SEVEN), 4.0)
    spike = np.zeros((7, 1))
    spike[SEVEN.index[CENTRE]] = 8.0
    s = smooth(spike, SEVEN)
    assert s[SEVEN.index[CENTRE], 0] == pytest.approx(8 / 4)  # 8 / (1 + 6·0.5)
    assert all(s[i, 0] > 0 for i in range(7))


def test_spillover_uses_positive_neighbour_acceleration() -> None:
    accel = np.zeros(7)
    accel[SEVEN.index[CENTRE]] = 3.0
    out = spillover(accel, SEVEN)
    assert out[SEVEN.index[CENTRE]] == 0.0
    assert all(out[i] == pytest.approx(1.0) for i in range(7) if i != SEVEN.index[CENTRE])


def test_robust_z_with_zero_mad_stays_finite_and_clipped() -> None:
    v = np.array([0.0] * 99 + [5.0])  # MAD = 0
    z = robust_z(v)
    assert np.all(np.isfinite(z))
    assert z[-1] == 4.0 and np.all(z[:-1] == 0.0)


def test_score_mapping() -> None:
    assert score_from_r(np.array([1.0]))[0] == 50
    assert score_from_r(np.array([-5.0]))[0] == 0
    assert score_from_r(np.array([6.0]))[0] == 100


@pytest.mark.parametrize(
    ("score", "gi", "conf", "expected"),
    [
        (95, 2.5, "high", "CRITICAL"),
        (95, 1.5, "high", "HIGH"),  # not a significant hotspot
        (95, 2.5, "low", "HIGH"),  # too few events for CRITICAL
        (80, 3.0, "high", "HIGH"),
        (65, 0.0, "low", "WATCH"),
        (59, 4.0, "high", "NORMAL"),
    ],
)
def test_severity_gates(score: int, gi: float, conf: str, expected: str) -> None:
    assert severity_of(score, gi, conf, THRESHOLDS) == expected


def test_confidence_bands() -> None:
    assert [confidence_of(n) for n in (0, 7, 8, 19, 20)] == [
        "low", "low", "medium", "medium", "high",
    ]  # fmt: skip


def test_dense_counts_ignores_out_of_range() -> None:
    idx = np.array([0, 0, 5, 1], dtype=np.int64)
    counts = dense_counts(idx, np.array([0, 0, 0, 2]), np.array([0, 0, 0, 9]), 2, 3)
    assert counts[0, 0, 0] == 2 and counts.sum() == 2


def test_planted_hotspot_scores_highest() -> None:
    grid = CellGrid.from_bbox(BBOX, 7)
    rng = np.random.default_rng(1)
    counts = rng.poisson(0.3, size=(grid.n, 3, 30)).astype(float)
    hot = grid.index[CENTRE]
    counts[hot, 0, -7:] += np.array([2, 4, 6, 8, 10, 12, 14])
    result = score_cells(counts, grid, WEIGHTS, THRESHOLDS)
    assert int(np.argmax(result.score)) == hot
    assert result.severity[hot] in ("HIGH", "CRITICAL")
    assert result.contrib["accel"][hot] > 0


def test_sensitivity_stable_for_strong_cell_and_seeded() -> None:
    z = np.array([[4.0, 4.0, 4.0, 4.0], [0.0, 0.0, 0.0, 0.0]])
    a = sensitivity(z, WEIGHTS, 75, samples=30, seed=7)
    assert a[0].stability == 1.0 and a[1].stability == 0.0
    assert a == sensitivity(z, WEIGHTS, 75, samples=30, seed=7)


def test_scoring_pass_performance() -> None:
    # SPEC §6.9: ≤ 200 ms for ≤ 5,000 cells × 60 buckets
    grid = CellGrid.from_bbox((30.9, 74.2, 32.2, 75.6), 7)
    assert grid.n >= 3000
    counts = np.random.default_rng(0).poisson(0.5, size=(grid.n, 3, 60)).astype(float)
    score_cells(counts, grid, WEIGHTS, THRESHOLDS)  # warm-up
    started = time.perf_counter()
    score_cells(counts, grid, WEIGHTS, THRESHOLDS)
    assert time.perf_counter() - started < 0.2
