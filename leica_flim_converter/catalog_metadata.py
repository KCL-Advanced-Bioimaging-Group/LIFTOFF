"""Typed acquisition, layout and detector metadata construction."""

from __future__ import annotations

import mmap
import re
import struct
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image

import lif_flim_forensics as lif

from .catalog_detectors import acquisition_context
from .catalog_detectors import raw_channels as _raw_channels
from .catalog_mosaic import attach_mosaic
from .catalog_sequences import attach_detector_metadata, attach_sequence_layout
from .compressed_index import compressed_index_error
from .data_types import RawChannel
from .dataset import DatasetInfo
from .intensity_preview import (
    float16_preview,
    float32_preview,
    is_float16_preview,
)
from .linked_intensity import scope_intensity
from .partial_compressed import attach_recorded_prefix
from .spatial_metadata import dimension_calibration, voxel_calibration


def _last_text(pattern: str, context: str) -> str | None:
    values = re.findall(pattern, context, flags=re.IGNORECASE)
    return values[-1].strip() if values and values[-1].strip() else None


def _index_label(prefix: str, value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return f"{prefix}{int(float(value)) + 1}"
    except ValueError:
        return value


def _encoded_container_bytes(
    header: tuple[int, ...], declared_size: int
) -> int:
    stream_start, stream_size, table_size = map(int, header[1:4])
    encoded = stream_start + stream_size + table_size
    return (
        encoded
        if 64 <= stream_start <= encoded <= declared_size
        else declared_size
    )


def _resolve_repetition_model(
    decoded_rows: int,
    height: int,
    plane_count: int,
    line_repetitions: int,
    frame_repetitions: int,
) -> tuple[str, int, str]:
    in_row_expected = height * plane_count * frame_repetitions
    explicit_expected = in_row_expected * line_repetitions
    if line_repetitions > 1 and decoded_rows == explicit_expected:
        return (
            "explicit-line-repeat-rows",
            explicit_expected,
            "confirmed (line order inferred)",
        )
    if decoded_rows == in_row_expected:
        model = (
            "in-row-line-accumulation"
            if line_repetitions > 1
            else "frame-repeat-rows"
        )
        return (model, in_row_expected, "confirmed")
    return (
        "unresolved",
        explicit_expected,
        (
            "row-count mismatch: found "
            f"{decoded_rows}"
            "; expected "
            f"{explicit_expected}"
            " with explicit line repeats or "
            f"{in_row_expected}"
            " with in-row accumulation"
        ),
    )


def _preview(image: np.ndarray, size: int = 180) -> Image.Image:
    values = image.astype(np.float64)
    nonzero = values[values > 0]
    if nonzero.size:
        low, high = np.percentile(nonzero, (1, 99.8))
    else:
        low, high = (0.0, 1.0)
    scaled = np.clip(
        (values - low) * 255.0 / max(1e-12, high - low), 0, 255
    ).astype(np.uint8)
    result = Image.fromarray(scaled, mode="L")
    result.thumbnail((size, size), Image.Resampling.LANCZOS)
    return result


def _element_context(xml: str, memory_id: str) -> str:
    """Return the direct element body ending at a memory declaration."""
    memory_index = xml.find(f'MemoryBlockID="{memory_id}"')
    if memory_index < 0:
        return ""
    start = xml.rfind("<Element ", 0, memory_index)
    return xml[start:memory_index] if start >= 0 else ""


def _raw_dimensions(context: str) -> tuple[dict[str, int], tuple[str, ...]]:
    raw_end = context.find("</RawData>")
    raw = context[:raw_end] if raw_end >= 0 else context
    values: dict[str, int] = {}
    order = []
    for match in re.finditer(
        (
            "<Dimension><DimensionIdentifier>([^<]+)</DimensionIdentif"
            "ier><Size>(\\d+)</Size></Dimension>"
        ),
        raw,
    ):
        axis, size = (match.group(1), int(match.group(2)))
        values[axis] = size
        if size > 1:
            order.append(axis)
    return (values, tuple(order))


def _parse_offset_table(
    data: mmap.mmap, block: lif.MemoryBlock | None, payload_size: int
) -> tuple[int, tuple[int, ...]]:
    if block is None or block.declared_size < 40:
        return (0, ())
    version, count, described_size, _a, _b = struct.unpack_from(
        "<5Q", data, block.data_start
    )
    if version != 1 or count <= 0 or described_size != payload_size:
        return (0, ())
    return (int(count), ())


def _parse_frame_row_starts(
    data: mmap.mmap,
    block: lif.MemoryBlock | None,
    plane_count: int,
    decoded_rows: int,
) -> tuple[int, ...]:
    if block is None or block.declared_size < 16 + plane_count * 8:
        return ()
    version, count = struct.unpack_from("<2Q", data, block.data_start)
    if version != 1 or count != plane_count:
        return ()
    ends = struct.unpack_from(f"<{plane_count}Q", data, block.data_start + 16)
    if not ends or ends[-1] != decoded_rows:
        return ()
    return (0,) + tuple(int(value) for value in ends[:-1])


@dataclass(frozen=True)
class _CatalogueIndex:
    """Mapped block groups and shared sparse indexing callbacks."""

    source: Path
    data: mmap.mmap
    xml: str
    element_paths: dict[str, tuple[str, ...]]
    intensities: list[lif.MemoryBlock]
    line_offset_blocks: list[lif.MemoryBlock]
    frame_offset_blocks: list[lif.MemoryBlock]


@dataclass(frozen=True)
class _BlockTiming:
    """Timing and acquisition metadata recovered from the XML
    context.
    """

    element_context: str
    timing_context: str
    storage_format: str
    clock_period: float | None
    laser_frequency: float | None
    metadata: dict
    path_names: tuple[str, ...]
    acquisition: str
    series: str | None
    time_index: str | None
    z_index: str | None


@dataclass
class _DimensionInfo:
    """Spatial calibration and Leica's native T/Z dimension order."""

    dimensions_by_id: dict[int, dict] = field(default_factory=dict)
    raw_dimension_values: dict[str, int] = field(default_factory=dict)
    raw_order: tuple[str, ...] = ()
    width: int = 512
    height: int = 512
    z_count: int = 1
    t_count: int = 1
    stage_count: int = 1
    pixel_x: float | None = None
    pixel_y: float | None = None
    spatial_sources: tuple[dict, ...] = ()
    z_stride: int = 0
    t_stride: int = 0
    stage_stride: int = 0
    dimension_order: tuple[str, ...] = ()

    @property
    def plane_count(self) -> int:
        """Count independent T/Z/stage planes."""
        return self.z_count * self.t_count * self.stage_count


@dataclass
class _BlockLayout:
    """Validated line indexes, repetitions and linked detector
    metadata.
    """

    intensity: lif.MemoryBlock | None = None
    frame_text: str | None = None
    line_text: str | None = None
    frame_repetitions: int = 1
    line_repetitions: int = 1
    line_offsets: lif.MemoryBlock | None = None
    frame_offsets: lif.MemoryBlock | None = None
    plane_row_starts: tuple[int, ...] = ()
    decoded_rows: int = 0
    encoded_bytes: int = 0
    repetition_model: str = "unresolved"
    dimension_status: str = "empty"
    frame_count: int = 0
    default_channel: str | None = None
    default_detector: str | None = None
    raw_channels: list[RawChannel] = field(default_factory=list)
    channel_count: int = 1
    intensity_channels: list[dict] = field(default_factory=list)
    intensity_context: str = ""
    plane_bytes: int = 0


def _block_timing(
    index: _CatalogueIndex, block: lif.MemoryBlock
) -> _BlockTiming:
    """Read the direct raw context or preceding compressed timing
    context.
    """
    memory_index = index.xml.find(f'MemoryBlockID="{block.memory_id}"')
    timing_context = index.xml[max(0, memory_index - 250000) : memory_index]
    element_context = _element_context(index.xml, block.memory_id)
    storage_format = (
        "lmsraw"
        if "<Format>LMSRAW</Format>" in element_context
        else "compressed"
    )
    timing_source = (
        element_context if storage_format == "lmsraw" else timing_context
    )
    clock_values = re.findall(
        "<ClockPeriod>([^<]+)</ClockPeriod>", timing_source
    )
    laser_values = re.findall(
        "<LaserPulseFrequency>([^<]+)</LaserPulseFrequency>", timing_source
    )
    clock_period = float(clock_values[-1]) if clock_values else None
    laser_frequency = float(laser_values[-1]) if laser_values else None
    metadata = lif.block_metadata(index.xml, block.memory_id)
    path_names = index.element_paths.get(block.memory_id, ())
    meaningful_path = tuple(
        name
        for name in path_names
        if name not in ("Project", "FLIM Compressed", "FLIM")
    )
    acquisition = meaningful_path[-1] if meaningful_path else index.source.stem
    series = meaningful_path[-2] if len(meaningful_path) > 1 else None
    time_index = _last_text("<TimeIndex>([^<]+)</TimeIndex>", timing_context)
    z_index = _last_text("<ZIndex>([^<]+)</ZIndex>", timing_context)
    return _BlockTiming(
        element_context,
        timing_context,
        storage_format,
        clock_period,
        laser_frequency,
        metadata,
        path_names,
        acquisition,
        series,
        time_index,
        z_index,
    )


def _block_dimensions(timing: _BlockTiming) -> _DimensionInfo:
    """Preserve spatial calibration, dimension records and plane
    strides.
    """
    dimensions = _DimensionInfo()
    dimensions.dimensions_by_id = {}
    dimensions.raw_dimension_values = {}
    dimensions.raw_order = ()
    if timing.storage_format == "lmsraw":
        dimensions.raw_dimension_values, dimensions.raw_order = (
            _raw_dimensions(timing.element_context)
        )
        dimensions.width = dimensions.raw_dimension_values.get("X", 512)
        dimensions.height = dimensions.raw_dimension_values.get("Y", 512)
        dimensions.z_count = max(
            1, dimensions.raw_dimension_values.get("Z", 1)
        )
        dimensions.t_count = max(
            1, dimensions.raw_dimension_values.get("T", 1)
        )
        dimensions.stage_count = max(
            1, dimensions.raw_dimension_values.get("S", 1)
        )
        dimensions.spatial_sources = tuple(
            voxel_calibration(
                axis,
                _last_text(
                    f"<VoxelSize{axis.upper()}>([^<]+)"
                    f"</VoxelSize{axis.upper()}>",
                    timing.element_context,
                ),
                "RawData",
            )
            for axis in ("x", "y", "z")
        )
        dimensions.pixel_x = dimensions.spatial_sources[0]["spacingMetres"]
        dimensions.pixel_y = dimensions.spatial_sources[1]["spacingMetres"]
        axis_stride = 1
        dimensions.z_stride = dimensions.t_stride = 0
        for axis in dimensions.raw_order:
            if axis == "Z":
                dimensions.z_stride = axis_stride
                axis_stride *= dimensions.z_count
            elif axis == "T":
                dimensions.t_stride = axis_stride
                axis_stride *= dimensions.t_count
            elif axis == "S":
                dimensions.stage_stride = axis_stride
                axis_stride *= dimensions.stage_count
        dimensions.dimension_order = tuple(
            axis
            for axis in dimensions.raw_order
            if axis in ("X", "Y", "Z", "T", "S")
        )
    else:
        dims = timing.metadata.get("dimensions") or []
        for dimension in dims:
            try:
                dimensions.dimensions_by_id.setdefault(
                    int(dimension.get("DimID", 0)), dimension
                )
            except ValueError:
                continue
        x_dimension = dimensions.dimensions_by_id.get(1, {})
        y_dimension = dimensions.dimensions_by_id.get(2, {})
        dimensions.width = int(x_dimension.get("NumberOfElements", 512))
        dimensions.height = int(y_dimension.get("NumberOfElements", 512))
        dimensions.spatial_sources = tuple(
            dimension_calibration(
                axis, dimensions.dimensions_by_id.get(identifier, {})
            )
            for axis, identifier in (("x", 1), ("y", 2), ("z", 3))
        )
        dimensions.pixel_x = dimensions.spatial_sources[0]["spacingMetres"]
        dimensions.pixel_y = dimensions.spatial_sources[1]["spacingMetres"]
        z_dimension = dimensions.dimensions_by_id.get(3, {})
        t_dimension = dimensions.dimensions_by_id.get(4, {})
        stage_dimension = dimensions.dimensions_by_id.get(10, {})
        dimensions.stage_count = max(
            1, int(stage_dimension.get("NumberOfElements", 1))
        )
        dimensions.z_count = max(
            1, int(z_dimension.get("NumberOfElements", 1))
        )
        dimensions.t_count = max(
            1, int(t_dimension.get("NumberOfElements", 1))
        )
        image_plane_bytes = dimensions.width * dimensions.height * 4
        dimensions.z_stride = (
            int(z_dimension.get("BytesInc", 0)) // image_plane_bytes
            if dimensions.z_count > 1 and image_plane_bytes
            else 0
        )
        dimensions.t_stride = (
            int(t_dimension.get("BytesInc", 0)) // image_plane_bytes
            if dimensions.t_count > 1 and image_plane_bytes
            else 0
        )
        dimensions.stage_stride = (
            int(stage_dimension.get("BytesInc", 0)) // image_plane_bytes
            if dimensions.stage_count > 1 and image_plane_bytes
            else 0
        )
        varying = [
            (stride, axis)
            for stride, axis, count in (
                (dimensions.z_stride, "Z", dimensions.z_count),
                (dimensions.t_stride, "T", dimensions.t_count),
                (dimensions.stage_stride, "S", dimensions.stage_count),
            )
            if count > 1
        ]
        dimensions.dimension_order = ("X", "Y") + tuple(
            (axis for _stride, axis in sorted(varying))
        )
        # Byte strides include interleaved detector channels; logical
        # plane strides enumerate only T/Z/stage coordinates.
        logical_stride = 1
        for _byte_stride, axis in sorted(varying):
            if axis == "Z":
                dimensions.z_stride = logical_stride
                logical_stride *= dimensions.z_count
            elif axis == "T":
                dimensions.t_stride = logical_stride
                logical_stride *= dimensions.t_count
            else:
                dimensions.stage_stride = logical_stride
                logical_stride *= dimensions.stage_count
    return dimensions


def _following_block(
    candidates: list[lif.MemoryBlock], start: int, stop: int
) -> lif.MemoryBlock | None:
    """Compute following."""
    choices = [
        item for item in candidates if start < item.record_offset < stop
    ]
    return (
        min(choices, key=lambda item: item.record_offset) if choices else None
    )


def _block_layout(
    index: _CatalogueIndex,
    block: lif.MemoryBlock,
    next_flim_offset: int,
    timing: _BlockTiming,
    dimensions: _DimensionInfo,
) -> _BlockLayout:
    """Resolve line boundaries and repetitions before constructing
    detectors.
    """
    layout = _BlockLayout()
    layout.intensity = _following_block(
        index.intensities, block.record_offset, next_flim_offset
    )
    layout.frame_text = _last_text(
        "<FrameRepetitions>([^<]+)</FrameRepetitions>", timing.element_context
    )
    layout.line_text = _last_text(
        "<LineRepetitions>([^<]+)</LineRepetitions>", timing.element_context
    )
    layout.frame_repetitions = max(1, int(layout.frame_text or 1))
    layout.line_repetitions = max(1, int(layout.line_text or 1))
    layout.line_offsets = layout.frame_offsets = None
    layout.plane_row_starts = ()
    if timing.storage_format == "lmsraw":
        layout.line_offsets = _following_block(
            index.line_offset_blocks, block.record_offset, next_flim_offset
        )
        layout.frame_offsets = _following_block(
            index.frame_offset_blocks, block.record_offset, next_flim_offset
        )
        layout.decoded_rows, _unused = _parse_offset_table(
            index.data, layout.line_offsets, block.declared_size
        )
        layout.encoded_bytes = block.declared_size
        layout.plane_row_starts = _parse_frame_row_starts(
            index.data,
            layout.frame_offsets,
            dimensions.plane_count,
            layout.decoded_rows,
        )
    else:
        container_header = struct.unpack_from(
            "<8Q", index.data, block.data_start
        )
        layout.decoded_rows = int(container_header[5])
        layout.encoded_bytes = _encoded_container_bytes(
            container_header, block.declared_size
        )
    layout.repetition_model, _expected_rows, layout.dimension_status = (
        _resolve_repetition_model(
            layout.decoded_rows,
            dimensions.height,
            dimensions.plane_count,
            layout.line_repetitions,
            layout.frame_repetitions,
        )
    )
    if layout.decoded_rows == 0:
        layout.dimension_status = "empty"
    layout.frame_count = dimensions.plane_count if layout.decoded_rows else 0
    channel_meta = timing.metadata.get("channel") or {}
    layout.default_channel = (
        channel_meta.get("NameOfMeasuredQuantity")
        or channel_meta.get("Name")
        or None
    )
    layout.default_detector = _last_text(
        "<DetectorName>([^<]+)</DetectorName>", timing.timing_context
    )
    layout.raw_channels = _raw_channels(timing.element_context)
    layout.channel_count = max(
        1,
        dimensions.raw_dimension_values.get(
            "C", len(layout.raw_channels) or 1
        ),
    )
    if not layout.raw_channels:
        layout.raw_channels = [
            {
                "index": 0,
                "name": layout.default_detector,
                "identifier": None,
                "color": layout.default_channel,
            }
        ]
    layout.intensity_context = (
        _element_context(index.xml, layout.intensity.memory_id)
        if layout.intensity
        else ""
    )
    layout.intensity_channels = [
        lif.parse_attrs(match.group(1))
        for match in re.finditer(
            "<ChannelDescription\\b([^>]*)/>", layout.intensity_context
        )
    ]
    layout.plane_bytes = dimensions.width * dimensions.height * 4
    return layout


def _channel_dataset(
    index: _CatalogueIndex,
    block: lif.MemoryBlock,
    timing: _BlockTiming,
    dimensions: _DimensionInfo,
    layout: _BlockLayout,
    channel_index: int,
) -> DatasetInfo:
    """Build one detector's immutable metadata and linked-intensity
    thumbnail.
    """
    unknown_channel: RawChannel = {
        "index": channel_index,
        "name": None,
        "identifier": None,
        "color": None,
    }
    channel_record = next(
        (
            record
            for record in layout.raw_channels
            if record["index"] == channel_index
        ),
        unknown_channel,
    )
    channel_offset = 0
    if channel_index < len(layout.intensity_channels):
        channel_offset = int(
            layout.intensity_channels[channel_index].get("BytesInc", 0)
        )
    intensity_start = (
        layout.intensity.data_start + channel_offset
        if layout.intensity
        and not is_float16_preview(layout.intensity_context)
        else None
    )
    intensity_end = (
        intensity_start + layout.plane_bytes * dimensions.plane_count
        if intensity_start is not None
        else None
    )
    if (
        layout.intensity
        and intensity_end
        and (intensity_end > layout.intensity.data_end)
    ):
        intensity_start = intensity_end = None
    total, thumbnail = (None, None)
    if intensity_start is not None:
        movie = np.frombuffer(
            index.data,
            dtype="<f4",
            count=dimensions.plane_count
            * dimensions.width
            * dimensions.height,
            offset=intensity_start,
        ).reshape(
            dimensions.plane_count,
            dimensions.height,
            dimensions.width,
        )
        if np.all(np.isfinite(movie)) and np.all(movie >= 0):
            summed = movie.sum(axis=0, dtype=np.float64)
            total = int(np.rint(movie).astype(np.uint64).sum())
            thumbnail = _preview(summed)
        del movie
    if thumbnail is None:
        preview = float16_preview(
            index.data,
            layout.intensity,
            layout.intensity_context,
            dimensions.width,
            dimensions.height,
            channel_index,
        )
        if preview is None:
            preview = float32_preview(
                index.data,
                layout.intensity,
                layout.intensity_context,
                dimensions.width,
                dimensions.height,
                channel_index,
            )
        if preview is not None:
            thumbnail = _preview(preview)
    dataset = DatasetInfo(
        source=index.source,
        memory_id=block.memory_id,
        block_start=block.data_start,
        block_end=block.data_start + layout.encoded_bytes,
        compressed_bytes=layout.encoded_bytes,
        width=dimensions.width,
        height=dimensions.height,
        decoded_rows=layout.decoded_rows,
        intensity_memory_id=layout.intensity.memory_id
        if layout.intensity
        else None,
        intensity_start=intensity_start,
        intensity_end=intensity_end,
        total_photons=total,
        thumbnail=thumbnail,
        pixel_size_x_m=dimensions.pixel_x,
        pixel_size_y_m=dimensions.pixel_y,
        spatial_sources=dimensions.spatial_sources,
        clock_period_s=timing.clock_period,
        laser_frequency_hz=timing.laser_frequency,
        acquisition_name=timing.acquisition,
        series_name=timing.series,
        channel_name=str(channel_record.get("color") or layout.default_channel)
        if channel_record.get("color") or layout.default_channel
        else None,
        timepoint_name=_index_label("t", timing.time_index),
        z_name=_index_label("z", timing.z_index),
        detector_name=channel_record.get("name") or layout.default_detector,
        detector_identifier=channel_record.get("identifier") or None,
        channel_color=channel_record.get("color") or None,
        element_path=timing.path_names,
        frame_count=layout.frame_count,
        z_count=dimensions.z_count,
        t_count=dimensions.t_count,
        z_stride=dimensions.z_stride,
        t_stride=dimensions.t_stride,
        stage_count=dimensions.stage_count,
        stage_stride=dimensions.stage_stride,
        dimension_order=dimensions.dimension_order,
        dimension_status=layout.dimension_status,
        dimension_records=tuple(
            dict(item) for item in dimensions.dimensions_by_id.values()
        ),
        storage_format=timing.storage_format,
        channel_index=channel_index,
        channel_count=layout.channel_count,
        frame_repetitions=layout.frame_repetitions,
        line_repetitions=layout.line_repetitions,
        repetition_storage_model=layout.repetition_model,
        frame_repetitions_source="Leica XML element context"
        if layout.frame_text
        else "default",
        line_repetitions_source="Leica XML element context"
        if layout.line_text
        else "default",
        line_offsets_start=layout.line_offsets.data_start
        if layout.line_offsets
        else None,
        line_offsets_end=layout.line_offsets.data_end
        if layout.line_offsets
        else None,
        plane_row_starts=layout.plane_row_starts,
        excitation_wavelengths_nm=(excitation,)
        if (excitation := channel_record.get("excitation_nm")) is not None
        else (),
        sequence_index=channel_record.get("sequence_index", 0),
        sequence_count=channel_record.get("sequence_count", 1),
        local_detector_index=channel_record.get("detector_index"),
        sequence_detector_count=channel_record.get("detector_count"),
    )
    if timing.storage_format == "compressed":
        dataset = attach_detector_metadata(dataset, timing.element_context)
    if timing.storage_format == "compressed" and dataset.sequence_count > 1:
        model, _expected, status = _resolve_repetition_model(
            dataset.decoded_rows,
            dataset.height,
            dataset.plane_count,
            dataset.line_repetitions,
            dataset.frame_repetitions,
        )
        dataset = replace(
            dataset, repetition_storage_model=model, dimension_status=status
        )
    dataset = (
        attach_sequence_layout(
            dataset,
            timing.element_context,
            dimensions.raw_order,
            index.data,
            layout.frame_offsets,
        )
        if timing.storage_format == "lmsraw"
        else dataset
    )
    dataset = attach_mosaic(
        dataset,
        acquisition_context(index.xml, dataset),
        timing.element_context,
    )
    if timing.storage_format == "compressed":
        error = compressed_index_error(index.data, block)
        if error is not None:
            dataset = replace(
                dataset,
                repetition_storage_model="unresolved",
                dimension_status=error,
            )
    dataset = scope_intensity(
        dataset,
        index.data,
        layout.intensity,
        layout.intensity_context,
        _preview,
    )
    return attach_recorded_prefix(
        dataset,
        index.data,
        block,
        layout.intensity,
        layout.intensity_context,
    )


def _catalogue_groups(
    source: Path,
    data: mmap.mmap,
    xml: str,
    blocks: list[lif.MemoryBlock],
    element_paths: dict[str, tuple[str, ...]],
) -> tuple[_CatalogueIndex, list[lif.MemoryBlock]]:
    """Group linked intensity and line-index blocks before detector
    cataloguing.
    """
    names = {
        block.memory_id: lif.block_metadata(xml, block.memory_id)
        .get("element", {})
        .get("Name")
        for block in blocks
    }
    flim_blocks = [
        block
        for block in blocks
        if names.get(block.memory_id) in ("FLIM Compressed", "FLIM")
    ]
    intensities = [
        block for block in blocks if names.get(block.memory_id) == "Intensity"
    ]
    line_offset_blocks = [
        block
        for block in blocks
        if names.get(block.memory_id) == "LineOffsets"
    ]
    frame_offset_blocks = [
        block
        for block in blocks
        if names.get(block.memory_id) == "FrameOffsets"
    ]
    index = _CatalogueIndex(
        source,
        data,
        xml,
        element_paths,
        intensities,
        line_offset_blocks,
        frame_offset_blocks,
    )
    return (index, flim_blocks)
