"""Native arrival-window exclusion shared by scientific exports."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from .dataset import DatasetInfo
from .histogram_core import DecodeCancelled, HistogramCube
from .reflection_metadata import (
    MODE_LABELS,
    REPAIR_MODES,
    processing_description,
)
from .reflection_processing import corrected_cube
from .timing import TimeGrid


@dataclass(frozen=True)
class ReflectionWindow:
    """Snapshot one dataset's boundaries and their plane coverage."""

    dataset_key: str
    lower: float
    upper: float
    planes: tuple[int, ...] | None = None
    mode: str = "exclude"
    seed: int = 0

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
        if self.mode not in ("exclude", *MODE_LABELS):
            raise ValueError("Unknown reflection processing mode")
        if (
            not isinstance(self.seed, int)
            or isinstance(self.seed, bool)
            or not 0 <= self.seed < 2**64
        ):
            raise ValueError(
                "Simulation seed must be an unsigned 64-bit integer"
            )

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

    def metadata(self, clock_s: float | None, *, event_format=False) -> dict:
        """Record exact native boundaries."""
        return {
            **processing_description(
                (self.lower, self.upper),
                "exclude" if event_format else self.mode,
                self.seed,
            ),
            "enabled": True,
            "lowerNativeBin": self.lower,
            "upperNativeBin": self.upper,
            "nativeClockSeconds": clock_s,
            "boundaryConvention": "inclusive native bin centres",
            "appliedBeforeRebinning": True,
            "mode": self.mode,
            "modeLabel": MODE_LABELS.get(
                self.mode, "Exclude reflection events"
            ),
            "requestedMode": self.mode,
            "appliedMode": "exclude events" if event_format else self.mode,
            "containsSyntheticSamples": False,
            "interpolation": (
                "Straight line between whole-image log-count endpoints. "
                "Counts allocated using each pixel's fraction of counts "
                "outside the interval. Undefined whole-image endpoints "
                "remain NaN."
                if self.mode in REPAIR_MODES and not event_format
                else None
            ),
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
    if window.mode != "exclude":
        return _repair_native_cube(cube, grid, window, destinations, cancelled)
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


def _repair_native_cube(cube, grid, window, destinations, cancelled):
    """Repair pixels before spatial sums and temporal grouping."""
    derived = corrected_cube(
        cube, (window.lower, window.upper), window.mode, seed=window.seed
    )
    repaired = derived.counts
    counts = np.zeros((grid.bins, *cube.counts.shape[1:]), dtype=np.float64)
    for index in range(grid.bins):
        if cancelled():
            raise DecodeCancelled("Reflection filtering cancelled")
        # An unknown native sample makes its output bin unknown too.
        counts[index] = repaired[destinations == index].sum(axis=0)
    excluded = window.excludes(np.arange(cube.counts.shape[0]))
    inside = (destinations >= 0) & (destinations < grid.bins)
    measured = int(cube.counts[inside & ~excluded].sum(dtype=np.uint64))
    removed = int(cube.counts[excluded].sum(dtype=np.uint64))
    processing = dict(derived.reflection_processing or {})
    synthetic_bins = (
        np.unique(destinations[inside & excluded]).tolist()
        if window.mode in REPAIR_MODES
        and processing.get("interpolationAvailable")
        else []
    )
    processing.update(
        {
            "syntheticOutputBins": synthetic_bins,
            "containsSyntheticSamples": bool(synthetic_bins),
            "estimatedCountSum": float(np.nansum(repaired[inside & excluded]))
            if window.mode == "interpolate"
            else 0.0,
            "simulatedCountSum": int(np.nansum(repaired[inside & excluded]))
            if window.mode == "simulate"
            else 0,
            "missingSamples": int(np.count_nonzero(np.isnan(counts))),
            "countSumMeaning": (
                "Synthetic replacements are not measured photons"
            ),
        }
    )
    return replace(
        cube,
        counts=counts,
        events=measured,
        overflow_events=cube.overflow_events
        + int(cube.counts[~inside & ~excluded].sum(dtype=np.uint64)),
        reflection_excluded_events=removed,
        reflection_processing=processing,
        period_bins=grid.bins,
        time_grid=grid,
        output_bits=64,
        backend=f"{cube.backend} (reflection {window.mode})",
    )
