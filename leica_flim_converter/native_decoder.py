"""ctypes bridge to the native Leica histogram decoder with oracle
fallback.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .calibrated_histogram import decode_calibrated
from .decay import native_period_bins
from .event_flags import (
    PRIMARY_EVENT_FLAGS,
    compressed_route_mask,
    marker_labels,
    normalize_selection,
)
from .histogram_core import (
    DecodeCancelled,
    HistogramCube,
    align_cube_to_linked_intensity,
    decode_histogram_cube_python,
    decode_histogram_plane_python,
)
from .linked_intensity import read_intensity_plane
from .platform_paths import native_library_candidates
from .raw_decoder import RawPreparedDecoder
from .raw_selection import decode_selected_raw
from .timing import TimeGrid

API_VERSION = 6


class NativeDecoderUnavailableError(RuntimeError):
    """Represent native decoder unavailable error."""


# This passive ctypes record must match the native C structure exactly.
# pylint: disable-next=too-few-public-methods
class NativeDecodeResult(ctypes.Structure):
    """The exact decoder result structure from C++."""

    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("time_bins", ctypes.c_uint32),
        ("decoded_rows", ctypes.c_uint32),
        ("photon_count", ctypes.c_uint64),
        ("overflow_count", ctypes.c_uint64),
        ("output_bits", ctypes.c_uint32),
        ("elapsed_seconds", ctypes.c_double),
    ]


ProgressCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p
)


def _candidate_paths() -> list[Path]:
    return native_library_candidates("LeicaFlimDecoder")


def native_library_path() -> Path | None:
    """Compute native library path."""
    return next((path for path in _candidate_paths() if path.is_file()), None)


def _load_library() -> ctypes.CDLL:
    path = native_library_path()
    if path is None:
        raise NativeDecoderUnavailable("LeicaFlimDecoder.dll is not installed")
    try:
        library = ctypes.CDLL(str(path))
    except OSError as exc:
        raise NativeDecoderUnavailable(
            f"Could not load {path}: {exc}"
        ) from exc
    library.leica_decoder_api_version.restype = ctypes.c_uint32
    library.leica_decoder_version.restype = ctypes.c_char_p
    library.leica_recommended_threads.restype = ctypes.c_uint32
    if library.leica_decoder_api_version() != API_VERSION:
        raise NativeDecoderUnavailable(
            "Native decoder API "
            f"{library.leica_decoder_api_version()}"
            " is incompatible with "
            f"{API_VERSION}"
        )
    library.leica_decode_histogram.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint64,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint64,
        ProgressCallback,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(NativeDecodeResult),
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    library.leica_decode_histogram.restype = ctypes.c_int
    library.leica_prepare_block.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    library.leica_prepare_block.restype = ctypes.c_int
    library.leica_decode_row_range.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint64,
        ProgressCallback,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(NativeDecodeResult),
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    library.leica_decode_row_range.restype = ctypes.c_int
    library.leica_release_block.argtypes = [ctypes.c_void_p]
    library.leica_release_block.restype = None
    if hasattr(library, "leica_decode_raw_batch"):
        library.leica_decode_raw_batch.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint32),
            *[ctypes.c_uint32] * 7,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        library.leica_decode_raw_batch.restype = ctypes.c_int
    return library


def _native_row_model(dataset) -> int:
    if dataset.repetition_storage_model == "unresolved":
        raise RuntimeError(dataset.dimension_status)
    return int(dataset.repetition_storage_model == "explicit-line-repeat-rows")


class NativePreparedDecoder:
    """Keep one compressed buffer and native row table alive across
    plane decodes.
    """

    def __init__(self, dataset) -> None:
        if dataset.repetition_storage_model == "unresolved":
            raise RuntimeError(dataset.dimension_status)
        if dataset.storage_format == "lmsraw":
            raise NativeDecoderUnavailable(
                "LMSRAW uses the bounded streaming decoder, not "
                "the compressed DLL"
            )
        self.dataset = dataset
        self.library = _load_library()
        with dataset.source.open("rb") as handle:
            handle.seek(dataset.block_start)
            self.block = handle.read(dataset.block_end - dataset.block_start)
        self.block_array = np.frombuffer(self.block, dtype=np.uint8)
        self.context = ctypes.c_void_p()
        rows = ctypes.c_uint32()
        error = ctypes.create_string_buffer(2048)
        status = self.library.leica_prepare_block(
            self.block_array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            self.block_array.nbytes,
            ctypes.byref(self.context),
            ctypes.byref(rows),
            error,
            len(error),
        )
        if status != 0:
            message = (
                error.value.decode("utf-8", errors="replace")
                or f"native status {status}"
            )
            raise RuntimeError(f"Native Leica prepare failed: {message}")
        if (rows.value) != dataset.decoded_rows:
            self.close()
            raise RuntimeError(
                "Native prepared row mismatch: "
                f"{rows.value}"
                " != "
                f"{dataset.decoded_rows}"
            )

    def close(self) -> None:
        """Release owned native handles and mapped source resources."""
        if getattr(self, "context", None) and self.context.value:
            self.library.leica_release_block(self.context)
            self.context = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def reference_events(self, linear_plane: int) -> int | None:
        """Reference events."""
        values = read_intensity_plane(self.dataset, linear_plane)
        if values is None:
            return None
        return int(np.rint(values).astype(np.uint64).sum())

    def decode_plane(
        self,
        linear_plane: int,
        bins: int = 128,
        threads: int | None = None,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        event_flag_mask: int = PRIMARY_EVENT_FLAGS,
        grid: TimeGrid | None = None,
    ) -> HistogramCube:
        """Compute decode plane."""
        if not 0 <= linear_plane < self.dataset.plane_count:
            raise IndexError(linear_plane)
        thread_count = max(
            1, int(threads or self.library.leica_recommended_threads())
        )
        counts = np.zeros(
            (bins, self.dataset.height, self.dataset.width), dtype=np.uint32
        )
        cancel_flag = ctypes.c_uint32(0)

        def report(completed: int, total: int, _user_data) -> None:
            """Compute report."""
            if cancelled and cancelled():
                cancel_flag.value = 1
            if progress:
                progress(
                    "Native plane decoder: "
                    f"{completed}"
                    "/"
                    f"{total}"
                    " rows ("
                    f"{thread_count}"
                    " threads)"
                )

        callback = ProgressCallback(report)
        result = NativeDecodeResult()
        error = ctypes.create_string_buffer(2048)
        first_row, row_count = self.dataset.plane_row_range(linear_plane)
        lookup = grid.lookup() if grid is not None else None
        status = self.library.leica_decode_row_range(
            self.context,
            first_row,
            row_count,
            self.dataset.width,
            self.dataset.height,
            bins,
            native_period_bins(
                self.dataset.clock_period_s, self.dataset.laser_frequency_hz
            ),
            lookup.ctypes.data if lookup is not None else None,
            lookup.size if lookup is not None else 0,
            self.dataset.line_repetitions,
            _native_row_model(self.dataset),
            compressed_route_mask(
                normalize_selection(
                    event_flag_mask, self.dataset.storage_format
                ),
                self.dataset.detector_route,
            ),
            thread_count,
            counts.ctypes.data,
            counts.nbytes,
            callback,
            None,
            ctypes.byref(cancel_flag),
            ctypes.byref(result),
            error,
            len(error),
        )
        if status == 1:
            raise DecodeCancelled("Native plane decode cancelled")
        if status != 0:
            message = (
                error.value.decode("utf-8", errors="replace")
                or f"native status {status}"
            )
            raise RuntimeError(f"Native Leica plane decode failed: {message}")
        reference = self.reference_events(linear_plane)
        cube = HistogramCube(
            event_flag_mask=event_flag_mask,
            included_event_flags=marker_labels(
                event_flag_mask, self.dataset.detector_route
            ),
            time_grid=grid,
            counts=counts,
            events=int(result.photon_count),
            overflow_events=int(result.overflow_count),
            period_bins=grid.bins
            if grid is not None
            else native_period_bins(
                self.dataset.clock_period_s, self.dataset.laser_frequency_hz
            ),
            decoded_rows=int(result.decoded_rows),
            backend="native-range",
            elapsed_seconds=float(result.elapsed_seconds),
            thread_count=thread_count,
            output_bits=int(result.output_bits),
            reference_events=reference,
            source_dataset_key=self.dataset.key,
            linear_plane=linear_plane,
            event_difference=int(result.photon_count) - reference
            if reference is not None
            else None,
        )
        return align_cube_to_linked_intensity(cube, self.dataset, linear_plane)


def native_decoder_info() -> dict:
    """Compute native decoder info."""
    try:
        library = _load_library()
    except NativeDecoderUnavailable as exc:
        return {
            "available": False,
            "reason": str(exc),
            "apiVersion": API_VERSION,
        }
    return {
        "available": True,
        "path": str(native_library_path()),
        "apiVersion": int(library.leica_decoder_api_version()),
        "version": library.leica_decoder_version().decode(
            "ascii", errors="replace"
        ),
        "recommendedThreads": int(library.leica_recommended_threads()),
        "rawAvailable": hasattr(library, "leica_decode_raw_batch"),
    }


def _decode_native(
    dataset,
    bins: int,
    threads: int | None,
    progress: Callable[[str], None] | None,
    cancelled: Callable[[], bool] | None,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    grid: TimeGrid | None = None,
) -> HistogramCube:
    library = _load_library()
    row_model = _native_row_model(dataset)
    recommended = int(library.leica_recommended_threads())
    thread_count = max(1, (threads or recommended))
    with dataset.source.open("rb") as handle:
        handle.seek(dataset.block_start)
        block = handle.read(dataset.block_end - dataset.block_start)
    block_array = np.frombuffer(block, dtype=np.uint8)
    counts = np.zeros((bins, dataset.height, dataset.width), dtype=np.uint32)
    cancel_flag = ctypes.c_uint32(0)

    def report(completed: int, total: int, _user_data) -> None:
        """Compute report."""
        if cancelled and cancelled():
            cancel_flag.value = 1
        if progress:
            progress(
                "Native decoder: "
                f"{completed}"
                "/"
                f"{total}"
                " rows ("
                f"{thread_count}"
                " threads)"
            )

    callback = ProgressCallback(report)
    result = NativeDecodeResult()
    error = ctypes.create_string_buffer(2048)
    lookup = grid.lookup() if grid is not None else None
    status = library.leica_decode_histogram(
        block_array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        block_array.nbytes,
        dataset.width,
        dataset.height,
        bins,
        native_period_bins(dataset.clock_period_s, dataset.laser_frequency_hz),
        lookup.ctypes.data if lookup is not None else None,
        lookup.size if lookup is not None else 0,
        dataset.line_repetitions,
        row_model,
        compressed_route_mask(
            normalize_selection(event_flag_mask, dataset.storage_format),
            dataset.detector_route,
        ),
        thread_count,
        counts.ctypes.data,
        counts.nbytes,
        callback,
        None,
        ctypes.byref(cancel_flag),
        ctypes.byref(result),
        error,
        len(error),
    )
    if status == 1:
        raise DecodeCancelled("Native histogram decode cancelled")
    if status != 0:
        message = (
            error.value.decode("utf-8", errors="replace")
            or f"native status {status}"
        )
        raise RuntimeError(f"Native Leica decoder failed: {message}")
    if result.decoded_rows != dataset.decoded_rows:
        raise RuntimeError(
            "Native row mismatch: "
            f"{result.decoded_rows}"
            " != "
            f"{dataset.decoded_rows}"
        )
    cube = HistogramCube(
        event_flag_mask=event_flag_mask,
        included_event_flags=marker_labels(
            event_flag_mask, dataset.detector_route
        ),
        time_grid=grid,
        counts=counts,
        events=int(result.photon_count),
        overflow_events=int(result.overflow_count),
        period_bins=grid.bins
        if grid is not None
        else native_period_bins(
            dataset.clock_period_s, dataset.laser_frequency_hz
        ),
        decoded_rows=int(result.decoded_rows),
        backend="native",
        elapsed_seconds=float(result.elapsed_seconds),
        thread_count=thread_count,
        output_bits=int(result.output_bits),
        reference_events=dataset.total_photons,
        source_dataset_key=dataset.key,
        event_difference=int(result.photon_count) - dataset.total_photons
        if dataset.total_photons is not None
        else None,
    )
    return align_cube_to_linked_intensity(cube, dataset)


def decode_histogram_cube(
    dataset,
    bins: int = 128,
    threads: int | None = None,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    prefer_native: bool = True,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    grid: TimeGrid | None = None,
) -> HistogramCube:
    """Compute decode histogram cube."""
    if dataset.mosaic is not None and dataset.tile_index is None:
        raise ValueError(
            "Select a mosaic tile; stage positions cannot be summed"
        )
    event_flag_mask = normalize_selection(
        event_flag_mask, dataset.storage_format
    )
    if dataset.storage_format == "lmsraw":
        return decode_selected_raw(
            dataset,
            event_flag_mask=event_flag_mask,
            bins=bins,
            progress=progress,
            cancelled=cancelled,
            threads=threads,
            prefer_native=prefer_native,
            grid=grid,
        )
    if prefer_native:
        try:
            return _decode_native(
                dataset,
                bins,
                threads,
                progress,
                cancelled,
                event_flag_mask,
                grid,
            )
        except NativeDecoderUnavailable as exc:
            if progress:
                progress(
                    "Native decoder unavailable; using verified "
                    "Python oracle ("
                    f"{exc}"
                    ")"
                )
    if grid is not None:
        return decode_calibrated(
            dataset,
            grid,
            None,
            event_flag_mask,
            progress or (lambda _m: None),
            cancelled or (lambda: False),
        )
    return decode_histogram_cube_python(
        dataset,
        bins=bins,
        progress=progress,
        cancelled=cancelled,
        event_flag_mask=event_flag_mask,
    )


# Retain the plane decoder interface and its 2.4 selection argument.
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def decode_histogram_plane(
    dataset,
    linear_plane: int,
    bins: int = 128,
    threads: int | None = None,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    prepared: NativePreparedDecoder | RawPreparedDecoder | None = None,
    prefer_native: bool = True,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    grid: TimeGrid | None = None,
) -> HistogramCube:
    """Compute decode histogram plane."""
    event_flag_mask = normalize_selection(
        event_flag_mask, dataset.storage_format
    )
    if dataset.storage_format == "lmsraw":
        if isinstance(prepared, RawPreparedDecoder):
            return decode_selected_raw(
                dataset,
                bins=bins,
                linear_plane=linear_plane,
                threads=threads,
                progress=progress,
                cancelled=cancelled,
                prepared=prepared,
                event_flag_mask=event_flag_mask,
                prefer_native=prefer_native,
                grid=grid,
            )
        return decode_selected_raw(
            dataset,
            event_flag_mask=event_flag_mask,
            bins=bins,
            linear_plane=linear_plane,
            progress=progress,
            cancelled=cancelled,
            threads=threads,
            prefer_native=prefer_native,
            grid=grid,
        )
    if prepared is not None:
        if not isinstance(prepared, NativePreparedDecoder):
            raise ValueError(
                "Compressed data requires a compressed prepared decoder"
            )
        if prepared.dataset.key != dataset.key:
            raise ValueError(
                "Prepared decoder belongs to another recorded pair"
            )
        return prepared.decode_plane(
            linear_plane,
            bins,
            threads,
            progress,
            cancelled,
            event_flag_mask,
            grid,
        )
    if prefer_native:
        try:
            with NativePreparedDecoder(dataset) as context:
                return context.decode_plane(
                    linear_plane,
                    bins,
                    threads,
                    progress,
                    cancelled,
                    event_flag_mask,
                    grid,
                )
        except NativeDecoderUnavailable as exc:
            if progress:
                progress(
                    "Native decoder unavailable; using Python "
                    "plane oracle ("
                    f"{exc}"
                    ")"
                )
    if grid is not None:
        return decode_calibrated(
            dataset,
            grid,
            linear_plane,
            event_flag_mask,
            progress or (lambda _m: None),
            cancelled or (lambda: False),
        )
    return decode_histogram_plane_python(
        dataset,
        linear_plane,
        bins=bins,
        progress=progress,
        cancelled=cancelled,
        event_flag_mask=event_flag_mask,
    )


NativeDecoderUnavailable = NativeDecoderUnavailableError
