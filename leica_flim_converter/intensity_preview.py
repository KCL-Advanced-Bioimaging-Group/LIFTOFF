"""Read bounded Leica display previews using declared byte strides."""

from __future__ import annotations

import mmap
import re

import numpy as np

import lif_flim_forensics as lif


def _records(tag: str, context: str) -> list[dict[str, str]]:
    return [
        lif.parse_attrs(match.group(1))
        for match in re.finditer(rf"<{tag}\b([^>]*)>", context)
    ]


def is_float16_preview(context: str) -> bool:
    """Require Leica's F16 marker to interpret half floats."""
    return any(
        record.get("Name") == "F16"
        for record in _records("Attachment", context)
    )


def _preview_layout(
    context: str, width: int, height: int, channel_index: int, bits: int = 16
) -> tuple[tuple[int, ...], tuple[int, ...], int]:
    """Validate the shape, channel offset and byte strides."""
    channels = _records("ChannelDescription", context)
    if not 0 <= channel_index < len(channels):
        raise ValueError("Preview channel is unavailable")
    channel = channels[channel_index]
    if channel.get("Resolution") != str(bits):
        raise ValueError("Preview sample resolution differs from its format")
    if bits == 32 and channel.get("DataType") != "1":
        raise ValueError("F32 preview requires floating-point channel samples")
    dimensions = {
        record.get("DimID"): record
        for record in _records("DimensionDescription", context)
    }
    x_dimension = dimensions.pop("1")
    y_dimension = dimensions.pop("2")
    if (
        int(x_dimension["NumberOfElements"]) != width
        or int(y_dimension["NumberOfElements"]) != height
    ):
        raise ValueError("Preview dimensions differ from the acquisition")
    axes = list(dimensions.values()) + [y_dimension, x_dimension]
    shape = tuple(int(axis["NumberOfElements"]) for axis in axes)
    strides = tuple(int(axis["BytesInc"]) for axis in axes)
    offset = int(channel.get("BytesInc", "0"))
    if (
        offset < 0
        or int(channel.get("BitInc", "0")) != 0
        or any(int(axis.get("BitInc", "0")) != 0 for axis in axes)
    ):
        raise ValueError("Unsupported preview channel or bit offset")
    if (
        any(size <= 0 for size in shape)
        or any(stride < 0 for stride in strides)
        or any(
            size > 1 and stride < bits // 8
            for size, stride in zip(shape, strides, strict=True)
        )
    ):
        raise ValueError("Invalid preview shape or byte strides")
    return shape, strides, offset


def float16_preview(
    data: mmap.mmap,
    block: lif.MemoryBlock | None,
    context: str,
    width: int,
    height: int,
    channel_index: int,
) -> np.ndarray | None:
    """Sum the display preview's available planes."""
    if block is None or not is_float16_preview(context):
        return None
    return _float_preview(
        data, block, context, width, height, channel_index, 16
    )


def float32_preview(
    data: mmap.mmap,
    block: lif.MemoryBlock | None,
    context: str,
    width: int,
    height: int,
    channel_index: int,
) -> np.ndarray | None:
    """Read available F32 planes, including incomplete acquisitions."""
    if block is None or is_float16_preview(context):
        return None
    return _float_preview(
        data, block, context, width, height, channel_index, 32
    )


def _float_preview(
    data: mmap.mmap,
    block: lif.MemoryBlock,
    context: str,
    width: int,
    height: int,
    channel_index: int,
    bits: int,
) -> np.ndarray | None:
    try:
        shape, strides, offset = _preview_layout(
            context, width, height, channel_index, bits
        )
        end = (
            offset
            + bits // 8
            + sum(
                (size - 1) * stride
                for size, stride in zip(shape, strides, strict=True)
            )
        )
        if end > block.declared_size or block.data_start + end > min(
            block.data_end, len(data)
        ):
            return None
        values = np.ndarray(
            shape,
            dtype=f"<f{bits // 8}",
            buffer=data,
            offset=block.data_start + offset,
            strides=strides,
        )
        if not np.all(np.isfinite(values)) or np.any(values < 0):
            return None
        # Display normalization cancels any positive scaling factor.
        # Lossy or partial previews cannot supply exact photon counts.
        return values.sum(axis=tuple(range(values.ndim - 2)), dtype=np.float64)
    except KeyError, ValueError, OverflowError:
        return None
