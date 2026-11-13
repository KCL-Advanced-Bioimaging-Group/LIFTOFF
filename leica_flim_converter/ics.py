"""ICS v2 time-stack writer with calibrated spatial and micro-time
axes.
"""

from __future__ import annotations

import gzip
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

import patent_guided_deflate_attack as codec

from .acquisition_metadata import acquisition_metadata, ics_history
from .dataset import DatasetInfo
from .decay import ALL
from .header_metadata import ics_standard_header
from .optical_metadata import wavelength_label
from .spatial_metadata import spatial_calibration
from .timing import TimeGrid, time_grid
from .version import APPLICATION_NAME

ALLOWED_BINS = (32, 64, 128, 256, 512, 1024, 2048, 4096)
CancelCheck = Callable[[], bool]
Progress = Callable[[int, int], None]


class IcsExportCancelledError(RuntimeError):
    """Represent ics export cancelled error."""


def sanitize_ics_basename(value: str) -> str:
    """Preserve Leica naming while replacing Windows-invalid
    characters.
    """
    cleaned = re.sub('[<>:"/\\\\|?*\\x00-\\x1f]', "_", value).rstrip(" .")
    return cleaned or "Leica_FLIM"


def _sequence_name_part(dataset: DatasetInfo) -> str | None:
    if dataset.sequence_count <= 1:
        return None
    wavelengths = "-".join(
        f"{wavelength_label(wave)}nm"
        for wave in dataset.excitation_wavelengths_nm
    )
    return (
        f"seq{dataset.sequence_index + 1:02d}_Ex_"
        f"{wavelengths or 'unavailable'}"
    )


def leica_name_parts(dataset: DatasetInfo) -> tuple[str, ...]:
    """Compute leica name parts."""
    values = (
        dataset.acquisition_name,
        _sequence_name_part(dataset),
        dataset.timepoint_name,
        dataset.channel_name,
        dataset.series_name,
        dataset.z_name,
        dataset.detector_name,
    )
    return tuple(value.strip() for value in values if value and value.strip())


def proposed_ics_basename(dataset: DatasetInfo) -> str:
    """Compute proposed ics basename."""
    parts = leica_name_parts(dataset)
    if dataset.storage_format == "lmsraw":
        raw_parts = (
            dataset.acquisition_name,
            _sequence_name_part(dataset),
            dataset.channel_name,
            dataset.detector_name,
        )
        return sanitize_ics_basename(
            "_".join(
                value.strip() for value in raw_parts if value and value.strip()
            )
        )
    return sanitize_ics_basename(parts[0] if parts else dataset.source.stem)


def proposed_ics_filenames(datasets: Iterable[DatasetInfo]) -> dict[str, str]:
    """Generate unique deterministic names without touching the
    destination.
    """
    items = list(datasets)
    bases = [proposed_ics_basename(dataset) for dataset in items]
    frequencies: dict[str, int] = {}
    for base in bases:
        frequencies[base.casefold()] = frequencies.get(base.casefold(), 0) + 1
    result: dict[str, str] = {}
    used: set[str] = set()
    for dataset, base in zip(items, bases, strict=False):
        candidate = base
        if frequencies[base.casefold()] > 1:
            candidate = sanitize_ics_basename(
                "_".join(leica_name_parts(dataset)) or base
            )
        if candidate.casefold() in used:
            candidate = sanitize_ics_basename(
                f"{candidate}_{dataset.memory_id}"
            )
        suffix, unique = (2, candidate)
        while unique.casefold() in used:
            unique = f"{candidate}_{suffix}"
            suffix += 1
        used.add(unique.casefold())
        result[dataset.key] = unique + ".ics"
    return result


def build_decay_stack(
    rows: list[dict],
    dataset: DatasetInfo,
    bins: int = 128,
    classes: set[int] = ALL,
) -> tuple[np.ndarray, dict]:
    """Compute build decay stack."""
    if bins not in ALLOWED_BINS:
        raise ValueError(f"ICS bins must be one of {ALLOWED_BINS}")
    stack = np.zeros((bins, dataset.height, dataset.width), dtype=np.uint32)
    grid = time_grid(dataset, bins)
    events = overflow = 0
    for line, x, dt, _marker in codec.iter_event_tuples(rows, classes):
        destination = int(grid.indices(np.array([dt]))[0])
        if not 0 <= destination < grid.bins:
            overflow += 1
            continue
        stack[destination, dataset.encoded_row_to_y(line), x] += 1
        events += 1
    return (
        stack,
        {
            "events": events,
            "nativePeriodBins": int(np.ceil(grid.extent_s / grid.clock_s)),
            "timing": grid.metadata(),
            "eventsAtOrBeyondNativePeriod": overflow,
        },
    )


def write_ics(
    path: str | Path,
    stack: np.ndarray,
    dataset: DatasetInfo,
    compression: str = "gzip",
    *,
    cancelled: CancelCheck | None = None,
    progress: Progress | None = None,
    grid: TimeGrid | None = None,
    metadata: dict | None = None,
) -> dict:
    """Compute write ics."""
    target = Path(path)
    if compression not in ("gzip", "uncompressed"):
        raise ValueError("ICS compression must be gzip or uncompressed")
    if stack.ndim != 3:
        raise ValueError("ICS output must be one X/Y/photon-histogram cube")
    bins, height, width = map(int, stack.shape)
    if height != dataset.height or width != dataset.width:
        raise ValueError(
            "ICS cube X/Y dimensions do not match the selected Leica dataset"
        )
    maximum = int(stack.max())
    if maximum > np.iinfo(np.uint32).max or int(stack.min()) < 0:
        raise OverflowError(
            "ICS histogram counts must fit an unsigned 32-bit integer"
        )
    bits = 16 if maximum <= np.iinfo(np.uint16).max else 32
    dtype = np.dtype("<u2" if bits == 16 else "<u4")
    byte_order = "\t".join(str(index) for index in range(1, bits // 8 + 1))
    axes = spatial_calibration(dataset)["axes"]
    pixel_x, pixel_y = axes["x"]["scale"], axes["y"]["scale"]
    grid = grid or time_grid(dataset, bins)
    if grid.bins != bins:
        raise ValueError("ICS timing grid does not match the cube")
    metadata = (
        dict(metadata)
        if metadata is not None
        else acquisition_metadata(dataset, dimension_mode="unspecified")
    )
    metadata["histogramTiming"] = grid.metadata()
    header = (
        "\t\nics_version\t2.0\nfilename\t"
        f"{target.stem}"
        "\nlayout\tparameters\t4\nlayout\torder\tbits\ty\tx\tt"
        "\nlayout\tsizes\t"
        f"{bits}"
        "\t"
        f"{height}"
        "\t"
        f"{width}"
        "\t"
        f"{bins}"
        "\nlayout\tcoordinates\tvideo\nlayout\tsignificant_bits\t"
        f"{bits}"
        "\nrepresentation\tformat\tinteger\nrepresentation\tsign\tunsigned\n"
        "representation\tcompression\t"
        f"{compression}"
        "\nrepresentation\tbyte_order\t"
        f"{byte_order}"
        "\nparameter\torigin\t0.000000\t0.000000\t0.000000\t0.000000\n"
        "parameter\tscale\t1.000000\t"
        f"{pixel_y:.17g}"
        "\t"
        f"{pixel_x:.17g}"
        "\t"
        f"{grid.step_s:.17g}"
        f"\nparameter\tunits\trelative\t{axes['y']['unit']}"
        f"\t{axes['x']['unit']}\ts"
        "\nparameter\tlabels\tintensity\t"
        "y-position\tx-position\tmicro-time\nhistory\tsoftware\t"
        f"{APPLICATION_NAME}\n\nhistory\ttype\tTime Resolved"
        "\nhistory\tlabels\tx y t"
        "\nhistory\textents\t"
        f"{width * pixel_x:.17g}"
        " "
        f"{height * pixel_y:.17g}"
        " "
        f"{grid.extent_s:.17g}"
        f"\nhistory\tunits\t{axes['x']['unit']} {axes['y']['unit']} s"
        "\nhistory\tdimensions\t"
        f"{width}"
        " "
        f"{height}"
        " "
        f"{bins}"
        "\n"
        + ics_standard_header(metadata)
        + ics_history(metadata)
        + "end\t\n"
    ).encode("ascii")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    try:
        with temporary.open("wb") as raw:
            raw.write(header)
            output = (
                gzip.GzipFile(
                    filename="",
                    fileobj=raw,
                    mode="wb",
                    compresslevel=6,
                    mtime=0,
                )
                if compression == "gzip"
                else raw
            )
            try:
                for index, plane in enumerate(stack):
                    if cancelled and cancelled():
                        raise IcsExportCancelled("ICS export cancelled")
                    output.write(
                        np.ascontiguousarray(plane.T, dtype=dtype).tobytes()
                    )
                    if progress:
                        progress(index + 1, bins)
            finally:
                if output is not raw:
                    output.close()
        if cancelled and cancelled():
            raise IcsExportCancelled("ICS export cancelled")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "format": "ICS v2",
        "path": str(target),
        "bins": bins,
        "bits": bits,
        "compression": compression,
        "shapeZYX": [bins, height, width],
        "shapeXYH": [width, height, bins],
        "maximumBinCount": maximum,
        "timeStepSeconds": grid.step_s,
        "payloadBytesUncompressed": bins * height * width * (bits // 8),
        "axisOrder": ["x", "y", "photon_arrival_bin"],
        "internalArrayAxisOrder": ["photon_arrival_bin", "y", "x"],
        "byteOrder": "little-endian",
        "filename": target.stem,
        "acquisitionMetadata": metadata,
    }


IcsExportCancelled = IcsExportCancelledError
