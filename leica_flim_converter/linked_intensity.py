"""Sequence-scoped intensity references and bounded plane reads."""

from __future__ import annotations

import mmap
import re
from collections.abc import Callable, Iterable
from dataclasses import replace

import numpy as np
from PIL import Image

import lif_flim_forensics as lif

from .dataset import DatasetInfo


def sum_intensity_planes(
    dataset: DatasetInfo, planes: Iterable[np.ndarray]
) -> np.ndarray:
    """Sum T/Z planes and place each tile in a separate cell."""
    layout = dataset.mosaic if dataset.tile_index is None else None
    result = np.zeros(
        (
            dataset.height * (layout.rows if layout else 1),
            dataset.width * (layout.columns if layout else 1),
        ),
        dtype=np.float64,
    )
    for index, plane in enumerate(planes):
        x = y = 0
        if layout is not None:
            tile = layout.tiles[dataset.plane_stage_index(index)]
            x, y = tile.column * dataset.width, tile.row * dataset.height
        result[y : y + dataset.height, x : x + dataset.width] += plane
    return result


def validated_intensity_starts(
    dataset: DatasetInfo, block: lif.MemoryBlock, context: str
) -> tuple[int, ...]:
    """Validate the entire declared C/T/Z/S reference layout."""
    dimensions = {
        attributes.get("DimID"): attributes
        for match in re.finditer(r"<DimensionDescription\b([^>]*)>", context)
        if (attributes := lif.parse_attrs(match.group(1)))
    }
    plane_bytes = dataset.width * dataset.height * 4
    if plane_bytes <= 0:
        raise ValueError("Invalid intensity spatial dimensions")
    channels = [
        lif.parse_attrs(match.group(1))
        for match in re.finditer(r"<ChannelDescription\b([^>]*)>", context)
    ]
    channel_offsets = [int(channel["BytesInc"]) for channel in channels]
    if dataset.channel_index >= len(channel_offsets) or len(
        set(channel_offsets)
    ) != len(channel_offsets):
        raise ValueError("Intensity detector channel mapping is unavailable")
    if any(offset < 0 or offset % plane_bytes for offset in channel_offsets):
        raise ValueError("Unsupported intensity channel stride")
    if (
        int(dimensions["1"]["BytesInc"]) != 4
        or int(dimensions["2"]["BytesInc"]) != dataset.width * 4
    ):
        raise ValueError("Unsupported intensity spatial strides")
    if (
        int(dimensions["1"]["NumberOfElements"]) != dataset.width
        or int(dimensions["2"]["NumberOfElements"]) != dataset.height
    ):
        raise ValueError(
            "Intensity spatial dimensions differ from photon data"
        )
    z_dimension, t_dimension, stage_dimension = (
        dimensions.get("3", {}),
        dimensions.get("4", {}),
        dimensions.get("10", {}),
    )
    if (
        int(z_dimension.get("NumberOfElements", 1)) != dataset.z_count
        or int(t_dimension.get("NumberOfElements", 1)) != dataset.t_count
        or int(stage_dimension.get("NumberOfElements", 1))
        != dataset.stage_count
    ):
        raise ValueError("Intensity T/Z coverage differs from photon data")
    z_stride = int(z_dimension.get("BytesInc", 0))
    t_stride = int(t_dimension.get("BytesInc", 0))
    stage_stride = int(stage_dimension.get("BytesInc", 0))
    if any(
        size > 1 and stride <= 0
        for size, stride in (
            (dataset.z_count, z_stride),
            (dataset.t_count, t_stride),
            (dataset.stage_count, stage_stride),
        )
    ):
        raise ValueError("Intensity T/Z strides are unavailable")
    if (
        z_stride % plane_bytes
        or t_stride % plane_bytes
        or stage_stride % plane_bytes
    ):
        raise ValueError("Unsupported intensity T/Z strides")
    tz_offsets = tuple(
        t * t_stride + z * z_stride + stage * stage_stride
        for stage, (t, z) in (
            (dataset.plane_stage_index(plane), dataset.plane_indices(plane))
            for plane in range(dataset.plane_count)
        )
    )
    all_offsets = [
        channel + tz for channel in channel_offsets for tz in tz_offsets
    ]
    if len(set(all_offsets)) != len(all_offsets):
        raise ValueError("Intensity C/T/Z planes overlap")
    starts = tuple(
        block.data_start + channel_offsets[dataset.channel_index] + tz
        for tz in tz_offsets
    )
    if any(
        start < block.data_start or start + plane_bytes > block.data_end
        for start in starts
    ):
        raise ValueError("Intensity plane exceeds its memory block")
    return starts


def scope_intensity(
    dataset: DatasetInfo,
    data: mmap.mmap,
    block: lif.MemoryBlock | None,
    context: str,
    thumbnail: Callable[[np.ndarray], Image.Image],
) -> DatasetInfo:
    """Follow declared C/T/Z/S strides for scoped references."""
    if (
        (dataset.sequence_count <= 1 and dataset.stage_count <= 1)
        or block is None
        or dataset.intensity_start is None
    ):
        return dataset
    try:
        starts = validated_intensity_starts(dataset, block, context)
        planes = []
        total = 0
        for start in starts:
            plane = np.frombuffer(
                data,
                dtype="<f4",
                count=dataset.width * dataset.height,
                offset=start,
            ).reshape(dataset.height, dataset.width)
            if not np.all(np.isfinite(plane)) or np.any(plane < 0):
                raise ValueError("Invalid intensity values")
            planes.append(plane)
            total += int(np.rint(plane).astype(np.uint64).sum())
        summed = sum_intensity_planes(dataset, planes)
        return replace(
            dataset,
            intensity_plane_starts=starts,
            total_photons=total,
            thumbnail=thumbnail(summed),
        )
    except KeyError, ValueError:
        return replace(
            dataset,
            intensity_start=None,
            intensity_end=None,
            total_photons=None,
            thumbnail=None,
        )


def read_intensity_plane(
    dataset: DatasetInfo, plane: int
) -> np.ndarray | None:
    """Read a bounded calibrated plane for this detector."""
    if dataset.intensity_start is None or dataset.intensity_end is None:
        return None
    size = dataset.width * dataset.height * 4
    if dataset.intensity_plane_starts:
        if not 0 <= plane < len(dataset.intensity_plane_starts):
            return None
        start = dataset.intensity_plane_starts[plane]
    else:
        start = dataset.intensity_start + plane * size
        if plane < 0 or start + size > dataset.intensity_end:
            return None
    with dataset.source.open("rb") as stream:
        stream.seek(start)
        payload = stream.read(size)
    if len(payload) != size:
        return None
    return np.frombuffer(payload, dtype="<f4").reshape(
        dataset.height, dataset.width
    )
