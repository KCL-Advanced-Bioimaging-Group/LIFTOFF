"""Half-float preview strides and optional-data validation."""

import mmap
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import lif_flim_forensics as lif
from leica_flim_converter.intensity_preview import (
    float16_preview,
    float32_preview,
)


@pytest.fixture(name="half_float_preview")
def half_float_preview_fixture(
    tmp_path: Path,
) -> Iterator[tuple[mmap.mmap, lif.MemoryBlock, str, np.ndarray]]:
    """Provide two timepoints with interleaved detector channels."""
    values = np.arange(48, dtype="<f2").reshape(2, 3, 4, 2)
    payload = values.tobytes()
    prefix = b"padding"
    source = tmp_path / "preview.bin"
    source.write_bytes(prefix + payload)
    block = lif.MemoryBlock(
        "MemBlock_2",
        len(payload),
        0,
        len(prefix),
        source.stat().st_size,
        0,
        0.0,
        "",
    )
    context = """
    <Attachment Name="F16" FactorF32ToF16="0.5"/>
    <ChannelDescription Resolution="16" BytesInc="0"/>
    <ChannelDescription Resolution="16" BytesInc="2"/>
    <DimensionDescription DimID="1" NumberOfElements="4" BytesInc="4"/>
    <DimensionDescription DimID="2" NumberOfElements="3" BytesInc="16"/>
    <DimensionDescription DimID="4" NumberOfElements="2" BytesInc="48"/>
    """
    with (
        source.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        yield data, block, context, values


@pytest.mark.parametrize("channel", [0, 1])
def test_half_float_channel_and_time_strides(
    half_float_preview: tuple[mmap.mmap, lif.MemoryBlock, str, np.ndarray],
    channel: int,
) -> None:
    """Sum time while respecting detector, pixel and row offsets."""
    data, block, context, values = half_float_preview
    result = float16_preview(data, block, context, 4, 3, channel)
    assert result is not None
    assert np.array_equal(result, values[:, :, :, channel].sum(axis=0))
    assert result.dtype == np.float64


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('Name="F16"', 'Name="Other"'),
        ('Resolution="16"', 'Resolution="32"'),
        ('NumberOfElements="4"', 'NumberOfElements="5"'),
        ('BytesInc="48"', 'BytesInc="480"'),
        ('BytesInc="16"', 'BytesInc="-16"'),
        ('BytesInc="4"', 'BytesInc="1"'),
        ('BytesInc="4"', 'BytesInc="4" BitInc="1"'),
    ],
)
def test_invalid_preview_metadata_is_optional(
    half_float_preview: tuple[mmap.mmap, lif.MemoryBlock, str, np.ndarray],
    original: str,
    replacement: str,
) -> None:
    """Decline invalid previews while retaining photon decoding."""
    data, block, context, _values = half_float_preview
    assert (
        float16_preview(
            data, block, context.replace(original, replacement), 4, 3, 0
        )
        is None
    )


def test_truncated_preview_does_not_cross_block(
    half_float_preview: tuple[mmap.mmap, lif.MemoryBlock, str, np.ndarray],
) -> None:
    """Respect payload bounds when more bytes follow the block."""
    data, block, context, _values = half_float_preview
    truncated = replace(block, declared_size=block.declared_size - 2)
    assert float16_preview(data, truncated, context, 4, 3, 1) is None


def test_float32_available_preview_planes(tmp_path: Path) -> None:
    """Use available display planes independently of photon T count."""
    values = np.arange(48, dtype="<f4").reshape(2, 3, 4, 2)
    source = tmp_path / "preview.bin"
    source.write_bytes(values.tobytes())
    block = lif.MemoryBlock(
        "MemBlock_1",
        source.stat().st_size,
        0,
        0,
        source.stat().st_size,
        0,
        0.0,
        "",
    )
    context = """
    <ChannelDescription DataType="1" Resolution="32" BytesInc="0"/>
    <ChannelDescription DataType="1" Resolution="32" BytesInc="4"/>
    <DimensionDescription DimID="1" NumberOfElements="4" BytesInc="8"/>
    <DimensionDescription DimID="2" NumberOfElements="3" BytesInc="32"/>
    <DimensionDescription DimID="4" NumberOfElements="2" BytesInc="96"/>
    """
    with (
        source.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        for channel in (0, 1):
            preview = float32_preview(data, block, context, 4, 3, channel)
            assert preview is not None
            assert np.array_equal(
                preview, values[:, :, :, channel].sum(axis=0)
            )
        assert (
            float32_preview(
                data,
                block,
                context.replace('DataType="1"', 'DataType="0"'),
                4,
                3,
                0,
            )
            is None
        )
        assert (
            float32_preview(
                data,
                replace(block, declared_size=block.declared_size - 4),
                context,
                4,
                3,
                1,
            )
            is None
        )
