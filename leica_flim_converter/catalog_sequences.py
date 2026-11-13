"""Validate sequence-local row ranges independently of T/Z identity."""

from __future__ import annotations

import mmap
import struct
import xml.etree.ElementTree as ET
from dataclasses import replace

import lif_flim_forensics as lif

from .catalog_detectors import (
    positive_number,
    raw_sequence_root,
    sequence_indices,
)
from .catalog_timing import read_timing
from .dataset import DatasetInfo
from .spatial_metadata import voxel_calibration


def _frame_ranges(
    data: mmap.mmap, block: lif.MemoryBlock | None, count: int, rows: int
) -> tuple[tuple[int, int], ...]:
    if block is None or block.declared_size < 16 + count * 8:
        raise ValueError("Missing or truncated sequence FrameOffsets table")
    version, found = struct.unpack_from("<2Q", data, block.data_start)
    if version != 1 or found != count:
        raise ValueError(
            f"Sequence frame index: expected {count} entries, found {found}"
        )
    ends = struct.unpack_from(f"<{count}Q", data, block.data_start + 16)
    starts = (0,) + ends[:-1]
    if ends[-1] != rows or any(
        end <= start for start, end in zip(starts, ends, strict=True)
    ):
        raise ValueError(
            "Invalid or non-monotonic sequence FrameOffsets table"
        )
    return tuple(
        (start, end - start) for start, end in zip(starts, ends, strict=True)
    )


def _sequence_slots(
    dataset: DatasetInfo, order: tuple[str, ...], mode: str, ordinal: int
) -> tuple[int, ...]:
    if mode not in ("SequentialFrame", "SequentialStack"):
        raise ValueError(f"Unsupported sequence storage order: {mode}")
    axes = [
        "Q" if axis == "C" else axis
        for axis in order
        if axis in ("C", "T", "Z", "S")
    ]
    if "Q" not in axes:
        axes = ["Q"] + [
            axis for axis in dataset.dimension_order if axis in ("T", "Z", "S")
        ]
        if mode == "SequentialStack" and "Z" in axes:
            axes.remove("Q")
            axes.insert(axes.index("Z") + 1, "Q")
    if len(set(axes)) != len(axes) or any(
        count > 1 and axis not in axes
        for axis, count in (
            ("T", dataset.t_count),
            ("Z", dataset.z_count),
            ("S", dataset.stage_count),
        )
    ):
        raise ValueError("Incomplete or duplicate sequence dimension order")
    if dataset.z_count > 1:
        stack_order = axes.index("Q") > axes.index("Z")
        if stack_order != (mode == "SequentialStack"):
            raise ValueError("Sequence mode conflicts with declared Z/C order")
    strides = {}
    stride = 1
    sizes = {
        "Q": dataset.sequence_count,
        "T": dataset.t_count,
        "Z": dataset.z_count,
        "S": dataset.stage_count,
    }
    for axis in axes:
        strides[axis] = stride
        stride *= sizes[axis]
    return tuple(
        ordinal * strides["Q"]
        + t * strides.get("T", 0)
        + z * strides.get("Z", 0)
        + stage * strides.get("S", 0)
        for stage, (t, z) in (
            (dataset.plane_stage_index(plane), dataset.plane_indices(plane))
            for plane in range(dataset.plane_count)
        )
    )


def _row_model(
    dataset: DatasetInfo, ranges: tuple[tuple[int, int], ...]
) -> tuple[str, str]:
    base = dataset.height * dataset.frame_repetitions
    explicit = base * dataset.line_repetitions
    lengths = [length for _first, length in ranges]
    if all(length == explicit for length in lengths):
        return (
            "explicit-line-repeat-rows"
            if dataset.line_repetitions > 1
            else "frame-repeat-rows"
        ), "confirmed"
    if all(length == base for length in lengths):
        return (
            "in-row-line-accumulation"
            if dataset.line_repetitions > 1
            else "frame-repeat-rows"
        ), "confirmed"
    if (
        dataset.line_repetitions > 1
        and any(length > base for length in lengths)
        and all(length <= explicit for length in lengths)
    ):
        return "explicit-line-repeat-rows", "partial indexed sequence"
    if dataset.line_repetitions == 1 and all(
        length <= base for length in lengths
    ):
        return "frame-repeat-rows", "partial indexed sequence"
    raise ValueError(
        f"Sequence {dataset.sequence_index + 1} row-count mismatch: "
        f"{lengths}; "
        f"expected {explicit} or {base} rows per T/Z plane"
    )


def _voxel_sources(*scopes: ET.Element) -> tuple[dict, ...]:
    sources = []
    for axis in ("x", "y", "z"):
        tag = f"VoxelSize{axis.upper()}"
        source = voxel_calibration(axis, None, "RawData")
        for scope, name in zip(
            scopes, ("Detector", "SequenceItem", "RawData"), strict=True
        ):
            if (text := scope.findtext(tag)) is not None:
                source = voxel_calibration(axis, text, name)
                break
        sources.append(source)
    return tuple(sources)


def attach_detector_metadata(
    dataset: DatasetInfo, context: str
) -> DatasetInfo:
    """Bind detector calibration independently of storage grammar."""
    raw = raw_sequence_root(context)
    if raw is None:
        return dataset
    sequences = raw.findall("Sequence/SequenceItem")
    if not 0 <= dataset.sequence_index < len(sequences):
        timing = read_timing(
            raw, ET.Element("SequenceItem"), ET.Element("Detectors"), context
        )
        return replace(dataset, acquisition_timing=timing)
    sequence = sequences[dataset.sequence_index]
    detector = next(
        (
            item
            for item in sequence.findall("Detectors/Detectors")
            if item.findtext("Detector") == str(dataset.detector_route)
        ),
        None,
    )
    if detector is None:
        return replace(
            dataset,
            acquisition_timing=read_timing(
                raw, sequence, ET.Element("Detectors"), context
            ),
            repetition_storage_model="unresolved",
            dimension_status="Sequence detector route is unavailable",
        )
    timing = read_timing(raw, sequence, detector, context)
    scoped = replace(
        dataset,
        acquisition_timing=timing,
        clock_period_s=timing.clock.value,
        laser_frequency_hz=timing.laser_frequency.value,
        detector_dead_time_s=positive_number(detector.findtext("DeadTime")),
        detector_data_type=detector.findtext("DataType"),
    )
    if dataset.sequence_count <= 1:
        return scoped
    spatial = (
        _voxel_sources(detector, sequence, raw)
        if dataset.storage_format == "lmsraw"
        else dataset.spatial_sources
    )
    return replace(
        scoped,
        line_repetitions=max(
            1, int(sequence.findtext("LineRepetitions", "1"))
        ),
        frame_repetitions=max(
            1, int(sequence.findtext("FrameRepetitions", "1"))
        ),
        pixel_size_x_m=(
            spatial[0]["spacingMetres"]
            if dataset.storage_format == "lmsraw"
            else dataset.pixel_size_x_m
        ),
        pixel_size_y_m=(
            spatial[1]["spacingMetres"]
            if dataset.storage_format == "lmsraw"
            else dataset.pixel_size_y_m
        ),
        spatial_sources=spatial,
    )


def attach_sequence_layout(
    dataset: DatasetInfo,
    context: str,
    order: tuple[str, ...],
    data: mmap.mmap,
    frames: lif.MemoryBlock | None,
) -> DatasetInfo:
    """Bind calibration and indexed LMSRAW intervals to a detector."""
    scoped = attach_detector_metadata(dataset, context)
    raw = raw_sequence_root(context)
    if (
        raw is None
        or dataset.sequence_count <= 1
        or scoped.dimension_status == "Sequence detector route is unavailable"
    ):
        return scoped
    try:
        indexed = _frame_ranges(
            data,
            frames,
            dataset.sequence_count * dataset.plane_count,
            dataset.decoded_rows,
        )
        slots = _sequence_slots(
            scoped,
            order,
            raw.findtext("SequentialMode", ""),
            sequence_indices(context).index(dataset.sequence_index),
        )
        ranges = tuple(indexed[slot] for slot in slots)
        model, status = _row_model(scoped, ranges)
        return replace(
            scoped,
            plane_row_ranges=ranges,
            plane_row_starts=tuple(first for first, _length in ranges),
            repetition_storage_model=model,
            dimension_status=status,
        )
    except (ValueError, IndexError) as exc:
        return replace(
            scoped,
            repetition_storage_model="unresolved",
            dimension_status=str(exc),
        )
