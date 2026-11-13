"""Literal-only Deflate fixture with interleaved detectors."""

import struct
import zlib
from pathlib import Path

import numpy as np

from tests.sequence_fixture import _record  # pylint: disable=protected-access


def _container(rows: list[bytes]) -> bytes:
    # A complete alphabet: EOB has length 1, bytes have length 9.
    # Code-length symbols 1 and 9 have length 1. Descriptor boundaries
    # are constructed independently of the production codec.
    bits: list[int] = []

    def write(value: int, width: int) -> None:
        bits.extend((value >> index) & 1 for index in range(width))

    write(1, 1)  # final
    write(2, 2)  # dynamic Huffman
    write(0, 5)  # 257 literal codes
    write(0, 5)  # one distance code
    write(14, 4)  # 18 code-length codes
    for symbol in (
        16,
        17,
        18,
        0,
        8,
        7,
        9,
        6,
        10,
        5,
        11,
        4,
        12,
        3,
        13,
        2,
        14,
        1,
    ):
        write(int(symbol in (1, 9)), 3)
    bits.extend([1] * 256 + [0, 0])
    header_bits = len(bits)
    for row in rows:
        for token in row:
            bits.extend(
                (256 + token >> shift) & 1 for shift in range(8, -1, -1)
            )
    write(0, 1)  # EOB
    bits.extend([0] * (-len(bits) % 8))
    packed = bytes(
        sum(bit << shift for shift, bit in enumerate(bits[index : index + 8]))
        for index in range(0, len(bits), 8)
    )
    payload = b"".join(rows)
    stream = b"\x78\x01" + packed + struct.pack(">I", zlib.adler32(payload))
    assert zlib.decompress(stream) == payload
    descriptors = [16, 0xC0000000 | header_bits] + [
        0x80000000 | (len(row) * 9 + int(index == len(rows) - 1))
        for index, row in enumerate(rows)
    ]
    table = struct.pack(f"<{len(descriptors)}I", *descriptors)
    return (
        struct.pack("<8Q", 1, 64, len(stream), len(table), 16, len(rows), 0, 0)
        + stream
        + table
    )


def _metadata(route: int) -> str:
    channels = "".join(
        "<Channel><Detectors><DetectorReferences>"
        f"<SequenceItemIndex>{seq}</SequenceItemIndex>"
        "<DetectorIndex>0</DetectorIndex></DetectorReferences>"
        f"</Detectors><ColorPalette>{color}</ColorPalette></Channel>"
        for seq, color in enumerate(("Green", "Cyan"))
    )
    sequences = "".join(
        "<SequenceItem><HasRawData>true</HasRawData>"
        "<LineRepetitions>2</LineRepetitions>"
        "<FrameRepetitions>1</FrameRepetitions><Detectors><Detectors>"
        f"<Detector>{detector}</Detector><Name>{name}</Name>"
        f"<Identifier>{identifier}</Identifier>"
        f"<Excitation>{excitation}</Excitation>"
        f"<LaserPulseFrequency>{frequency}</LaserPulseFrequency>"
        "<DeadTime>1.3e-9</DeadTime><DataType>PulseVersion2</DataType>"
        "</Detectors></Detectors></SequenceItem>"
        for detector, name, identifier, excitation, frequency in (
            (0, "HyD X 3", 3, 5.55e-7, 1e9),
            (route, "HyD NDD 2", 1001, 0, 5e8),
        )
    )
    return (
        "<RawData><Format>LMSCOMPRESSED</Format>"
        "<ClockPeriod>1e-10</ClockPeriod>"
        "<LaserPulseFrequency>1e9</LaserPulseFrequency>"
        "<Dimensions><Dimension><DimensionIdentifier>C</DimensionIdentifier>"
        "<Size>3</Size></Dimension></Dimensions>"
        f"<Channels>{channels}</Channels><Sequence>{sequences}</Sequence>"
        "<SequentialMode>SequentialFrame</SequentialMode></RawData>"
    )


def _optics() -> str:
    return (
        "<LDM_Block_Sequential_List>"
        + "".join(
            '<ATLConfocalSettingDefinition IsEnabledForScanning="1" '
            f'UserSettingName="Setting {index + 1}">'
            f'<Detector Channel="{identifier}" IsActive="1"/>'
            f'<MultiBand Channel="{identifier}" LeftWorld="{left}" '
            f'RightWorld="{right}"/><Aotf LightSourceName="{source}">'
            f'<LaserLineSetting LaserLine="{wavelength}" IntensityDev="5"/>'
            f'</Aotf><Laser LightSourceName="{source}" LaserName="{name}"/>'
            "</ATLConfocalSettingDefinition>"
            for index, (
                identifier,
                left,
                right,
                source,
                name,
                wavelength,
            ) in enumerate(
                (
                    (3, 565, 630, "SuperContVisible Light", "WLL", 555),
                    (1001, 410, 490, "MP1", "MP", 740),
                )
            )
        )
        + "</LDM_Block_Sequential_List>"
    )


def mixed_compressed_lif(path: Path, route: int = 1) -> Path:
    """Store two sequences' photons together in each compressed row."""
    rows = []
    for y in range(2):
        row = bytearray()
        for x in range(3):
            for detector, times in ((0, (1, 2)), (route, (2, 2, 2))):
                row.extend((0xA8 | detector, *times))
                row.extend([0] * (x + y))
                for marker, arrival in ((0xA0, 4), (0xB0, 5), (0xB8, 6)):
                    row.extend((marker | detector, arrival))
            row.append(0x81)
        rows.append(bytes(row))
    compressed = _container(rows)
    intensities = np.array(
        [
            [[4 + x + y for x in range(3)] for y in range(2)],
            [[5 + x + y for x in range(3)] for y in range(2)],
        ],
        dtype="<f4",
    ).tobytes()
    image = (
        '<Image><ImageDescription><Channels><ChannelDescription BytesInc="0"/>'
        '<ChannelDescription BytesInc="24"/></Channels><Dimensions>'
        '<DimensionDescription DimID="1" NumberOfElements="3" Length="3e-6" '
        'BytesInc="4"/><DimensionDescription DimID="2" NumberOfElements="2" '
        'Length="2e-6" BytesInc="12"/></Dimensions></ImageDescription></Image>'
    )
    xml = (
        '<LMSDataContainerHeader><Element Name="Mixed compressed"><Data>'
        + _optics()
        + '</Data><Children><Element Name="FLIM Compressed"><Data>'
        + _metadata(route)
        + image
        + f'</Data><Memory Size="{len(compressed)}" '
        'MemoryBlockID="MemBlock_1"/>'
        + '<Children><Element Name="Intensity"><Data>'
        + image
        + '</Data><Memory Size="48" MemoryBlockID="MemBlock_2"/>'
        + "</Element></Children></Element></Children></Element>"
        + "</LMSDataContainerHeader>"
    ).encode("utf-16le")
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + _record(1, compressed)
        + _record(2, intensities)
    )
    return path
