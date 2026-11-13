"""Histogram data models, alignment safeguards and Python oracle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

import patent_guided_deflate_attack as codec

from .data_types import CountArray
from .decay import ALL, native_period_bins
from .event_flags import PRIMARY_EVENT_FLAGS, marker_labels, markers_from_mask
from .linked_intensity import read_intensity_plane
from .timing import TimeGrid

if TYPE_CHECKING:
    from .dataset import DatasetInfo


@dataclass
class HistogramCube:
    """Calibrated bin/y/x counts and decoder provenance."""

    counts: CountArray
    events: int
    overflow_events: int
    period_bins: int
    decoded_rows: int
    backend: str = "python"
    elapsed_seconds: float = 0.0
    thread_count: int = 1
    output_bits: int = 16
    reference_events: int | None = None
    event_difference: int | None = None
    event_flag_mask: int | None = PRIMARY_EVENT_FLAGS
    included_event_flags: tuple[str, ...] = ("0xA8", "0xA0", "0xB0")
    spatial_transform: str = "identity"
    spatial_alignment_correlation: float | None = None
    spatial_alignment_absolute_error: int | None = None
    spatial_alignment_confirmed: bool = False
    source_dataset_key: str | None = None
    linear_plane: int | None = None
    time_grid: TimeGrid | None = None
    reflection_excluded_events: int = 0

    @property
    def intensity(self) -> NDArray[np.uint64]:
        """Sum all arrival bins without overflowing narrow counts."""
        return self.counts.sum(axis=0, dtype=np.uint64)

    def pixel(self, x: int, y: int) -> NDArray[np.uint64]:
        """Return the calibrated histogram for one image pixel."""
        return self.counts[:, y, x].astype(np.uint64, copy=False)

    def roi(self, x0: int, y0: int, x1: int, y1: int) -> NDArray[np.uint64]:
        """Sum the inclusive ROI bounds in each arrival bin."""
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return self.counts[:, y0 : y1 + 1, x0 : x1 + 1].sum(
            axis=(1, 2), dtype=np.uint64
        )


class HistogramAccumulator:
    """Vectorize all photon events in each row and immediately discard
    its tokens.
    """

    def __init__(
        self,
        bins: int,
        height: int,
        width: int,
        period_bins: int,
        classes: set[int] = ALL,
        row_to_y: Callable[[int], int] | None = None,
    ) -> None:
        self.bins, self.height, self.width = (bins, height, width)
        self.period_bins, self.classes = (period_bins, classes)
        self.counts: CountArray = np.zeros(
            (bins, height, width), dtype=np.uint16
        )
        self.events = self.overflow_events = self.rows = 0
        self._class_lut = np.zeros(256, dtype=bool)
        self._class_lut[list(classes)] = True
        self._row_to_y = row_to_y or (lambda row: row % self.height)

    def add_row(self, row: dict) -> None:
        """Compute add row."""
        self.rows += 1
        raw = row["tokens"]
        if not any(marker in raw for marker in self.classes):
            return
        tokens = np.frombuffer(raw, dtype=np.uint8)
        if tokens.size == 0:
            return
        positions = np.arange(tokens.size, dtype=np.int32)
        boundary = (tokens >= 128) & (tokens < 192)
        last_boundary = np.maximum.accumulate(
            np.where(boundary, positions, -1)
        )
        low_positions = positions[tokens < 128]
        if low_positions.size == 0:
            return
        owners = last_boundary[low_positions]
        valid = (owners >= 0) & self._class_lut[tokens[np.maximum(owners, 0)]]
        low_positions, owners = (low_positions[valid], owners[valid])
        if low_positions.size == 0:
            return
        low = tokens[low_positions].astype(np.int64)
        previous = np.zeros(low_positions.size, dtype=np.uint8)
        has_previous = low_positions > 0
        previous[has_previous] = tokens[low_positions[has_previous] - 1]
        two_byte = previous >= 192
        values = low
        values[two_byte] |= (previous[two_byte].astype(np.int64) & 63) << 7
        starts = np.flatnonzero(np.r_[True, owners[1:] != owners[:-1]])
        cumulative = np.cumsum(values, dtype=np.int64)
        offsets = cumulative[starts] - values[starts]
        arrivals = cumulative - np.repeat(
            offsets, np.diff(np.r_[starts, len(values)])
        )
        x_steps = np.where((tokens >= 129) & (tokens <= 159), tokens & 31, 0)
        x_at_token = np.cumsum(x_steps, dtype=np.int32)
        x = x_at_token[owners]
        inside = (x >= 0) & (x < self.width)
        x, arrivals = (x[inside], arrivals[inside])
        if x.size == 0:
            return
        self._accumulate_events(row, x, arrivals)

    def finish(self) -> HistogramCube:
        """Compute finish."""
        return HistogramCube(
            self.counts,
            self.events,
            self.overflow_events,
            self.period_bins,
            self.rows,
            output_bits=self.counts.dtype.itemsize * 8,
        )

    def _accumulate_events(
        self, row: dict, x: np.ndarray, arrivals: np.ndarray
    ) -> None:
        """Accumulate selected photons, promoting counts before narrow
        overflow.
        """
        output_bins = np.minimum(
            self.bins - 1,
            np.maximum(0, arrivals * self.bins // self.period_bins),
        )
        row_counts = np.bincount(
            output_bins * self.width + x, minlength=self.bins * self.width
        ).reshape(self.bins, self.width)
        y = self._row_to_y(int(row["line"]))
        combined = self.counts[:, y, :].astype(np.uint64) + row_counts
        if (
            self.counts.dtype == np.uint16
            and int(combined.max(initial=0)) > 65535
        ):
            self.counts = self.counts.astype(np.uint32)
        if int(combined.max(initial=0)) > np.iinfo(np.uint32).max:
            raise OverflowError("uint32 histogram overflow")
        self.counts[:, y, :] += row_counts.astype(
            self.counts.dtype, copy=False
        )
        self.events += x.size
        self.overflow_events += int(
            np.count_nonzero(arrivals >= self.period_bins)
        )


class DecodeCancelledError(RuntimeError):
    """Represent decode cancelled error."""


def _spatial_views(image: np.ndarray) -> tuple[tuple[str, np.ndarray], ...]:
    """Candidate mappings from encoded row/pixel axes to Leica image
    X/Y.
    """
    return (
        ("identity", image),
        ("flip_x", image[:, ::-1]),
        ("flip_y", image[::-1, :]),
        ("rotate_180", image[::-1, ::-1]),
        ("transpose", image.T),
        ("rotate_90_clockwise", np.rot90(image, -1)),
        ("rotate_90_counterclockwise", np.rot90(image, 1)),
        ("transpose_flip_xy", image.T[::-1, ::-1]),
    )


def _transform_cube(counts: np.ndarray, transform: str) -> np.ndarray:
    if transform == "identity":
        return counts
    if transform == "flip_x":
        view = counts[:, :, ::-1]
    elif transform == "flip_y":
        view = counts[:, ::-1, :]
    elif transform == "rotate_180":
        view = counts[:, ::-1, ::-1]
    elif transform == "transpose":
        view = counts.transpose(0, 2, 1)
    elif transform == "rotate_90_clockwise":
        view = np.rot90(counts, -1, axes=(1, 2))
    elif transform == "rotate_90_counterclockwise":
        view = np.rot90(counts, 1, axes=(1, 2))
    elif transform == "transpose_flip_xy":
        view = counts.transpose(0, 2, 1)[:, ::-1, ::-1]
    else:
        raise ValueError(f"unknown spatial transform {transform}")
    return np.ascontiguousarray(view)


def _linked_intensity(
    dataset: DatasetInfo, linear_plane: int | None
) -> np.ndarray | None:
    """Read a complete calibrated spatial oracle, or decline uncertain
    data.
    """
    try:
        if dataset.intensity_start is None or dataset.intensity_end is None:
            return None
        if linear_plane is not None:
            return read_intensity_plane(dataset, linear_plane)
        plane_bytes = dataset.width * dataset.height * 4
        available = dataset.intensity_end - dataset.intensity_start
        if not plane_bytes or available <= 0 or available % plane_bytes:
            return None
        reference_planes = (
            len(dataset.intensity_plane_starts) or available // plane_bytes
        )
        reference_values = np.zeros(
            (dataset.height, dataset.width), dtype=np.float64
        )
        for plane in range(reference_planes):
            values = read_intensity_plane(dataset, plane)
            if values is None:
                return None
            reference_values += values
    except OSError, ValueError:
        return None
    return reference_values


def align_cube_to_linked_intensity(
    cube: HistogramCube, dataset: DatasetInfo, linear_plane: int | None = None
) -> HistogramCube:
    """Align encoded axes to Leica's linked intensity image when
    unambiguous.

    Some Leica acquisitions store FLIM row/pixel axes in a rotated
    orientation. The linked intensity payload is the only file-local
    spatial oracle.  Apply a dihedral transform only when it preserves
    the declared shape, correlates at least 0.95, and reduces absolute
    pixel error by at least 90%.  Symmetric or low-information images
    therefore remain unchanged.
    """
    reference_values = _linked_intensity(dataset, linear_plane)
    if reference_values is None:
        return cube
    if not np.all(np.isfinite(reference_values)) or np.any(
        reference_values < 0
    ):
        return cube
    reference = np.rint(reference_values).astype(np.int64)
    encoded = cube.intensity
    candidates = []
    for name, view in _spatial_views(encoded):
        if view.shape != reference.shape:
            continue
        residual = view.astype(np.int64) - reference
        absolute_error = int(np.abs(residual).sum(dtype=np.uint64))
        if np.array_equal(view, reference):
            correlation = 1.0
        else:
            encoded_std = float(np.std(view, dtype=np.float64))
            reference_std = float(np.std(reference, dtype=np.float64))
            correlation = (
                float(np.corrcoef(view.ravel(), reference.ravel())[0, 1])
                if encoded_std and reference_std
                else -1.0
            )
            if not np.isfinite(correlation):
                correlation = -1.0
        candidates.append((absolute_error, -correlation, name, correlation))
    if not candidates:
        return cube
    identity = next(
        (item for item in candidates if item[2] == "identity"), None
    )
    best = min(candidates)
    selected = identity or best
    if (
        identity is not None
        and best[2] != "identity"
        and (best[3] >= 0.95)
        and (best[0] < identity[0])
        and (best[0] * 10 <= identity[0])
    ):
        selected = best
        cube.counts = _transform_cube(cube.counts, best[2])
    cube.spatial_transform = selected[2]
    cube.spatial_alignment_correlation = selected[3]
    cube.spatial_alignment_absolute_error = selected[0]
    alternatives = [item for item in candidates if item[2] != selected[2]]
    runner_up = min(alternatives) if alternatives else None
    cube.spatial_alignment_confirmed = (
        selected[3] >= 0.95
        and runner_up is not None
        and (selected[0] < runner_up[0])
        and (selected[0] * 10 <= runner_up[0])
    )
    return cube


def decode_histogram_cube_python(
    dataset: DatasetInfo,
    bins: int = 128,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    first_row: int = 0,
    row_count: int | None = None,
    reference_plane: int | None = None,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
) -> HistogramCube:
    """Compute decode histogram cube python."""
    started = perf_counter()
    if dataset.repetition_storage_model == "unresolved":
        raise RuntimeError(dataset.dimension_status)
    if progress:
        progress(f"Reading {dataset.display_name}")
    with dataset.source.open("rb") as handle:
        handle.seek(dataset.block_start)
        data = handle.read(dataset.block_end - dataset.block_start)
    _header, stream, lengths, flags = codec.load_container_bytes(data)
    period = native_period_bins(
        dataset.clock_period_s, dataset.laser_frequency_hz
    )
    accumulator = HistogramAccumulator(
        bins,
        dataset.height,
        dataset.width,
        period,
        classes=set(
            markers_from_mask(event_flag_mask, dataset.detector_route)
        ),
        row_to_y=dataset.encoded_row_to_y,
    )
    selected_rows = (
        dataset.decoded_rows - first_row if row_count is None else row_count
    )
    if (
        first_row < 0
        or selected_rows <= 0
        or first_row + selected_rows > dataset.decoded_rows
    ):
        raise ValueError(
            "requested Python row range is outside the encoded block"
        )
    if progress:
        progress(
            f"Building {bins}-bin pixel histograms for {dataset.display_name}"
        )

    def consume(row: dict) -> None:
        """Compute consume."""
        if cancelled and cancelled():
            raise DecodeCancelled("Histogram decode cancelled")
        line = int(row["line"])
        if line < first_row or line >= first_row + selected_rows:
            return
        accumulator.add_row(row)
        if progress and accumulator.rows % 8 == 0:
            progress(
                f"Python decoder: {accumulator.rows}/{selected_rows} rows"
            )

    _rows, _groups, errors, _consumed = codec.decode_descriptor_rows(
        stream, lengths, flags, row_callback=consume, keep_rows=False
    )
    if errors or accumulator.rows != selected_rows:
        raise RuntimeError(
            "Incomplete histogram decode for "
            f"{dataset.display_name}"
            ": "
            f"{accumulator.rows}"
            "/"
            f"{selected_rows}"
            " selected rows; "
            f"{errors[:3]}"
        )
    cube = accumulator.finish()
    cube.source_dataset_key = dataset.key
    cube.linear_plane = reference_plane
    cube.event_flag_mask = event_flag_mask
    cube.included_event_flags = marker_labels(
        event_flag_mask, dataset.detector_route
    )
    cube.backend = "python"
    cube.elapsed_seconds = perf_counter() - started
    cube.thread_count = 1
    cube.output_bits = cube.counts.dtype.itemsize * 8
    cube.reference_events = dataset.total_photons
    cube.event_difference = (
        cube.events - dataset.total_photons
        if dataset.total_photons is not None
        else None
    )
    return align_cube_to_linked_intensity(cube, dataset, reference_plane)


def decode_histogram_plane_python(
    dataset: DatasetInfo,
    linear_plane: int,
    bins: int = 128,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
) -> HistogramCube:
    """Compute decode histogram plane python."""
    if not 0 <= linear_plane < dataset.plane_count:
        raise IndexError(linear_plane)
    first_row, row_count = dataset.plane_row_range(linear_plane)
    return decode_histogram_cube_python(
        dataset,
        bins=bins,
        progress=progress,
        cancelled=cancelled,
        first_row=first_row,
        row_count=row_count,
        reference_plane=linear_plane,
        event_flag_mask=event_flag_mask,
    )


DecodeCancelled = DecodeCancelledError
