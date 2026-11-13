"""Memory-bounded, selected-block ICS export orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .acquisition_metadata import acquisition_metadata
from .dataset import DatasetInfo
from .event_flags import (
    PRIMARY_EVENT_FLAGS,
    filename_suffix,
    normalize_selection,
)
from .export_companions import (
    cleanup_export,
    export_path_available,
    write_companions,
)
from .histogram_core import DecodeCancelled, HistogramCube
from .ics import (
    ALLOWED_BINS,
    IcsExportCancelled,
    proposed_ics_filenames,
    sanitize_ics_basename,
    write_ics,
)
from .mosaic import MOSAIC_INTEGRATION_ERROR
from .native_decoder import (
    NativeDecoderUnavailable,
    NativePreparedDecoder,
    decode_histogram_cube,
    decode_histogram_plane,
    native_decoder_info,
)
from .photon_selection import dataset_selection_metadata
from .raw_decoder import RawPreparedDecoder
from .reflection_export import (
    ReflectionWindow,
    filter_native_cube,
    reflection_window,
)
from .spatial_metadata import source_metadata, spatial_calibration
from .timing import TimeGrid, recorded_timing, time_grid
from .version import application_metadata

BatchProgress = Callable[[str, float, float], None]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class IcsExportOptions:
    """Immutable binning, compression and selection options."""

    bins: int | None = 128
    compression: str = "gzip"
    collision: str = "suffix"
    threads: int | None = None
    dimension_mode: str = "split"
    event_flag_mask: int = PRIMARY_EVENT_FLAGS
    reflection_windows: tuple[ReflectionWindow, ...] = ()

    def validate(self) -> None:
        """Reject unsupported options before beginning any export."""
        normalize_selection(self.event_flag_mask, "compressed")
        for window in self.reflection_windows:
            window.validate()
        if self.bins is not None and self.bins not in ALLOWED_BINS:
            raise ValueError(f"ICS bins must be one of {ALLOWED_BINS}")
        if self.compression not in ("gzip", "uncompressed"):
            raise ValueError("ICS compression must be gzip or uncompressed")
        if self.collision not in ("suffix", "skip"):
            raise ValueError("ICS collision handling must be suffix or skip")
        if self.dimension_mode not in ("split", "integrate"):
            raise ValueError("ICS dimension mode must be split or integrate")


_DEFAULT_OPTIONS = IcsExportOptions()


def estimated_uncompressed_bytes(
    dataset: DatasetInfo, bins: int | None, dimension_mode: str = "split"
) -> int:
    """Compute estimated uncompressed bytes."""
    planes = dataset.plane_count if dimension_mode == "split" else 1
    return (
        dataset.width
        * dataset.height
        * time_grid(dataset, bins).bins
        * 2
        * planes
    )


def rebin_cube(
    cube: HistogramCube, bins: int, grid: TimeGrid | None = None
) -> HistogramCube | None:
    """Losslessly combine an existing cube; finer bins require a fresh
    decode.
    """
    if grid is not None and (
        cube.time_grid is None
        or cube.time_grid.clock_s != grid.clock_s
        or cube.time_grid.extent_s != grid.extent_s
    ):
        return None
    source_bins = int(cube.counts.shape[0])
    if source_bins == bins:
        return cube
    if bins > source_bins or source_bins % bins:
        return None
    factor = source_bins // bins
    if grid is not None and cube.time_grid is not None:
        source_edges = (
            np.arange(0, source_bins + 1, factor) * cube.time_grid.step_s
        )
        target_edges = np.arange(bins + 1) * grid.step_s
        if not np.array_equal(source_edges, target_edges):
            return None
    counts = cube.counts.reshape(bins, factor, *cube.counts.shape[1:]).sum(
        axis=1, dtype=np.uint64
    )
    maximum = int(counts.max(initial=0))
    if maximum > np.iinfo(np.uint32).max:
        raise OverflowError("Rebinned histogram exceeds uint32")
    dtype = np.uint16 if maximum <= np.iinfo(np.uint16).max else np.uint32
    counts = counts.astype(dtype)
    return HistogramCube(
        event_flag_mask=cube.event_flag_mask,
        included_event_flags=cube.included_event_flags,
        counts=counts,
        events=cube.events,
        overflow_events=cube.overflow_events,
        period_bins=cube.period_bins,
        decoded_rows=cube.decoded_rows,
        backend=f"{cube.backend} (rebinned)",
        elapsed_seconds=0.0,
        thread_count=cube.thread_count,
        output_bits=counts.dtype.itemsize * 8,
        reference_events=cube.reference_events,
        event_difference=cube.event_difference,
        spatial_transform=cube.spatial_transform,
        spatial_alignment_correlation=cube.spatial_alignment_correlation,
        spatial_alignment_absolute_error=cube.spatial_alignment_absolute_error,
        spatial_alignment_confirmed=cube.spatial_alignment_confirmed,
        source_dataset_key=cube.source_dataset_key,
        linear_plane=cube.linear_plane,
        time_grid=grid,
        reflection_excluded_events=cube.reflection_excluded_events,
    )


def _collision_target(
    destination: Path, filename: str, policy: str
) -> Path | None:
    target = destination / filename
    if export_path_available(target):
        return target
    if policy == "skip":
        return None
    stem, suffix = (target.stem, target.suffix)
    index = 2
    while True:
        candidate = destination / f"{stem}_{index}{suffix}"
        if export_path_available(candidate):
            return candidate
        index += 1
    return None


def _sidecar(
    dataset: DatasetInfo,
    cube: HistogramCube,
    export: dict,
    linear_plane: int | None = None,
    dimension_mode: str = "split",
) -> dict:
    if (
        linear_plane is None
        and dimension_mode == "split"
        and dataset.plane_count == 1
    ):
        linear_plane = 0
    laser_period = (
        1.0 / dataset.laser_frequency_hz
        if dataset.laser_frequency_hz
        else None
    )
    calibration = {
        "pixelSizeXMetres": dataset.pixel_size_x_m,
        "pixelSizeYMetres": dataset.pixel_size_y_m,
        "laserFrequencyHz": dataset.laser_frequency_hz,
        "laserRepetitionPeriodSeconds": laser_period,
        "clockPeriodSeconds": dataset.clock_period_s,
        "exportedTimeBinWidthSeconds": export["timeStepSeconds"],
    }
    spatial = spatial_calibration(dataset)
    unavailable = [
        f"pixelSize{axis.upper()}Metres"
        for axis in ("x", "y")
        if spatial["axes"][axis]["status"] == "unavailable"
    ]
    calibration["pixelSizeXMetres"] = spatial["axes"]["x"]["spacingMetres"]
    calibration["pixelSizeYMetres"] = spatial["axes"]["y"]["spacingMetres"]
    inferred = []
    if dataset.laser_frequency_hz is None:
        inferred.append("laserRepetitionPeriodSeconds")
    orientation_confirmed = cube.spatial_alignment_confirmed
    if not orientation_confirmed:
        inferred.append("axisOrder")
    confirmed = ["dimensions", "integerBits", "byteOrder", "totalPhotonCount"]
    if orientation_confirmed:
        confirmed.append("axisOrder")
    t_index = z_index = None
    if linear_plane is not None:
        t_index, z_index = dataset.plane_indices(linear_plane)
    first_encoded_row = (
        dataset.plane_row_ranges[0][0] if dataset.plane_row_ranges else 0
    )
    encoded_row_count = dataset.indexed_rows
    if linear_plane is not None:
        first_encoded_row, encoded_row_count = dataset.plane_row_range(
            linear_plane
        )
    return {
        "sourceLif": str(dataset.source),
        "memoryBlockID": dataset.memory_id,
        "datasetKey": dataset.key,
        "sequence": dataset.sequence_metadata,
        "opticalMetadata": dataset.optical_metadata,
        "acquisitionMetadata": export["acquisitionMetadata"],
        "spatialCalibration": spatial,
        "sourceMetadata": source_metadata(dataset),
        "timing": recorded_timing(dataset).metadata(),
        "histogramTiming": cube.time_grid.metadata()
        if cube.time_grid
        else None,
        "photonAccounting": {
            "selectedPhotons": cube.events
            + cube.overflow_events
            + cube.reflection_excluded_events,
            "exportedPhotons": cube.events,
            "excludedOutsideTimeWindow": cube.overflow_events,
            "excludedReflectionPhotons": cube.reflection_excluded_events,
            "policy": "exclude and count; never clip",
        },
        "mosaic": dataset.mosaic_metadata(linear_plane),
        "leicaNames": {
            "acquisition": dataset.acquisition_name,
            "series": dataset.series_name,
            "channel": dataset.channel_name,
            "timepoint": dataset.timepoint_name,
            "z": dataset.z_name,
            "detector": dataset.detector_name,
            "elementPath": list(dataset.element_path),
        },
        "eventSelection": dataset_selection_metadata(
            dataset, cube.event_flag_mask
        ),
        "outputFilename": Path(export["path"]).name,
        "dimensions": {
            "microtimeBins": export["bins"],
            "height": dataset.height,
            "width": dataset.width,
            "zCount": dataset.z_count,
            "tCount": dataset.t_count,
            "stagePositionCount": dataset.stage_count,
            "channelCountInSource": dataset.channel_count,
            "exportedChannelIndexZeroBased": dataset.channel_index,
            "dimensionOrder": list(dataset.dimension_order),
            "dimensionStatus": dataset.dimension_status,
        },
        "planeCoverage": dataset.plane_coverage_metadata,
        "plane": {
            "mode": dimension_mode,
            "linearIndexZeroBased": linear_plane,
            "tIndexZeroBased": t_index,
            "zIndexZeroBased": z_index,
            "firstEncodedRow": first_encoded_row,
            "encodedRowCount": encoded_row_count,
        },
        "integerBits": export["bits"],
        "byteOrder": export["byteOrder"],
        "axisOrder": export["axisOrder"],
        "compression": export["compression"],
        "cubeContract": {
            "logicalAxes": ["X", "Y", "photon_arrival_bin"],
            "shapeXYH": export["shapeXYH"],
            "oneDetectorPerFile": True,
            "tAndZStoredInFilenameAndMetadata": True,
        },
        "totalPhotonCount": (cube.events),
        "linkedIntensityPhotonCount": cube.reference_events,
        "eventStreamMinusIntensity": cube.event_difference,
        "spatialAlignment": {
            "transformApplied": cube.spatial_transform,
            "correlationWithLinkedIntensity": (
                cube.spatial_alignment_correlation
            ),
            "absolutePixelError": cube.spatial_alignment_absolute_error,
            "confirmed": cube.spatial_alignment_confirmed,
            "reference": "linked Leica intensity"
            if cube.spatial_alignment_correlation is not None
            else None,
        },
        "maximumPixelBinCount": export["maximumBinCount"],
        "calibration": calibration,
        "detectorDeadTimeSeconds": dataset.detector_dead_time_s,
        "interpretation": {
            "confirmed": confirmed,
            "inferredOrDefaulted": inferred,
            "unavailable": unavailable,
        },
        "decoder": {
            "backend": cube.backend,
            "threads": cube.thread_count,
            "native": native_decoder_info(),
        },
        "sourceStorage": {
            "format": dataset.storage_format,
            "frameRepetitionsPerPlane": dataset.frame_repetitions,
            "lineRepetitionsPerLine": dataset.line_repetitions,
            "repetitionStorageModel": dataset.repetition_storage_model,
            "frameRepetitionsSource": dataset.frame_repetitions_source,
            "lineRepetitionsSource": dataset.line_repetitions_source,
            "detectorIdentifier": dataset.detector_identifier,
            "channelColor": dataset.channel_color,
        },
        "application": {
            **application_metadata(),
            "icsCompatibility": (
                "ICS v2; native bin counts require downstream verification"
            ),
        },
        "ics": export,
    }


def _output_filename(
    dataset: DatasetInfo, base: str, linear_plane: int | None
) -> str:
    if linear_plane is not None:
        if dataset.plane_count == 1:
            return base + ".ics"
        return f"{base}_{dataset.plane_label(linear_plane)}.ics"
    if dataset.plane_count == 1:
        return base + ".ics"
    suffix = (
        "all-frames-summed"
        if dataset.t_count > 1 and dataset.z_count == 1
        else "all-z-summed"
        if dataset.z_count > 1 and dataset.t_count == 1
        else "all-planes-summed"
    )
    return f"{base}_{suffix}.ics"


@dataclass(frozen=True)
class _IcsPlaneJob:
    """An output plane and its validated decode and progress context."""

    dataset: DatasetInfo
    linear_plane: int | None
    base: str
    destination: Path
    options: IcsExportOptions
    cached: Mapping[str, HistogramCube]
    prepared: NativePreparedDecoder | RawPreparedDecoder | None
    report: BatchProgress
    completed: int
    total: int
    is_cancelled: CancelCheck


def _export_plane(job: _IcsPlaneJob) -> dict:
    filename = _output_filename(job.dataset, job.base, job.linear_plane)
    target = _collision_target(
        job.destination, filename, job.options.collision
    )
    if target is None:
        return {
            "dataset": job.dataset.display_name,
            "status": "skipped",
            "reason": "output exists",
            "path": str(job.destination / filename),
            "linearPlane": job.linear_plane,
        }
    try:
        grid = time_grid(job.dataset, job.options.bins)
        window = reflection_window(
            job.options.reflection_windows, job.dataset, job.linear_plane
        )
        decode_grid = time_grid(job.dataset, None) if window else grid
        cube = job.cached.get(job.dataset.key)
        if (
            cube is None
            or cube.source_dataset_key != job.dataset.key
            or cube.linear_plane != job.linear_plane
            or cube.reflection_excluded_events != 0
            or cube.event_flag_mask
            != normalize_selection(
                job.options.event_flag_mask, job.dataset.storage_format
            )
        ):
            cube = None
        if cube is not None:
            cube = rebin_cube(cube, decode_grid.bins, decode_grid)
        if cube is None:

            def report(message):
                job.report(message, job.completed, job.total)

            if job.linear_plane is None:
                cube = decode_histogram_cube(
                    job.dataset,
                    bins=decode_grid.bins,
                    grid=decode_grid,
                    threads=job.options.threads,
                    event_flag_mask=job.options.event_flag_mask,
                    progress=report,
                    cancelled=job.is_cancelled,
                )
            else:
                cube = decode_histogram_plane(
                    job.dataset,
                    job.linear_plane,
                    bins=decode_grid.bins,
                    grid=decode_grid,
                    threads=job.options.threads,
                    prepared=job.prepared,
                    event_flag_mask=job.options.event_flag_mask,
                    progress=report,
                    cancelled=job.is_cancelled,
                )
        if window is not None:
            cube = filter_native_cube(cube, grid, window, job.is_cancelled)
        metadata = acquisition_metadata(
            job.dataset, job.linear_plane, job.options.dimension_mode
        )
        metadata["eventSelection"] = dataset_selection_metadata(
            job.dataset, job.options.event_flag_mask
        )
        metadata["reflectionFilter"] = (
            window.metadata(job.dataset.clock_period_s)
            if window
            else {"enabled": False}
        )
        export = write_ics(
            target,
            cube.counts,
            job.dataset,
            compression=job.options.compression,
            grid=grid,
            metadata=metadata,
            cancelled=job.is_cancelled,
            progress=lambda done, count: job.report(
                f"Writing {target.name}: {done}/{count} decay planes",
                job.completed + done / count,
                job.total,
            ),
        )
        sidecar = _sidecar(
            job.dataset,
            cube,
            export,
            job.linear_plane,
            job.options.dimension_mode,
        )
        sidecar["reflectionFilter"] = (
            window.metadata(job.dataset.clock_period_s)
            if window
            else {"enabled": False}
        )
        reports = write_companions(target, sidecar)
        return {
            "dataset": job.dataset.display_name,
            "status": "exported",
            "path": str(target),
            "sidecar": str(target) + ".json",
            "metadataReports": reports,
            "events": cube.events,
            "bits": export["bits"],
            "bins": grid.bins,
            "excludedPhotons": cube.overflow_events,
            "excludedReflectionPhotons": cube.reflection_excluded_events,
            "timingQuality": "Recorded"
            if grid.mode == "native"
            else "Calculated",
            "linearPlane": job.linear_plane,
        }
    except Exception:
        cleanup_export(target)
        raise


@dataclass(frozen=True)
class _IcsBatch:
    """Shared immutable options and progress callbacks for a batch."""

    default_destination: Path
    destinations: Mapping[str, str | Path]
    names: Mapping[str, str]
    cached: Mapping[str, HistogramCube]
    report: BatchProgress
    is_cancelled: CancelCheck
    selections: dict[str, list[int | None]]
    total: int
    options: IcsExportOptions


def _export_ics_planes(
    dataset: DatasetInfo,
    batch: _IcsBatch,
    completed_outputs: int,
    destination: Path,
    base: str,
    plane_indices: list[int | None],
) -> tuple[list[dict], int]:
    """Own decoder preparation and close it after success, cancellation
    or failure.
    """
    results: list[dict] = []
    prepared = None
    try:
        if plane_indices[0] is not None:
            if dataset.storage_format == "lmsraw":
                prepared = RawPreparedDecoder(dataset)
            else:
                try:
                    prepared = NativePreparedDecoder(dataset)
                except NativeDecoderUnavailable:
                    prepared = None
        for linear_plane in plane_indices:
            if batch.is_cancelled():
                raise IcsExportCancelled("ICS batch export cancelled")
            result = None
            try:
                result = _export_plane(
                    _IcsPlaneJob(
                        dataset,
                        linear_plane,
                        base,
                        destination,
                        batch.options,
                        batch.cached,
                        prepared,
                        batch.report,
                        completed_outputs,
                        batch.total,
                        batch.is_cancelled,
                    )
                )
                results.append(result)
            except IcsExportCancelled:
                raise
            except DecodeCancelled as exc:
                raise IcsExportCancelled("ICS batch export cancelled") from exc
            # Convert unexpected worker failures into explicit
            # user-facing errors.
            # pylint: disable-next=broad-exception-caught
            except Exception as exc:
                results.append(
                    {
                        "dataset": dataset.display_name,
                        "status": "failed",
                        "linearPlane": linear_plane,
                        "error": str(exc),
                    }
                )
            completed_outputs += 1
            batch.report(
                f"Saved {Path(result['path']).name}"
                if result and result.get("status") == "exported"
                else f"Completed plane {completed_outputs}/{batch.total}",
                completed_outputs,
                batch.total,
            )
    except IcsExportCancelled:
        raise
    # Convert unexpected worker failures into explicit user-facing
    # errors.
    # pylint: disable-next=broad-exception-caught
    except Exception as exc:
        results.append(
            {
                "dataset": dataset.display_name,
                "status": "failed",
                "path": None,
                "error": str(exc),
            }
        )
        batch.report(
            f"Failed {dataset.display_name}: {exc}",
            completed_outputs,
            batch.total,
        )
    finally:
        if prepared is not None:
            prepared.close()
    return (results, completed_outputs)


def _export_ics_dataset(
    dataset: DatasetInfo, batch: _IcsBatch, completed_outputs: int
) -> tuple[list[dict], int]:
    """Export one dataset, recording explicit per-plane and setup
    failures.
    """
    results: list[dict] = []
    if batch.is_cancelled():
        raise IcsExportCancelled("ICS batch export cancelled")
    destination = (
        Path(batch.destinations.get(dataset.key, batch.default_destination))
        .expanduser()
        .resolve()
    )
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        for linear_plane in batch.selections[dataset.key]:
            results.append(
                {
                    "dataset": dataset.display_name,
                    "status": "failed",
                    "linearPlane": linear_plane,
                    "error": (
                        f"Cannot create output folder {destination}: {exc}"
                    ),
                }
            )
        completed_outputs += len(batch.selections[dataset.key])
        batch.report(
            f"Could not create {destination}", completed_outputs, batch.total
        )
        return (results, completed_outputs)
    batch.report(
        f"Preparing {dataset.display_name}", completed_outputs, batch.total
    )
    requested_name = (
        batch.names.get(dataset.key)
        or proposed_ics_filenames([dataset])[dataset.key]
    )
    base = sanitize_ics_basename(Path(requested_name).stem)
    suffix = filename_suffix(batch.options.event_flag_mask)
    if suffix and (not base.endswith(suffix)):
        base += suffix
    if dataset.decoded_rows <= 0:
        results.append(
            {
                "dataset": dataset.display_name,
                "status": "failed",
                "error": "Leica block contains no encoded FLIM rows",
            }
        )
        completed_outputs += len(batch.selections[dataset.key])
        return (results, completed_outputs)
    failure = (
        dataset.dimension_status
        if dataset.repetition_storage_model == "unresolved"
        else MOSAIC_INTEGRATION_ERROR
        if dataset.mosaic is not None
        and dataset.tile_index is None
        and batch.options.dimension_mode != "split"
        else None
    )
    if failure is not None:
        results.append(
            {
                "dataset": dataset.display_name,
                "status": "failed",
                "error": failure,
            }
        )
        completed_outputs += len(batch.selections[dataset.key])
        return (results, completed_outputs)
    if (
        batch.options.dimension_mode == "split"
        and dataset.plane_count > 1
        and not dataset.dimension_status.startswith(
            ("confirmed", "partial indexed acquisition:")
        )
    ):
        results.append(
            {
                "dataset": dataset.display_name,
                "status": "failed",
                "error": dataset.dimension_status,
            }
        )
        completed_outputs += len(batch.selections[dataset.key])
        return (results, completed_outputs)
    plane_indices = batch.selections[dataset.key]
    if not plane_indices:
        return (results, completed_outputs)
    return _export_ics_planes(
        dataset, batch, completed_outputs, destination, base, plane_indices
    )


# Retain the accepted batch callback and output-selection interface.
# pylint: disable-next=too-many-arguments
def export_ics_blocks(
    datasets: Iterable[DatasetInfo],
    output_dir: str | Path,
    options: IcsExportOptions = _DEFAULT_OPTIONS,
    *,
    cached_cubes: Mapping[str, HistogramCube] | None = None,
    filenames: Mapping[str, str] | None = None,
    plane_selection: Mapping[str, Iterable[int]] | None = None,
    output_directories: Mapping[str, str | Path] | None = None,
    progress: BatchProgress | None = None,
    cancelled: CancelCheck | None = None,
) -> list[dict]:
    """Decode and export only the selected blocks, continuing after
    failures.
    """
    options.validate()
    selected = list(datasets)
    default_destination = Path(output_dir).expanduser().resolve()
    destinations = output_directories or {}
    names = dict(filenames or proposed_ics_filenames(selected))
    cached = cached_cubes or {}
    report = progress or (lambda _message, _current, _total: None)
    is_cancelled = cancelled or (lambda: False)
    results: list[dict] = []

    def requested_planes(dataset: DatasetInfo) -> list[int | None]:
        """Compute requested planes."""
        if options.dimension_mode != "split":
            return [None]
        if (
            plane_selection is None or dataset.key not in plane_selection
        ) and dataset.plane_count == 1:
            return [None]
        values = (
            list(plane_selection[dataset.key])
            if plane_selection is not None and dataset.key in plane_selection
            else list(range(dataset.plane_count))
        )
        unique = sorted(set((value) for value in values))
        if any(value < 0 or value >= dataset.plane_count for value in unique):
            raise ValueError(
                f"Plane selection is outside {dataset.display_name}"
            )
        return list[int | None](unique)

    selections = {
        dataset.key: requested_planes(dataset) for dataset in selected
    }
    total = sum(len(selections[dataset.key]) for dataset in selected)
    completed_outputs = 0
    batch = _IcsBatch(
        default_destination,
        destinations,
        names,
        cached,
        report,
        is_cancelled,
        selections,
        total,
        options,
    )
    for dataset in selected:
        outputs, completed_outputs = _export_ics_dataset(
            dataset, batch, completed_outputs
        )
        results.extend(outputs)
    return results
