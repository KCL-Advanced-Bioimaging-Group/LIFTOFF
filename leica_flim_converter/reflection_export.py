"""Native arrival-window exclusion shared by scientific exports."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from .dataset import DatasetInfo
from .histogram_core import DecodeCancelled, HistogramCube
from .timing import TimeGrid


@dataclass(frozen=True)
class ReflectionWindow:
    """Snapshot one dataset's boundaries and their plane coverage."""

    dataset_key: str
    lower: float
    upper: float
    planes: tuple[int, ...] | None = None

    def validate(self) -> None:
        """Reject invalid native bounds before writing outputs."""
        if not (
            math.isfinite(self.lower)
            and math.isfinite(self.upper)
            and 0 <= self.lower < self.upper
        ):
            raise ValueError("Invalid reflection peak boundaries")
        if self.planes is not None and any(plane < 0 for plane in self.planes):
            raise ValueError("Invalid reflection plane selection")

    def covers(self, dataset: DatasetInfo, plane: int | None) -> bool:
        """Keep bounds specific to an acquisition and its planes."""
        return self.dataset_key == dataset.key and (
            self.planes is None
            or (
                plane in self.planes
                if plane is not None
                else all(
                    index in self.planes
                    for index in range(dataset.plane_count)
                )
            )
        )

    def excludes(self, arrivals: np.ndarray) -> np.ndarray:
        """Use the same inclusive native bin centres as the preview."""
        return (arrivals >= self.lower) & (arrivals <= self.upper)

    def metadata(self, clock_s: float | None) -> dict:
        """Record exact native boundaries."""
        return {
            "enabled": True,
            "lowerNativeBin": self.lower,
            "upperNativeBin": self.upper,
            "nativeClockSeconds": clock_s,
            "boundaryConvention": "inclusive native bin centres",
            "appliedBeforeRebinning": True,
        }


def reflection_window(
    windows: tuple[ReflectionWindow, ...],
    dataset: DatasetInfo,
    plane: int | None,
) -> ReflectionWindow | None:
    """Resolve an interval for the matching dataset and plane."""
    return next(
        (item for item in windows if item.covers(dataset, plane)), None
    )


def filter_native_cube(
    cube: HistogramCube,
    grid: TimeGrid,
    window: ReflectionWindow,
    cancelled: Callable[[], bool] = lambda: False,
) -> HistogramCube:
    """Exclude native arrivals before assigning output bins."""
    window.validate()
    if (
        cube.time_grid is None
        or cube.time_grid.mode != "native"
        or cube.time_grid.clock_s != grid.clock_s
    ):
        raise ValueError(
            "Reflection filtering requires native calibrated counts"
        )
    native_bins = cube.counts.shape[0]
    if window.upper >= native_bins:
        raise ValueError(
            "Reflection boundaries exceed the native arrival window"
        )
    arrivals = np.arange(native_bins)
    excluded = window.excludes(arrivals)
    destinations = grid.indices(arrivals)
    counts = np.zeros((grid.bins, *cube.counts.shape[1:]), dtype=np.uint32)
    for index in range(grid.bins):
        if cancelled():
            raise DecodeCancelled("Reflection filtering cancelled")
        sources = np.flatnonzero((destinations == index) & ~excluded)
        values = cube.counts[sources].sum(axis=0, dtype=np.uint64)
        if np.any(values > np.iinfo(np.uint32).max):
            raise OverflowError("Filtered histogram exceeds uint32")
        counts[index] = values.astype(np.uint32)
    outside = ((destinations < 0) | (destinations >= grid.bins)) & ~excluded
    return replace(
        cube,
        counts=counts,
        events=int(counts.sum(dtype=np.uint64)),
        overflow_events=cube.overflow_events
        + int(cube.counts[outside].sum(dtype=np.uint64)),
        reflection_excluded_events=int(
            cube.counts[
                math.ceil(window.lower) : math.floor(window.upper) + 1
            ].sum(dtype=np.uint64)
        ),
        period_bins=grid.bins,
        time_grid=grid,
        backend=f"{cube.backend} (reflection filtered)",
        output_bits=32,
    )
