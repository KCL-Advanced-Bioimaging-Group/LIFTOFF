"""Selected-block PicoQuant PTU export for LIFTOFF."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .acquisition_metadata import acquisition_metadata
from .dataset import DatasetInfo
from .event_flags import (
    PRIMARY_EVENT_FLAGS,
    filename_suffix,
    normalize_selection,
    selection_name,
)
from .export_companions import (
    cleanup_export,
    export_path_available,
    write_companions,
)
from .header_metadata import ptu_header_mappings
from .ics import proposed_ics_filenames, sanitize_ics_basename
from .photon_selection import (
    dataset_selection_metadata,
    indexed_logical_lines,
)
from .photon_stream import (
    PhotonStreamCancelled,
    _compressed_rows,
    iter_lmsraw_vectors,
)
from .ptu import GenericT3Writer, VectorEvents, build_header
from .raster_timing import raster_timing
from .reflection_export import ReflectionWindow, reflection_window
from .spatial_metadata import source_metadata, spatial_calibration
from .timing import recorded_timing, require_calibration
from .version import application_metadata

BatchProgress = Callable[[str, float, float], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class PtuExportOptions:
    """Immutable raster clock, collision and selection options."""

    pixel_ticks: int = 3
    collision: str = "suffix"
    event_flag_mask: int = PRIMARY_EVENT_FLAGS
    timing_mode: str = "auto"
    reflection_windows: tuple[ReflectionWindow, ...] = ()

    def validate(self) -> None:
        """Reject unsupported options before beginning any export."""
        normalize_selection(self.event_flag_mask, "compressed")
        for window in self.reflection_windows:
            window.validate()
        if self.timing_mode not in ("auto", "synthetic", "reconstructed"):
            raise ValueError(
                "PTU timing mode must be auto, synthetic or reconstructed"
            )
        if not 1 <= self.pixel_ticks <= 1024:
            raise ValueError("PTU pixel ticks must be between 1 and 1024")
        if self.collision not in ("suffix", "skip"):
            raise ValueError("PTU collision handling must be suffix or skip")


_DEFAULT_OPTIONS = PtuExportOptions()


def proposed_ptu_filenames(datasets: Iterable[DatasetInfo]) -> dict[str, str]:
    """Compute proposed ptu filenames."""
    return {
        key: str(Path(value).with_suffix(".ptu"))
        for key, value in proposed_ics_filenames(datasets).items()
    }


def _collision_target(
    destination: Path, filename: str, policy: str
) -> Path | None:
    target = destination / filename
    if export_path_available(target):
        return target
    if policy == "skip":
        return None
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if export_path_available(candidate):
            return candidate
        index += 1
    return None


def _row_key(
    dataset: DatasetInfo, line: int, first_row: int
) -> tuple[int, int]:
    relative = line - first_row
    if dataset.repetition_storage_model == "explicit-line-repeat-rows":
        rows_per_frame = dataset.height * dataset.line_repetitions
        return (
            relative // rows_per_frame,
            relative % rows_per_frame // dataset.line_repetitions,
        )
    return (relative // dataset.height, relative % dataset.height)


@dataclass
class _RasterLineBuffer:
    """Pool repetitions into one logical scan line before vector
    encoding.
    """

    dataset: DatasetInfo
    first_row: int
    writer: GenericT3Writer
    vectorized: bool = False
    current_key: tuple[int, int] | None = None
    logical_lines: int = 0
    events: list[tuple[int, int, int]] = field(default_factory=list)
    x_chunks: list[np.ndarray] = field(default_factory=list)
    microtime_chunks: list[np.ndarray] = field(default_factory=list)
    reflection: ReflectionWindow | None = None
    reflection_excluded: int = 0

    def flush(self) -> None:
        """Emit one accumulated line with its frame and line markers."""
        if self.current_key is None:
            return
        frame, y = self.current_key
        if self.vectorized:
            if len(self.x_chunks) == 1:
                x_values = self.x_chunks[0]
                microtime_values = self.microtime_chunks[0]
            else:
                x_values = (
                    np.concatenate(self.x_chunks)
                    if self.x_chunks
                    else np.empty(0, dtype=np.int32)
                )
                microtime_values = (
                    np.concatenate(self.microtime_chunks)
                    if self.microtime_chunks
                    else np.empty(0, dtype=np.int32)
                )
            self.writer.write_line(
                VectorEvents(x_values, microtime_values),
                frame_start=y == 0,
                frame=frame,
                y=y,
            )
        else:
            self.writer.write_line(
                self.events, frame_start=y == 0, frame=frame, y=y
            )
        self.logical_lines += 1
        self.events = []
        self.x_chunks = []
        self.microtime_chunks = []

    def _advance(self, line: int) -> None:
        key = _row_key(self.dataset, line, self.first_row)
        if self.current_key is not None and key != self.current_key:
            self.flush()
        self.current_key = key

    def consume(self, line: int, events: list[tuple[int, int, int]]) -> None:
        """Append a compressed row to its logical line."""
        self._advance(line)
        if self.reflection is not None:
            kept = [
                event
                for event in events
                if not self.reflection.lower
                <= event[1]
                <= self.reflection.upper
            ]
            self.reflection_excluded += len(events) - len(kept)
            events = kept
        self.events.extend(events)

    def consume_vectors(
        self, line: int, x: np.ndarray, microtime: np.ndarray
    ) -> None:
        """Append selected raw photons without per-photon Python
        objects.
        """
        self._advance(line)
        if self.reflection is not None:
            excluded = self.reflection.excludes(microtime)
            self.reflection_excluded += int(np.count_nonzero(excluded))
            x, microtime = x[~excluded], microtime[~excluded]
        self.x_chunks.append(np.asarray(x, dtype=np.int32))
        self.microtime_chunks.append(np.asarray(microtime, dtype=np.int32))


def _dataset_ptu_header(
    dataset: DatasetInfo,
    target: Path,
    options: PtuExportOptions,
    linear_plane: int,
) -> tuple[bytes, int, int, float]:
    """Build the calibrated Generic T3 header for compressed or raw
    detectors.
    """
    microtime_resolution, frequency = require_calibration(dataset)
    sync_rate = round(frequency)
    if sync_rate < 1:
        raise ValueError("PTU requires a laser frequency of at least 1 Hz")
    timeline = raster_timing(dataset, options.timing_mode, options.pixel_ticks)
    metadata = _ptu_acquisition_metadata(dataset, linear_plane, options)
    axes = metadata["spatialCalibration"]["axes"]
    pixel_x, pixel_y = axes["x"]["spacingMetres"], axes["y"]["spacingMetres"]
    # The standard scalar cannot represent unknown or unequal X/Y.
    pixel_size_um = (
        pixel_x * 1e6 if pixel_x is not None and pixel_x == pixel_y else None
    )
    header, count_offset = build_header(
        filename=target.stem,
        width=dataset.width,
        height=dataset.height,
        microtime_resolution_s=microtime_resolution,
        sync_rate_hz=sync_rate,
        global_resolution_s=1.0 / frequency,
        timing_quality=timeline.quality,
        pixel_size_um=pixel_size_um,
        input_channels=2 if dataset.storage_format == "compressed" else 1,
        metadata=metadata,
    )
    return (header, count_offset, sync_rate, microtime_resolution)


def _ptu_acquisition_metadata(
    dataset: DatasetInfo, linear_plane: int, options: PtuExportOptions
) -> dict:
    """Keep header and sidecar summaries identical for this output."""
    metadata = acquisition_metadata(dataset, linear_plane)
    metadata["eventSelection"] = dataset_selection_metadata(
        dataset, options.event_flag_mask
    )
    window = reflection_window(
        options.reflection_windows, dataset, linear_plane
    )
    metadata["reflectionFilter"] = (
        window.metadata(dataset.clock_period_s)
        if window
        else {"enabled": False}
    )
    _clock, frequency = require_calibration(dataset)
    metadata["rasterTiming"] = raster_timing(
        dataset, options.timing_mode, options.pixel_ticks
    ).metadata(1.0 / frequency)
    metadata["headerMappings"] = ptu_header_mappings(metadata)
    return metadata


def _ptu_metadata(
    dataset: DatasetInfo,
    linear_plane: int,
    target: Path,
    options: PtuExportOptions,
    writer: GenericT3Writer,
    sync_rate: int,
    microtime_resolution: float,
) -> dict:
    """Describe measured photon fields and the explicitly reconstructed
    raster clock.
    """
    t_index, z_index = dataset.plane_indices(linear_plane)
    _clock, frequency = require_calibration(dataset)
    timeline = raster_timing(dataset, options.timing_mode, options.pixel_ticks)
    return {
        "format": "PicoQuant PTU Generic T3",
        "acquisitionMetadata": _ptu_acquisition_metadata(
            dataset, linear_plane, options
        ),
        "path": str(target),
        "recordType": "0x00010307",
        "bitsPerRecord": 32,
        "records": writer.stats.records,
        "photons": writer.stats.photons,
        "primaryPhotons": writer.stats.primary_photons,
        "referencePhotons": writer.stats.reference_photons,
        "lineMarkers": writer.stats.line_markers,
        "frameMarkers": writer.stats.frame_markers,
        "overflowWrapsRepresented": writer.stats.overflows,
        "linearPlane": linear_plane,
        "tIndexZeroBased": t_index,
        "zIndexZeroBased": z_index,
        "planeCoverage": dataset.plane_coverage_metadata,
        "width": dataset.width,
        "height": dataset.height,
        "frameRepetitions": dataset.frame_repetitions,
        "indexedEncodedRows": dataset.plane_row_range(linear_plane)[1],
        "nominalEncodedRows": dataset.rows_per_plane,
        "indexedFrameCount": writer.stats.frame_markers,
        "lineRepetitionsSummed": dataset.line_repetitions,
        "pixelTicks": timeline.pixel_ticks,
        "syntheticPixelTicksSetting": options.pixel_ticks,
        "syncRateHz": sync_rate,
        "globalResolutionSeconds": 1.0 / frequency,
        "timingQuality": timeline.quality,
        "rasterTiming": timeline.metadata(1.0 / frequency),
        "recordedTiming": recorded_timing(dataset).metadata(),
        "microtimeResolutionSeconds": microtime_resolution,
        "macrotimeInterpretation": (
            "reconstructed nominal raster clock"
            if timeline.quality == "Reconstructed"
            else "synthetic raster clock"
        ),
        "microtimeInterpretation": "native decoded Leica arrival value",
        "eventSelection": dataset_selection_metadata(
            dataset, options.event_flag_mask
        ),
    }


def write_dataset_ptu(
    dataset: DatasetInfo,
    linear_plane: int,
    target: Path,
    options: PtuExportOptions,
    *,
    progress: Callable[[str], None],
    cancelled: CancelCheck,
) -> dict:
    """Compute write dataset ptu."""
    options.validate()
    if dataset.repetition_storage_model == "unresolved":
        raise RuntimeError(dataset.dimension_status)
    if dataset.storage_format == "lmsraw":
        return fast_lmsraw_writer(
            dataset,
            linear_plane,
            target,
            options,
            progress=progress,
            cancelled=cancelled,
        )
    first_row, row_count = dataset.plane_row_range(linear_plane)
    header, count_offset, sync_rate, microtime_resolution = (
        _dataset_ptu_header(dataset, target, options, linear_plane)
    )
    temporary = target.with_name(target.name + ".part")
    try:
        with temporary.open("w+b") as handle:
            handle.write(header)
            writer = GenericT3Writer(
                handle,
                width=dataset.width,
                pixel_ticks=options.pixel_ticks,
                timing=raster_timing(
                    dataset, options.timing_mode, options.pixel_ticks
                ),
            )
            buffer = _RasterLineBuffer(
                dataset,
                first_row,
                writer,
                vectorized=False,
                reflection=reflection_window(
                    options.reflection_windows, dataset, linear_plane
                ),
            )
            decode = _compressed_rows
            decode(
                dataset,
                first_row,
                row_count,
                buffer.consume,
                progress,
                cancelled,
                options.event_flag_mask,
            )
            buffer.flush()
            expected_lines = indexed_logical_lines(dataset, linear_plane)
            if buffer.logical_lines != expected_lines:
                raise RuntimeError(
                    "PTU logical line mismatch: "
                    f"{buffer.logical_lines}"
                    " != "
                    f"{expected_lines}"
                )
            handle.seek(count_offset)
            handle.write(
                (writer.stats.records).to_bytes(8, "little", signed=True)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return _filtered_ptu_metadata(
        dataset,
        linear_plane,
        target,
        options,
        writer,
        sync_rate,
        microtime_resolution,
        buffer,
    )


@dataclass(frozen=True)
class _PtuBatch:
    """Shared selection, naming and progress context for PTU outputs."""

    default_destination: Path
    destinations: Mapping[str, str | Path]
    names: Mapping[str, str]
    report: BatchProgress
    is_cancelled: CancelCheck
    selections: dict[str, list[int]]
    total: int
    options: PtuExportOptions


def _export_ptu_dataset(
    dataset: DatasetInfo, batch: _PtuBatch, completed: int
) -> tuple[list[dict], int]:
    """Write independently recoverable PTU outputs and provenance
    sidecars.
    """
    results: list[dict] = []
    destination = (
        Path(batch.destinations.get(dataset.key, batch.default_destination))
        .expanduser()
        .resolve()
    )
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        for plane in batch.selections[dataset.key]:
            results.append(
                {
                    "dataset": dataset.display_name,
                    "status": "failed",
                    "linearPlane": plane,
                    "error": (
                        f"Cannot create output folder {destination}: {exc}"
                    ),
                }
            )
        completed += len(batch.selections[dataset.key])
        batch.report(f"Could not create {destination}", completed, batch.total)
        return (results, completed)
    base = sanitize_ics_basename(Path(batch.names[dataset.key]).stem)
    selection_suffix = filename_suffix(batch.options.event_flag_mask)
    if selection_suffix and (not base.endswith(selection_suffix)):
        base += selection_suffix
    for plane in batch.selections[dataset.key]:
        if batch.is_cancelled():
            raise PtuExportCancelled("PTU batch export cancelled")
        suffix = (
            f"_{dataset.plane_label(plane)}" if dataset.plane_count > 1 else ""
        )
        filename = f"{base}{suffix}.ptu"
        target = _collision_target(
            destination, filename, batch.options.collision
        )
        if target is None:
            results.append(
                {
                    "dataset": dataset.display_name,
                    "status": "skipped",
                    "path": str(destination / filename),
                    "linearPlane": plane,
                }
            )
            completed += 1
            continue
        try:
            export = write_dataset_ptu(
                dataset,
                plane,
                target,
                batch.options,
                progress=lambda message, current=completed: batch.report(
                    message, current, batch.total
                ),
                cancelled=batch.is_cancelled,
            )
            sidecar = {
                "application": application_metadata(),
                "sourceLif": str(dataset.source),
                "memoryBlockID": dataset.memory_id,
                "datasetKey": dataset.key,
                "sequence": dataset.sequence_metadata,
                "opticalMetadata": dataset.optical_metadata,
                "acquisitionMetadata": export["acquisitionMetadata"],
                "spatialCalibration": spatial_calibration(dataset),
                "sourceMetadata": source_metadata(dataset),
                "timing": recorded_timing(dataset).metadata(),
                "mosaic": dataset.mosaic_metadata(plane),
                "leicaNames": {
                    "acquisition": dataset.acquisition_name,
                    "series": dataset.series_name,
                    "channel": dataset.channel_name,
                    "detector": dataset.detector_name,
                },
                "sourceStorage": {
                    "format": dataset.storage_format,
                    "channelIndexZeroBased": dataset.channel_index,
                    "channelCount": dataset.channel_count,
                    "repetitionStorageModel": dataset.repetition_storage_model,
                },
                "known": [
                    "photon count",
                    "pixel coordinates",
                    "microtime values",
                    "detector route",
                    "image dimensions",
                ],
                "inferred": [
                    export["macrotimeInterpretation"].replace(
                        "clock", "macrotime"
                    ),
                    "scan marker timing",
                ],
                "export": export,
            }
            reports = write_companions(target, sidecar)
            results.append(
                {
                    "dataset": dataset.display_name,
                    "status": "exported",
                    "path": str(target),
                    "sidecar": str(target) + ".json",
                    "metadataReports": reports,
                    "events": export["photons"],
                    "excludedReflectionPhotons": export[
                        "excludedReflectionPhotons"
                    ],
                    "linearPlane": plane,
                }
            )
        except PtuExportCancelled:
            raise
        # Convert unexpected worker failures into explicit user-facing
        # errors.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:
            cleanup_export(target)
            results.append(
                {
                    "dataset": dataset.display_name,
                    "status": "failed",
                    "linearPlane": plane,
                    "error": str(exc),
                }
            )
        completed += 1
        batch.report(
            f"Completed PTU {completed}/{batch.total}", completed, batch.total
        )
    return (results, completed)


def export_ptu_blocks(
    datasets: Iterable[DatasetInfo],
    output_dir: str | Path,
    options: PtuExportOptions = _DEFAULT_OPTIONS,
    *,
    filenames: Mapping[str, str] | None = None,
    plane_selection: Mapping[str, Iterable[int]] | None = None,
    output_directories: Mapping[str, str | Path] | None = None,
    progress: BatchProgress | None = None,
    cancelled: CancelCheck | None = None,
) -> list[dict]:
    """Compute export ptu blocks."""
    options.validate()
    selected = list(datasets)
    default_destination = Path(output_dir).expanduser().resolve()
    destinations = output_directories or {}
    names = dict(filenames or proposed_ptu_filenames(selected))
    report = progress or (lambda _message, _current, _total: None)
    is_cancelled = cancelled or (lambda: False)
    selections: dict[str, list[int]] = {}
    for dataset in selected:
        values = (
            list(plane_selection[dataset.key])
            if plane_selection is not None and dataset.key in plane_selection
            else list(range(dataset.plane_count))
        )
        selections[dataset.key] = sorted(set((value) for value in values))
    total = sum(map(len, selections.values()))
    completed = 0
    results: list[dict] = []
    batch = _PtuBatch(
        default_destination,
        destinations,
        names,
        report,
        is_cancelled,
        selections,
        total,
        options,
    )
    for dataset in selected:
        outputs, completed = _export_ptu_dataset(dataset, batch, completed)
        results.extend(outputs)
    return results


def fast_lmsraw_writer(
    dataset: DatasetInfo,
    linear_plane: int,
    target: Path,
    options: PtuExportOptions,
    *,
    progress: Callable[[str], None],
    cancelled: CancelCheck,
) -> dict:
    """Compute fast lmsraw writer."""
    first_row, row_count = dataset.plane_row_range(linear_plane)
    header, count_offset, sync_rate, microtime_resolution = (
        _dataset_ptu_header(dataset, target, options, linear_plane)
    )
    temporary = target.with_name(target.name + ".part")
    mode = normalize_selection(options.event_flag_mask, dataset.storage_format)
    try:
        with temporary.open("w+b") as handle:
            handle.write(header)
            writer = GenericT3Writer(
                handle,
                width=dataset.width,
                pixel_ticks=options.pixel_ticks,
                timing=raster_timing(
                    dataset, options.timing_mode, options.pixel_ticks
                ),
            )
            buffer = _RasterLineBuffer(
                dataset,
                first_row,
                writer,
                vectorized=True,
                reflection=reflection_window(
                    options.reflection_windows, dataset, linear_plane
                ),
            )
            update_interval = max(64, row_count // 200)
            iterator = iter_lmsraw_vectors(
                dataset, first_row, row_count, mode, cancelled
            )
            for relative, (line, x_values, microtime_values) in enumerate(
                iterator
            ):
                if cancelled():
                    raise PtuExportCancelled("PTU export cancelled")
                buffer.consume_vectors(line, x_values, microtime_values)
                if (relative + 1) % update_interval == 0:
                    progress(
                        "Vector-encoding "
                        f"{selection_name(mode)}"
                        " PTU events: "
                        f"{relative + 1}"
                        "/"
                        f"{row_count}"
                        " rows"
                    )
            buffer.flush()
            expected_lines = indexed_logical_lines(dataset, linear_plane)
            if buffer.logical_lines != expected_lines:
                raise RuntimeError(
                    "PTU logical line mismatch: "
                    f"{buffer.logical_lines}"
                    " != "
                    f"{expected_lines}"
                )
            handle.seek(count_offset)
            handle.write(
                (writer.stats.records).to_bytes(8, "little", signed=True)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return _filtered_ptu_metadata(
        dataset,
        linear_plane,
        target,
        options,
        writer,
        sync_rate,
        microtime_resolution,
        buffer,
    )


def _filtered_ptu_metadata(
    dataset: DatasetInfo,
    linear_plane: int,
    target: Path,
    options: PtuExportOptions,
    writer: GenericT3Writer,
    sync_rate: int,
    microtime_resolution: float,
    buffer: _RasterLineBuffer,
) -> dict:
    """Account for reflection photons without changing scan markers."""
    metadata = _ptu_metadata(
        dataset,
        linear_plane,
        target,
        options,
        writer,
        sync_rate,
        microtime_resolution,
    )
    metadata["reflectionFilter"] = (
        buffer.reflection.metadata(dataset.clock_period_s)
        if buffer.reflection
        else {"enabled": False}
    )
    metadata["excludedReflectionPhotons"] = buffer.reflection_excluded
    metadata["selectedPhotons"] = (
        writer.stats.photons + buffer.reflection_excluded
    )
    return metadata


PtuExportCancelled = PhotonStreamCancelled
