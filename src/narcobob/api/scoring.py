"""The fast path: rebuild the count array from SQLite and score every cell (SPEC §7).

Scores are computed up to the last *complete* sim-day, so a half-filled "today" never
looks like a sudden drop, and live results match the backtest bucket for bucket.
"""

from __future__ import annotations

import numpy as np

from narcobob.api.state import AppState
from narcobob.common.db import data_version
from narcobob.common.ids import parse_ts, wall_now
from narcobob.engine.composite import DRIVERS, ScoreResult, score_cells
from narcobob.engine.windows import TYPES

HISTORY = 60
MIN_BUCKETS = 14


def load_counts(state: AppState, last_bucket: int, n_buckets: int = HISTORY) -> np.ndarray:
    """Dense `[cell, type, bucket]` counts for the `n_buckets` ending at `last_bucket`."""
    first = last_bucket - n_buckets + 1
    rows = state.conn.execute(
        "SELECT cell, type, bucket, COUNT(*) AS n FROM events WHERE bucket BETWEEN ? AND ?"
        " GROUP BY cell, type, bucket",
        (first, last_bucket),
    ).fetchall()
    counts = np.zeros((state.grid.n, len(TYPES), n_buckets))
    for r in rows:
        i = state.grid.index.get(r["cell"])
        if i is not None:  # events near the bbox edge can fall in a cell outside the universe
            counts[i, TYPES.index(r["type"]), r["bucket"] - first] = r["n"]
    return counts


def last_complete_bucket(state: AppState) -> int | None:
    sim_now = state.sim_now()
    if sim_now is None:
        return None
    return state.bucket_of(parse_ts(sim_now)) - 1


def score_now(state: AppState) -> tuple[ScoreResult, int] | None:
    """Score all cells if new data could change the result; None when nothing to do."""
    bucket = last_complete_bucket(state)
    version = data_version(state.conn)
    if bucket is None or (bucket == state.scored_bucket and version == state.scored_version):
        return None
    first_bucket = state.conn.execute("SELECT MIN(bucket) FROM events").fetchone()[0]
    n_buckets = min(HISTORY, bucket - int(first_bucket) + 1) if first_bucket is not None else 0
    if n_buckets < MIN_BUCKETS:
        return None
    s = state.settings
    counts = load_counts(state, bucket, n_buckets)
    result = score_cells(counts, state.grid, s.weights, s.thresholds)
    state.scored_version, state.scored_bucket = version, bucket
    return result, bucket


def cell_score_dicts(
    state: AppState, result: ScoreResult, bucket: int
) -> dict[str, dict[str, object]]:
    sim_ts = state.bucket_start(bucket + 1)  # scores describe the day that just ended
    out: dict[str, dict[str, object]] = {}
    for i, cell in enumerate(state.grid.cells):
        out[cell] = {
            "cell": cell,
            "score": int(result.score[i]),
            "severity": result.severity[i],
            "confidence": result.confidence[i],
            "support": int(result.support[i]),
            "components": {
                d: {
                    "z": round(float(result.z[d][i]), 3),
                    "contrib": round(float(result.contrib[d][i]), 3),
                }
                for d in DRIVERS
            },
            "sim_ts": sim_ts,
        }
    return out


def persist_scores(state: AppState, changed: list[dict[str, object]]) -> None:
    now, version = wall_now(), state.scored_version
    rows = []
    for c in changed:
        comp = c["components"]
        assert isinstance(comp, dict)
        rows.append(
            (
                c["cell"], c["score"], c["severity"],
                comp["accel"]["z"], comp["div"]["z"], comp["spill"]["z"], comp["gi"]["z"],
                comp["accel"]["contrib"], comp["div"]["contrib"], comp["spill"]["contrib"],
                comp["gi"]["contrib"], c["support"], c["confidence"], version, c["sim_ts"], now,
            )
        )  # fmt: skip
    state.conn.executemany(
        "INSERT INTO cell_scores(cell, score, severity, z_accel, z_div, z_spill, gi_star,"
        " c_accel, c_div, c_spill, c_gi, support, confidence, data_version, sim_ts,"
        " wall_updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(cell) DO UPDATE SET score=excluded.score, severity=excluded.severity,"
        " z_accel=excluded.z_accel, z_div=excluded.z_div, z_spill=excluded.z_spill,"
        " gi_star=excluded.gi_star, c_accel=excluded.c_accel, c_div=excluded.c_div,"
        " c_spill=excluded.c_spill, c_gi=excluded.c_gi, support=excluded.support,"
        " confidence=excluded.confidence, data_version=excluded.data_version,"
        " sim_ts=excluded.sim_ts, wall_updated_at=excluded.wall_updated_at",
        rows,
    )
    state.conn.commit()
