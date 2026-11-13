"""Independent interleaved WLL/MP compressed C/T/Z photon fixtures."""

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Build container bytes independently of the production decoders.
# pylint: disable=protected-access
from tests.compressed_fixture import _container, _metadata, _optics
from tests.sequence_fixture import _record


@dataclass(frozen=True)
class StackSpec:
    """Vary storage layout and the reserved image extent separately."""

    order: tuple[str, ...] = ("Z", "T", "C")
    recorded: int = 5
    explicit: bool = False
    row_deficit: int = 0
    frames: int = 2
    lines: int = 2


def expected_stack_cube(spec, plane, channel, mask=15, bins=20):
    """Count known arrivals without using the container reader."""
    expected = np.zeros((bins, 3, 5), np.uint64)
    period = 20 if channel else 10
    for y in range(3):
        for x in range(5):
            expected[2 * bins // period, y, x] = (
                (plane + x + y + channel + 1) * spec.frames * spec.lines
            )
            for flag, arrival in ((2, 4), (4, 5), (8, 6)):
                if mask & flag:
                    expected[arrival * bins // period, y, x] += (
                        spec.frames * spec.lines
                    )
    return expected


_DEFAULT_SPEC = StackSpec()


def _pixel_row(spec, plane, y):
    row = bytearray()
    for x in range(5):
        for channel in range(2):
            count = plane + x + y + channel + 1
            repeats = 1 if spec.explicit else spec.lines
            row.extend((0xA8 | channel, 2))
            row.extend([0] * (count * repeats - 1))
            for marker, arrival in ((0xA0, 4), (0xB0, 5), (0xB8, 6)):
                row.extend((marker | channel, arrival))
                row.extend([0] * (repeats - 1))
        row.append(0x81)
    return bytes(row)


def _stack_rows(spec):
    rows = []
    for plane in range(spec.recorded):
        for _frame in range(spec.frames):
            for y in range(3):
                for _repeat in range(spec.lines if spec.explicit else 1):
                    rows.append(_pixel_row(spec, plane, y))
    if spec.row_deficit:
        rows = rows[: -spec.row_deficit]
    return rows


def compressed_stack_lif(path: Path, spec: StackSpec = _DEFAULT_SPEC) -> Path:
    """Reserve Z=3,T=2 planes while recording a verified prefix."""
    compressed = _container(_stack_rows(spec))
    sizes = {"Z": 3, "T": 2, "C": 2}
    strides = {}
    size = 60
    for axis in spec.order:
        strides[axis] = size
        size *= sizes[axis]
    plane_order = tuple(axis for axis in spec.order if axis != "C")
    references = bytearray(size)
    for plane in range(spec.recorded):
        coordinates = {
            plane_order[0]: plane % sizes[plane_order[0]],
            plane_order[1]: plane // sizes[plane_order[0]],
        }
        for channel in range(2):
            start = channel * strides["C"] + sum(
                coordinates[axis] * strides[axis] for axis in plane_order
            )
            image = expected_stack_cube(spec, plane, channel).sum(axis=0)
            references[start : start + 60] = image.astype("<f4").tobytes()
    dimensions = (
        '<DimensionDescription DimID="1" NumberOfElements="5" '
        'Length="5e-6" BytesInc="4"/>'
        '<DimensionDescription DimID="2" NumberOfElements="3" '
        'Length="3e-6" BytesInc="20"/>'
        + "".join(
            f'<DimensionDescription DimID="{identifier}" '
            f'NumberOfElements="{sizes[axis]}" '
            f'BytesInc="{strides[axis]}"/>'
            for axis, identifier in (("Z", 3), ("T", 4))
        )
    )
    image = (
        '<Image><ImageDescription><Channels><ChannelDescription BytesInc="0"/>'
        f'<ChannelDescription BytesInc="{strides["C"]}"/>'
        f"</Channels><Dimensions>{dimensions}</Dimensions>"
        "</ImageDescription></Image>"
    )
    metadata = (
        _metadata(1)
        .replace("<FrameRepetitions>1", f"<FrameRepetitions>{spec.frames}")
        .replace("<LineRepetitions>2", f"<LineRepetitions>{spec.lines}")
    )
    xml = (
        '<LMSDataContainerHeader><Element Name="Compressed stack"><Data>'
        + _optics()
        + '</Data><Children><Element Name="FLIM Compressed"><Data>'
        + metadata
        + image
        + f'</Data><Memory Size="{len(compressed)}" '
        'MemoryBlockID="MemBlock_1"/><Children>'
        '<Element Name="Intensity"><Data>'
        + image
        + f'</Data><Memory Size="{len(references)}" '
        'MemoryBlockID="MemBlock_2"/></Element></Children></Element>'
        "</Children></Element></LMSDataContainerHeader>"
    ).encode("utf-16le")
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + _record(1, compressed)
        + _record(2, bytes(references))
    )
    return path
