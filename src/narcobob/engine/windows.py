"""Turn event rows into a dense count array `x[cell, type, bucket]`."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from narcobob.engine.cells import IntArray

TYPES = ("overdose", "seizure", "arrest")
OD, SEIZURE, ARREST = 0, 1, 2


def dense_counts(
    cell_idx: IntArray, type_idx: IntArray, bucket_idx: IntArray, n_cells: int, n_buckets: int
) -> npt.NDArray[np.float64]:
    """Count events per (cell, type, bucket). Rows with an out-of-range index are ignored.

    `bucket_idx` is relative to the window start: 0 is the oldest bucket kept.
    """
    counts = np.zeros((n_cells, len(TYPES), n_buckets), dtype=np.float64)
    keep = (
        (cell_idx >= 0) & (cell_idx < n_cells) & (bucket_idx >= 0) & (bucket_idx < n_buckets)
        & (type_idx >= 0) & (type_idx < len(TYPES))
    )  # fmt: skip
    np.add.at(counts, (cell_idx[keep], type_idx[keep], bucket_idx[keep]), 1.0)
    return counts
