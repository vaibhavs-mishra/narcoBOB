"""Data-quality facts the Steward and Skeptic rely on: feed gaps and single-source dependence."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Floats = npt.NDArray[np.float64]
GAP_MIN_DAYS = 2  # consecutive silent buckets that count as a gap
GAP_MIN_RATE = 1.0  # only sources that normally report ≥ 1 event/bucket can "go silent"


@dataclass(frozen=True)
class SourceGap:
    source: int  # index into the caller's source list
    from_bucket: int  # relative to the start of the array
    to_bucket: int  # inclusive


def source_gaps(per_source: Floats, baseline_buckets: int = 28) -> list[SourceGap]:
    """Runs of ≥ 2 silent buckets in sources that normally report. per_source: [source, bucket]."""
    gaps: list[SourceGap] = []
    n_buckets = per_source.shape[1]
    for s, series in enumerate(per_source):
        history = series[max(0, n_buckets - baseline_buckets) :]
        if history.mean() < GAP_MIN_RATE:
            continue
        start = None
        for b in range(n_buckets + 1):
            silent = b < n_buckets and series[b] == 0
            if silent and start is None:
                start = b
            elif not silent and start is not None:
                if b - start >= GAP_MIN_DAYS:
                    gaps.append(SourceGap(s, start, b - 1))
                start = None
    return gaps


def top_source_share(cell_source: Floats) -> tuple[npt.NDArray[np.int64], Floats]:
    """Per cell: the dominant source and its share of events. cell_source: [cell, source]."""
    totals = cell_source.sum(axis=1)
    top = np.argmax(cell_source, axis=1).astype(np.int64)
    share = np.where(totals > 0, cell_source.max(axis=1) / np.maximum(totals, 1), 0.0)
    return top, share
