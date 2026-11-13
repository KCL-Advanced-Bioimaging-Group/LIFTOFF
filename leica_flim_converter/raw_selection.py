"""Bounded LMSRAW decoding with explicit, shared photon selection."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter

import numpy as np

from .dataset import DatasetInfo
from .decay import native_period_bins
from .event_flags import (
    PRIMARY_EVENT_FLAGS,
    RAW_ALL_PHOTONS,
    RAW_FIRST_PHOTONS,
    normalize_selection,
)
from .histogram_core import (
    DecodeCancelled,
    HistogramCube,
    align_cube_to_linked_intensity,
)
from .photon_selection import dead_time_info, select_raw_vectors
from .platform_paths import native_library_candidates
from .raw_container import RawPreparedReader as RawPreparedDecoder
from .timing import TimeGrid

Progress = Callable[[str], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class _RawSelection:
    """One validated plane selection shared by both decoding
    backends.
    """

    dataset: DatasetInfo
    decoder: RawPreparedDecoder
    counts: np.ndarray
    ranges: list[tuple[int, int]]
    mode: int
    period: int
    threshold: int
    linear_plane: int | None
    threads: int
    progress: Progress | None
    cancelled: CancelCheck | None
    grid: TimeGrid | None


@lru_cache(maxsize=1)
def load_filter_library() -> ctypes.CDLL:
    """Load API 2 and declare both portable C boundaries once."""
    path = next(
        (
            path
            for path in native_library_candidates("LeicaLmsrawFilter")
            if path.is_file()
        ),
        None,
    )
    if path is None:
        raise OSError("The Leica LMSRAW filter library is not installed")
    library = ctypes.CDLL(str(path))
    library.leica_lmsraw_filter_api_version.argtypes = []
    library.leica_lmsraw_filter_api_version.restype = ctypes.c_uint32
    if library.leica_lmsraw_filter_api_version() != 2:
        raise OSError("Unsupported LeicaLmsrawFilter API version")
    pointer = ctypes.c_void_p
    integer = ctypes.c_uint32
    wide = ctypes.c_uint64
    count_pointer = ctypes.POINTER(wide)
    library.leica_decode_raw_filtered_batch.argtypes = [
        pointer,
        wide,
        pointer,
        pointer,
        wide,
        *[integer] * 4,
        pointer,
        *[integer] * 4,
        pointer,
        wide,
        count_pointer,
        count_pointer,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.leica_decode_raw_filtered_batch.restype = ctypes.c_int
    library.leica_decode_raw_all_valid_batch.argtypes = [
        pointer,
        wide,
        pointer,
        pointer,
        wide,
        *[integer] * 4,
        pointer,
        *[integer] * 3,
        wide,
        wide,
        integer,
        integer,
        integer,
        pointer,
        wide,
        count_pointer,
        count_pointer,
        ctypes.POINTER(integer),
        ctypes.POINTER(integer),
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    library.leica_decode_raw_all_valid_batch.restype = ctypes.c_int
    return library


def _check_cancelled(cancelled: CancelCheck | None) -> None:
    if cancelled and cancelled():
        raise DecodeCancelled("LMSRAW histogram decode cancelled")


def _decode_python(job: _RawSelection) -> tuple[int, int]:
    events = overflow = processed = 0
    bins = job.counts.shape[0]
    total = sum((count for _first, count in job.ranges))
    with job.dataset.source.open("rb") as handle:
        for first, length in job.ranges:
            state = [False, 0]
            for row, payload in job.decoder.iter_rows(
                handle, first, length, job.cancelled
            ):
                _check_cancelled(job.cancelled)
                words = np.frombuffer(payload, dtype=">u2")
                x, arrivals = select_raw_vectors(
                    words, job.dataset, job.mode, state, job.threshold
                )
                if x.size:
                    if job.grid is None:
                        output_bin = np.clip(
                            arrivals * bins // job.period, 0, bins - 1
                        )
                        overflow += int(
                            np.count_nonzero(arrivals >= job.period)
                        )
                    else:
                        output_bin = job.grid.indices(arrivals)
                        inside = (output_bin >= 0) & (output_bin < bins)
                        overflow += int(np.count_nonzero(~inside))
                        x, output_bin = x[inside], output_bin[inside]
                    y = job.dataset.encoded_row_to_y(
                        row, first if job.linear_plane is not None else None
                    )
                    indices, increments = np.unique(
                        output_bin * job.dataset.width + x, return_counts=True
                    )
                    time_bins, pixels = np.divmod(indices, job.dataset.width)
                    combined = job.counts[time_bins, y, pixels].astype(
                        np.uint64
                    ) + increments.astype(np.uint64)
                    if np.any(combined > np.iinfo(np.uint32).max):
                        raise OverflowError("uint32 histogram overflow")
                    job.counts[time_bins, y, pixels] = combined.astype(
                        np.uint32
                    )
                    events += int(x.size)
                processed += 1
                if job.progress and processed % 64 == 0:
                    job.progress(f"LMSRAW selection: {processed}/{total} rows")
    return (events, overflow)


def _decode_native(
    job: _RawSelection, library: ctypes.CDLL
) -> tuple[int, int]:
    events = overflow = processed = 0
    total = sum((count for _first, count in job.ranges))
    lookup = job.grid.lookup() if job.grid is not None else None
    with job.dataset.source.open("rb") as handle:
        for plane_first, plane_rows in job.ranges:
            previous_valid = ctypes.c_uint32()
            previous_arrival = ctypes.c_uint32()
            for first, stop, start, block in job.decoder.iter_batches(
                handle, plane_first, plane_rows, job.cancelled
            ):
                _check_cancelled(job.cancelled)
                offsets = np.empty(stop - first + 1, dtype=np.uint64)
                offsets[0] = 0
                offsets[1:] = job.decoder.ends[first:stop] - start
                row_y = np.array(
                    [
                        job.dataset.encoded_row_to_y(
                            row,
                            plane_first
                            if job.linear_plane is not None
                            else None,
                        )
                        for row in range(first, stop)
                    ],
                    dtype=np.uint32,
                )
                data = np.frombuffer(block, dtype=np.uint8)
                photons = ctypes.c_uint64()
                overflows = ctypes.c_uint64()
                error = ctypes.create_string_buffer(2048)
                common = (
                    data.ctypes.data,
                    data.nbytes,
                    offsets.ctypes.data,
                    row_y.ctypes.data,
                    stop - first,
                    job.dataset.width,
                    job.dataset.height,
                    job.counts.shape[0],
                    job.period,
                    lookup.ctypes.data if lookup is not None else None,
                    lookup.size if lookup is not None else 0,
                    job.dataset.detector_route,
                )
                if job.mode == RAW_ALL_PHOTONS:
                    status = library.leica_decode_raw_all_valid_batch(
                        *common,
                        job.threshold,
                        first - plane_first,
                        plane_rows,
                        previous_valid.value,
                        previous_arrival.value,
                        job.threads,
                        job.counts.ctypes.data,
                        job.counts.nbytes,
                        ctypes.byref(photons),
                        ctypes.byref(overflows),
                        ctypes.byref(previous_valid),
                        ctypes.byref(previous_arrival),
                        error,
                        len(error),
                    )
                else:
                    status = library.leica_decode_raw_filtered_batch(
                        *common,
                        job.mode,
                        job.threads,
                        job.counts.ctypes.data,
                        job.counts.nbytes,
                        ctypes.byref(photons),
                        ctypes.byref(overflows),
                        error,
                        len(error),
                    )
                if status:
                    detail = error.value.decode("utf-8", errors="replace")
                    raise RuntimeError(
                        "Native LMSRAW selection failed: " + detail
                    )
                events += photons.value
                overflow += overflows.value
                processed += stop - first
                if job.progress:
                    job.progress(
                        "Native LMSRAW selection: "
                        f"{processed}"
                        "/"
                        f"{total}"
                        " rows ("
                        f"{job.threads}"
                        " threads)"
                    )
                _check_cancelled(job.cancelled)
    return (events, overflow)


# Retain raw decoder keywords used by preview and export callers.
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def decode_selected_raw(
    dataset: DatasetInfo,
    bins: int = 128,
    linear_plane: int | None = None,
    progress: Progress | None = None,
    cancelled: CancelCheck | None = None,
    threads: int | None = None,
    prefer_native: bool = True,
    prepared: RawPreparedDecoder | None = None,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    grid: TimeGrid | None = None,
) -> HistogramCube:
    """Use identical selection semantics in the Python and native
    paths.
    """
    started = perf_counter()
    if bins < 1:
        raise ValueError("Histogram bins must be positive")
    if dataset.repetition_storage_model == "unresolved":
        raise RuntimeError(dataset.dimension_status)
    if (
        dataset.mosaic is not None
        and dataset.tile_index is None
        and linear_plane is None
    ):
        raise ValueError(
            "Select a mosaic tile; different stage positions cannot be summed"
        )
    mode = normalize_selection(event_flag_mask, "lmsraw")
    threshold = (
        int(dead_time_info(dataset)["minimumSubsequentArrivalDeltaBins"])
        if mode == RAW_ALL_PHOTONS
        else 0
    )
    period = native_period_bins(
        dataset.clock_period_s, dataset.laser_frequency_hz
    )
    if prepared is not None and prepared.dataset.key != dataset.key:
        raise ValueError("Prepared decoder belongs to another recorded pair")
    decoder = prepared or RawPreparedDecoder(dataset)
    try:
        ranges = (
            [
                dataset.plane_row_range(index)
                for index in range(dataset.plane_count)
            ]
            if linear_plane is None
            else [dataset.plane_row_range(linear_plane)]
        )
        for first, length in ranges:
            if (
                first < 0
                or length <= 0
                or first + length > dataset.decoded_rows
            ):
                raise RuntimeError("LMSRAW plane range exceeds the line table")
        counts = np.zeros(
            (bins, dataset.height, dataset.width), dtype=np.uint32
        )
        library = None
        if prefer_native:
            try:
                library = load_filter_library()
            except OSError:
                library = None
        thread_count = min(64, max(1, (threads or os.cpu_count() or 1)))
        job = _RawSelection(
            dataset,
            decoder,
            counts,
            ranges,
            mode,
            period,
            threshold,
            linear_plane,
            thread_count,
            progress,
            cancelled,
            grid,
        )
        if library is None:
            totals = _decode_python(job)
            backend = "lmsraw-selection-python"
            thread_count = 1
        else:
            totals = _decode_native(job, library)
            backend = (
                "lmsraw-native-all-valid"
                if mode == RAW_ALL_PHOTONS
                else "lmsraw-native-event-filter"
            )
        cube = HistogramCube(
            time_grid=grid,
            counts=counts,
            events=totals[0],
            overflow_events=totals[1],
            period_bins=grid.bins if grid is not None else period,
            decoded_rows=sum((size for _, size in ranges)),
            backend=backend,
            elapsed_seconds=perf_counter() - started,
            thread_count=thread_count,
            output_bits=32,
            reference_events=decoder.reference_events(linear_plane),
            source_dataset_key=dataset.key,
            linear_plane=linear_plane,
            event_difference=None,
            event_flag_mask=mode,
            included_event_flags=(
                "first photons and dead-time-qualified subsequent photons"
                if mode == RAW_ALL_PHOTONS
                else "first-in-cycle flag"
                if mode == RAW_FIRST_PHOTONS
                else "complete cycles containing exactly one event",
            ),
        )
        if cube.reference_events is not None:
            cube.event_difference = cube.events - cube.reference_events
        return align_cube_to_linked_intensity(cube, dataset, linear_plane)
    finally:
        if prepared is None:
            decoder.close()
