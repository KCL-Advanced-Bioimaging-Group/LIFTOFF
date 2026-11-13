"""Small indexed LIFs with independent excitation and T/Z axes."""

import struct
from itertools import accumulate
from pathlib import Path

import numpy as np


def _record(index: int, payload: bytes) -> bytes:
    name = f"MemBlock_{index}".encode("utf-16le")
    return (
        struct.pack(
            "<IIBQBI",
            112,
            14 + len(name),
            42,
            len(payload),
            42,
            len(name) // 2,
        )
        + name
        + payload
    )


def _detector(sequence: int, route: int) -> str:
    dead_time = ((2e-10, 6e-10), (1e-9, 2e-10))[sequence % 2][route]
    frequency = 1e9 if sequence % 2 == 0 else 2.5e8
    return (
        f"<Detectors><Detector>{route}</Detector>"
        f"<Name>Detector {route + 1}</Name>"
        f"<Identifier>{1000 + route}</Identifier>"
        f"<Excitation>{(840 + sequence * 100) * 1e-9}</Excitation>"
        f"<LaserPulseFrequency>{frequency}</LaserPulseFrequency>"
        f"<DeadTime>{dead_time}</DeadTime><DataType>PulseVersion2</DataType>"
        "</Detectors>"
    )


def _sequence(index: int) -> str:
    return (
        "<SequenceItem><HasRawData>true</HasRawData>"
        f"<ClockPeriod>{1e-10 if index % 2 == 0 else 2e-10}</ClockPeriod>"
        f"<VoxelSizeX>{(index + 1) * 1e-6}</VoxelSizeX>"
        f"<VoxelSizeY>{(index + 1) * 2e-6}</VoxelSizeY>"
        f"<LineRepetitions>{2 if index % 2 == 0 else 1}</LineRepetitions>"
        f"<FrameRepetitions>{2 if index % 2 == 0 else 1}</FrameRepetitions>"
        "<Detectors>"
        + "".join(_detector(index, route) for route in range(2))
        + "</Detectors></SequenceItem>"
    )


def _channel(index: int) -> str:
    return (
        "<Channel><Detectors><DetectorReferences>"
        f"<SequenceItemIndex>{index // 2}</SequenceItemIndex>"
        f"<DetectorIndex>{index % 2}</DetectorIndex>"
        "</DetectorReferences></Detectors>"
        f"<ColorPalette>Channel {index + 1}</ColorPalette></Channel>"
    )


def _optical(index: int) -> str:
    return (
        f'<ATLConfocalSettingDefinition IsEnabledForScanning="1" '
        f'UserSettingName="Setting {index + 1}"><MultiBandList>'
        + "".join(
            f'<Detector Channel="{1000 + route}" IsActive="1"/>'
            f'<MultiBand Channel="{1000 + route}" '
            f'LeftWorld="{470 + index * 10 + route * 50}" '
            f'RightWorld="{510 + index * 10 + route * 50}"/>'
            for route in range(2)
        )
        + "</MultiBandList></ATLConfocalSettingDefinition>"
    )


def _indexed_payload(
    mode: str, sequences: int, invalid_frames: bool, time_fast: bool
) -> tuple[bytes, bytes, bytes]:
    """Build declared frame slots with two detector routes."""
    rows, frame_sizes = [], []
    slots = (
        (
            (time, z, seq)
            for time in range(2)
            for z in range(2)
            for seq in range(sequences)
        )
        if mode == "SequentialFrame"
        else (
            (time, z, seq)
            for time in range(2)
            for seq in range(sequences)
            for z in range(2)
        )
    )
    if time_fast:
        slots = (
            sorted(slots, key=lambda slot: (slot[1], slot[0], slot[2]))
            if mode == "SequentialFrame"
            else sorted(slots, key=lambda slot: (slot[2], slot[1], slot[0]))
        )
    for time, z, seq in slots:
        count = 8 if seq % 2 == 0 else 2
        frame_sizes.append(count)
        for _relative in range(count):
            base = 1 + time * 2 + z
            words = [
                0x1000 + base,
                base + 3,
                0x3000 + base + 1,
                0x2000 + base + 4,
                0xA004,
                0xA008,
                0x1000 + base + 5,
                base + 8,
                0x3000 + base + 6,
                0x2000 + base + 9,
            ]
            rows.append(np.array(words, dtype=">u2").tobytes())
    payload = b"".join(rows)
    ends = list(accumulate(map(len, rows)))
    lines = struct.pack("<5Q", 1, len(rows), len(payload), 0, 0)
    lines += b"".join(struct.pack("<2Q", end, 0) for end in ends)
    frame_ends = list(accumulate(frame_sizes))
    if invalid_frames:
        frame_ends[-1] -= 1
    frames = struct.pack("<2Q", 1, len(frame_ends))
    frames += struct.pack(f"<{len(frame_ends)}Q", *frame_ends)
    return payload, lines, frames


def mixed_lif(
    path: Path,
    mode: str = "SequentialFrame",
    sequences: int = 2,
    invalid_frames: bool = False,
    time_fast: bool = False,
) -> Path:
    """Write real records; sequences share routes but own their rows."""
    payload, lines, frames = _indexed_payload(
        mode, sequences, invalid_frames, time_fast
    )
    channel_count = sequences * 2
    values = [8, 4, 1, 2] * ((channel_count + 3) // 4)
    intensity = np.array(
        [
            value
            for _time in range(2)
            for _z in range(2)
            for value in values[:channel_count]
            for _pixel in range(4)
        ],
        dtype="<f4",
    ).tobytes()
    order = (
        ("X", "Y", "C", "Z", "T")
        if mode == "SequentialFrame"
        else ("X", "Y", "Z", "C", "T")
    )
    if time_fast:
        order = (
            ("X", "Y", "C", "T", "Z")
            if mode == "SequentialFrame"
            else ("X", "Y", "T", "Z", "C")
        )
    dimensions = "".join(
        f"<Dimension><DimensionIdentifier>{axis}</DimensionIdentifier>"
        f"<Size>{channel_count if axis == 'C' else 2}</Size></Dimension>"
        for axis in order
    )
    raw = (
        "<RawData><Format>LMSRAW</Format>"
        f"<SequentialMode>{mode}</SequentialMode>"
        f"<Dimensions>{dimensions}</Dimensions>"
        "<Sequence>"
        + "".join(_sequence(index) for index in range(sequences))
        + "</Sequence><Channels>"
        + "".join(_channel(index) for index in range(channel_count))
        + "</Channels></RawData>"
    )
    intensity_xml = (
        "<Image><ImageDescription><Channels>"
        + "".join(
            f'<ChannelDescription BytesInc="{index * 16}"/>'
            for index in range(channel_count)
        )
        + '</Channels><Dimensions><DimensionDescription DimID="1" '
        'NumberOfElements="2" BytesInc="4"/>'
        '<DimensionDescription DimID="2" NumberOfElements="2" BytesInc="8"/>'
        f'<DimensionDescription DimID="3" NumberOfElements="2" '
        f'BytesInc="{channel_count * 16}"/>'
        f'<DimensionDescription DimID="4" NumberOfElements="2" '
        f'BytesInc="{channel_count * 32}"/>'
        "</Dimensions></ImageDescription></Image>"
    )
    blocks = [
        ("FLIM", raw, payload),
        ("Intensity", intensity_xml, intensity),
        ("LineOffsets", "", lines),
        ("FrameOffsets", "", frames),
    ]
    xml = (
        '<LMSDataContainerHeader><Element Name="Project"><Children>'
        '<Element Name="Mixed"><LDM_Block_Sequential_List>'
        + "".join(_optical(index) for index in range(sequences))
        + "</LDM_Block_Sequential_List><Children>"
        + "".join(
            f'<Element Name="{name}">{body}<Memory Size="{len(data)}" '
            f'MemoryBlockID="MemBlock_{index}"/></Element>'
            for index, (name, body, data) in enumerate(blocks, 1)
        )
        + "</Children></Element></Children></Element></LMSDataContainerHeader>"
    ).encode("utf-16le")
    header = struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
    path.write_bytes(
        header
        + xml
        + b"".join(
            _record(index, data)
            for index, (_name, _body, data) in enumerate(blocks, 1)
        )
    )
    return path
