"""The cell universe: every H3 cell in the area, including cells with no events.

Gi* and the robust z-scores are only correct when zero-count cells are included,
so the universe comes from the bounding box, never from the events.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
import numpy as np
import numpy.typing as npt

IntArray = npt.NDArray[np.int64]


@dataclass(frozen=True)
class CellGrid:
    cells: tuple[str, ...]
    index: dict[str, int]
    # ring1[i] holds the indices of cell i's neighbours; -1 marks a neighbour outside the area.
    ring1: IntArray
    # Number of in-area neighbours per cell (6 in the interior, fewer at the edge).
    ring1_count: IntArray

    @property
    def n(self) -> int:
        return len(self.cells)

    @classmethod
    def from_cells(cls, cells: list[str]) -> CellGrid:
        ordered = tuple(sorted(set(cells)))
        index = {c: i for i, c in enumerate(ordered)}
        ring1 = np.full((len(ordered), 6), -1, dtype=np.int64)
        for i, cell in enumerate(ordered):
            neighbours = sorted(h3.grid_ring(cell, 1))
            for j, nb in enumerate(neighbours[:6]):
                ring1[i, j] = index.get(nb, -1)
        return cls(ordered, index, ring1, (ring1 >= 0).sum(axis=1).astype(np.int64))

    @classmethod
    def from_bbox(cls, bbox: tuple[float, float, float, float], res: int) -> CellGrid:
        """bbox = (lat_min, lon_min, lat_max, lon_max)."""
        lat_min, lon_min, lat_max, lon_max = bbox
        poly = h3.LatLngPoly(
            [(lat_min, lon_min), (lat_min, lon_max), (lat_max, lon_max), (lat_max, lon_min)]
        )
        return cls.from_cells(list(h3.polygon_to_cells(poly, res)))

    def neighbour_sum(self, values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Sum of `values` over each cell's in-area ring-1 neighbours (first axis = cell)."""
        padded = np.concatenate([values, np.zeros_like(values[:1])], axis=0)
        idx = np.where(self.ring1 >= 0, self.ring1, self.n)  # -1 → the zero padding row
        result: npt.NDArray[np.float64] = padded[idx].sum(axis=1)
        return result
