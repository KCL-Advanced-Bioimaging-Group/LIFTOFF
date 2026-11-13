"""Bounded physical-time histogramming of the selected photon stream."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter

import numpy as np

from .dataset import DatasetInfo
from .event_flags import marker_labels, normalize_selection, selection_name
from .histogram_core import HistogramCube, align_cube_to_linked_intensity
from .photon_stream import _compressed_rows, iter_lmsraw_vectors
from .timing import TimeGrid


def decode_calibrated(
    dataset: DatasetInfo,
    grid: TimeGrid,
    linear_plane: int | None,
    event_flag_mask: int,
    progress: Callable[[str], None],
    cancelled: Callable[[], bool],
) -> HistogramCube:
    """Share selection with PTU while assigning physical, half-open
    bins.
    """
    started = perf_counter()
    mode = normalize_selection(event_flag_mask, dataset.storage_format)
    if dataset.repetition_storage_model == "unresolved":
        raise ValueError(dataset.dimension_status)
    if (
        dataset.mosaic is not None
        and dataset.tile_index is None
        and linear_plane is None
    ):
        raise ValueError("Select an individual mosaic tile for ICS export")
    planes = (
        range(dataset.plane_count) if linear_plane is None else [linear_plane]
    )
    counts = np.zeros((grid.bins, dataset.height, dataset.width), np.uint32)
    events = excluded = rows = 0

    def consume(line, x, arrivals, first):
        nonlocal events, excluded, rows
        rows += 1
        destinations = grid.indices(arrivals)
        inside = (destinations >= 0) & (destinations < grid.bins)
        excluded += int(np.count_nonzero(~inside))
        x, destinations = x[inside], destinations[inside]
        events += int(x.size)
        y = dataset.encoded_row_to_y(line, first)
        indices, increments = np.unique(
            destinations * dataset.width + x, return_counts=True
        )
        time_bins, pixels = np.divmod(indices, dataset.width)
        combined = counts[time_bins, y, pixels].astype(
            np.uint64
        ) + increments.astype(np.uint64)
        if np.any(combined > np.iinfo(np.uint32).max):
            raise OverflowError("uint32 histogram overflow")
        counts[time_bins, y, pixels] = combined.astype(np.uint32)
        if rows % 256 == 0:
            progress(
                f"Calibrated histogram: {rows} rows; "
                f"{excluded} photons outside window"
            )

    for plane in planes:
        first, length = dataset.plane_row_range(plane)
        if dataset.storage_format == "lmsraw":
            for line, x, arrivals in iter_lmsraw_vectors(
                dataset, first, length, mode, cancelled
            ):
                consume(line, x, arrivals, first)
        else:

            def compressed(line, photons, first_row=first):
                values = np.asarray(photons, dtype=np.int64).reshape(-1, 3)
                consume(line, values[:, 0], values[:, 1], first_row)

            _compressed_rows(
                dataset, first, length, compressed, progress, cancelled, mode
            )
    cube = HistogramCube(
        counts=counts,
        events=events,
        overflow_events=excluded,
        period_bins=grid.bins,
        decoded_rows=rows,
        backend="calibrated-stream",
        elapsed_seconds=perf_counter() - started,
        output_bits=32,
        event_flag_mask=mode,
        included_event_flags=(
            marker_labels(mode, dataset.detector_route)
            if dataset.storage_format == "compressed"
            else (selection_name(mode),)
        ),
        source_dataset_key=dataset.key,
        linear_plane=linear_plane,
        time_grid=grid,
    )
    progress(
        f"Histogram complete: {events} photons; "
        f"{excluded} excluded outside the time window"
    )
    return align_cube_to_linked_intensity(cube, dataset, linear_plane)
