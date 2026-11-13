"""Small tiled LMSRAW acquisitions with independent T/Z and channels."""

import struct
from itertools import accumulate, product
from pathlib import Path

import numpy as np

from tests.sequence_fixture import _record  # pylint: disable=protected-access


def _photon_data(count, times, depths, channels):
    payloads, intensity, frame_ends = [], [], []
    for time, stage, depth in product(
        range(times), range(count), range(depths)
    ):
        words = []
        for _x in range(3):
            for route in range(channels):
                arrival = 2 + stage * 3 + depth + time * 5 + route
                repeats = stage + 1 + depth + time + route
                words.extend([((route * 2 + 1) << 12) | arrival] * repeats)
            words.extend((0xA004, 0xA008))
        payloads.extend([np.array(words, dtype=">u2").tobytes()] * 12)
        frame_ends.append(len(payloads))
        for route in range(channels):
            intensity.append(
                np.full(
                    (2, 3), 6 * (stage + 1 + depth + time + route), dtype="<f4"
                ).tobytes()
            )
    photons = b"".join(payloads)
    ends = list(accumulate(map(len, payloads)))
    lines = struct.pack("<5Q", 1, len(ends), len(photons), 0, 0)
    lines += b"".join(struct.pack("<2Q", end, 0) for end in ends)
    frames = struct.pack("<2Q", 1, len(frame_ends)) + struct.pack(
        f"<{len(frame_ends)}Q", *frame_ends
    )
    return photons, lines, frames, b"".join(intensity)


def _raw_metadata(cells, times, depths, channels):
    count = len(cells)
    stages = "".join(
        f"<StagePositions><X>{column * 1e-5}</X>"
        f"<Y>{row * 1e-5}</Y><Z>0</Z></StagePositions>"
        for column, row in cells
    )
    dimensions = "".join(
        f"<Dimension><DimensionIdentifier>{axis}</DimensionIdentifier>"
        f"<Size>{size}</Size></Dimension>"
        for axis, size in (
            ("X", 3),
            ("Y", 2),
            ("C", channels),
            ("Z", depths),
            ("S", count),
            ("T", times),
        )
    )
    routes = "".join(
        "<Channel><Detectors><DetectorReferences>"
        "<SequenceItemIndex>0</SequenceItemIndex>"
        f"<DetectorIndex>{route}</DetectorIndex>"
        "</DetectorReferences></Detectors></Channel>"
        for route in range(channels)
    )
    detectors = "".join(
        f"<Detectors><Detector>{route}</Detector><Name>Detector {route}</Name>"
        f"<Identifier>{3 + route}</Identifier>"
        "<DataType>PulseVersion2</DataType>"
        "<DeadTime>1.3e-9</DeadTime><Excitation>5.61e-7</Excitation>"
        "<LaserPulseFrequency>156250000</LaserPulseFrequency></Detectors>"
        for route in range(channels)
    )
    raw = (
        "<RawData><Format>LMSRAW</Format><VoxelSizeX>1e-6</VoxelSizeX>"
        "<VoxelSizeY>1e-6</VoxelSizeY><ClockPeriod>1e-10</ClockPeriod>"
        "<LaserPulseFrequency>156250000</LaserPulseFrequency>"
        f"<Dimensions>{dimensions}</Dimensions><Channels>{routes}</Channels>"
        "<Sequence><SequenceItem><FrameRepetitions>3</FrameRepetitions>"
        "<LineRepetitions>2</LineRepetitions><HasRawData>true</HasRawData>"
        f"<Detectors>{detectors}</Detectors></SequenceItem></Sequence>"
        "<SequentialMode>SequentialLine</SequentialMode></RawData>" + stages
    )
    return raw


def _image_metadata(columns, rows, count, channels, depths, times):
    tile_info = (
        '<Attachment Name="TileScanInfo" FlipX="0" FlipY="0" SwapXY="0">'
        + "".join(
            f'<Tile FieldX="{column}" FieldY="{row}" PosX="{column * 1e-5}" '
            f'PosY="{row * 1e-5}" PosZ="0"/>'
            for row in range(rows)
            for column in range(columns)
        )
        + "</Attachment>"
    )
    image = (
        "<Image><ImageDescription><Channels>"
        + "".join(
            f'<ChannelDescription BytesInc="{route * 24}"/>'
            for route in range(channels)
        )
        + "</Channels><Dimensions>"
        + "".join(
            f'<DimensionDescription DimID="{axis}" '
            f'NumberOfElements="{size}" BytesInc="{stride}"/>'
            for axis, size, stride in (
                (1, 3, 4),
                (2, 2, 12),
                (3, depths, 24 * channels),
                (10, count, 24 * channels * depths),
                (4, times, 24 * channels * depths * count),
            )
        )
        + "</Dimensions></ImageDescription>"
        + tile_info
        + "</Image>"
    )
    return image


def mosaic_lif(
    path: Path,
    columns: int = 2,
    rows: int = 2,
    *,
    times: int = 1,
    depths: int = 1,
    channels: int = 1,
    bad_frames: bool = False,
) -> Path:
    """Tile metadata is row-major; photon stages follow a snake path."""
    cells = [
        (column, row)
        for row in range(rows)
        for column in (
            range(columns) if row % 2 == 0 else reversed(range(columns))
        )
    ]
    count = len(cells)
    photons, lines, frames, intensity = _photon_data(
        count, times, depths, channels
    )
    if bad_frames:
        frames = (
            struct.pack("<2Q", 1, struct.unpack_from("<Q", frames, 8)[0] - 1)
            + frames[16:]
        )
    raw = _raw_metadata(cells, times, depths, channels)
    image = _image_metadata(columns, rows, count, channels, depths, times)
    optics = (
        '<ATLConfocalSettingDefinition IsEnabledForScanning="1">'
        + "".join(
            f'<Detector Channel="{3 + route}" IsActive="1"/>'
            f'<MultiBand Channel="{3 + route}" '
            'LeftWorld="580" RightWorld="700"/>'
            for route in range(channels)
        )
        + "</ATLConfocalSettingDefinition>"
    )
    values = [
        (1, "FLIM", raw, photons),
        (2, "Intensity", image, intensity),
        (3, "LineOffsets", "", lines),
        (4, "FrameOffsets", "", frames),
    ]
    children = "".join(
        f'<Element Name="{name}"><Data>{body}</Data>'
        f'<Memory Size="{len(payload)}" '
        f'MemoryBlockID="MemBlock_{index}"/></Element>'
        for index, name, body, payload in values
    )
    xml = (
        '<LMSDataContainerHeader><Element Name="Mosaic"><Data>'
        + image
        + optics
        + "</Data><Children>"
        + children
        + "</Children></Element></LMSDataContainerHeader>"
    ).encode("utf-16le")
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + b"".join(
            _record(index, payload) for index, _name, _body, payload in values
        )
    )
    return path
