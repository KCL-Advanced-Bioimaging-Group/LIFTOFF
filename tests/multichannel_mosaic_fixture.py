"""Literal LMSRAW mosaics with independent sequence and tile axes."""

import math
import struct
from dataclasses import dataclass
from itertools import accumulate, product
from pathlib import Path

import numpy as np

from tests.sequence_fixture import _record  # pylint: disable=protected-access


@dataclass(frozen=True)
class MosaicSpec:
    """Two light sources, two detectors each, and S/T/Z axes."""

    columns: int = 2
    rows: int = 2
    width: int = 7
    height: int = 5
    times: int = 2
    depths: int = 2
    mode: str = "SequentialFrame"

    @property
    def cells(self) -> list[tuple[int, int]]:
        """Store tiles in a snake path."""
        return [
            (column, row)
            for row in range(self.rows)
            for column in (
                range(self.columns)
                if row % 2 == 0
                else reversed(range(self.columns))
            )
        ]

    @property
    def axes(self) -> tuple[str, ...]:
        """Frame and stack sequencing exchange the Z/Q nesting."""
        return (
            ("X", "Y", "C", "Z", "S", "T")
            if self.mode == "SequentialFrame"
            else ("X", "Y", "Z", "C", "S", "T")
        )

    @staticmethod
    def clock(sequence: int) -> float:
        """Use independent native clocks."""
        return (9.696969697e-11, 2e-10)[sequence]

    @staticmethod
    def frequency(sequence: int) -> float:
        """Use the two laser periods from the supplied examples."""
        return (78.02e6, 80e6)[sequence]


def pixel_cycles(identity, x, y, width):
    """Return literal arrival cycles with spatial variation."""
    time, stage, depth, sequence, route = identity
    base = (
        2
        + 2 * stage
        + time
        + 2 * depth
        + 3 * sequence
        + route
        + (2 * x + y) % 5
    )
    extra = (x + 2 * y + time + depth + sequence + route) % 2
    return (
        (base, base + 6) if extra else (base,),
        (base + 12, base + 18) if x == width - 1 else (base + 12,),
    )


def expected_cube(spec: MosaicSpec, identity: tuple[int, ...], mask=256):
    """Compute an oracle directly from the invented photon cycles."""
    sequence = identity[3]
    bins = math.ceil(1 / spec.frequency(sequence) / spec.clock(sequence))
    cube = np.zeros((bins, spec.height, spec.width), dtype=np.uint32)
    repetitions = (2 + sequence) * (2 if sequence == 0 else 1)
    for y, x in product(range(spec.height), range(spec.width)):
        for cycle in pixel_cycles(identity, x, y, spec.width):
            arrivals = (
                cycle
                if mask == 256
                else cycle[:1]
                if mask == 512
                else cycle
                if len(cycle) == 1
                else ()
            )
            for arrival in arrivals:
                cube[arrival, y, x] += repetitions
    return cube


def _row(spec, time, stage, depth, sequence, y):
    words = []
    for x in range(spec.width):
        for route in range(2):
            identity = time, stage, depth, sequence, route
            for cycle in pixel_cycles(identity, x, y, spec.width):
                words.extend(
                    ((2 * route + int(index == 0)) << 12) | arrival
                    for index, arrival in enumerate(cycle)
                )
        words.extend((0xA004, 0xA008))
    return np.asarray(words, dtype=">u2").tobytes()


def _payload(spec):
    rows, frames = [], []
    stages = len(spec.cells)
    slots = (
        product(range(spec.times), range(stages), range(spec.depths), range(2))
        if spec.mode == "SequentialFrame"
        else (
            (time, stage, depth, sequence)
            for time, stage, sequence, depth in product(
                range(spec.times), range(stages), range(2), range(spec.depths)
            )
        )
    )
    for time, stage, depth, sequence in slots:
        for _frame in range(2 + sequence):
            for y in range(spec.height):
                row = _row(spec, time, stage, depth, sequence, y)
                rows.extend([row] * (2 if sequence == 0 else 1))
        frames.append(len(rows))
    photons = b"".join(rows)
    ends = list(accumulate(map(len, rows)))
    lines = struct.pack("<5Q", 1, len(ends), len(photons), 0, 0)
    lines += b"".join(struct.pack("<2Q", end, 0) for end in ends)
    frame_table = struct.pack("<2Q", 1, len(frames)) + struct.pack(
        f"<{len(frames)}Q", *frames
    )
    return photons, lines, frame_table


def _sequence(spec, sequence):
    return (
        "<SequenceItem><HasRawData>true</HasRawData>"
        f"<ClockPeriod>{spec.clock(sequence)}</ClockPeriod>"
        f"<FrameRepetitions>{2 + sequence}</FrameRepetitions>"
        f"<LineRepetitions>{2 if sequence == 0 else 1}</LineRepetitions>"
        "<Detectors>"
        + "".join(
            f"<Detectors><Detector>{route}</Detector>"
            f"<Identifier>{(3 if sequence == 0 else 1001) + route}"
            "</Identifier>"
            f"<Name>HyD {'X' if sequence == 0 else 'NDD'} {route + 1}</Name>"
            f"<Excitation>{5.55e-7 if sequence == 0 else 0}</Excitation>"
            f"<LaserPulseFrequency>{spec.frequency(sequence)}"
            "</LaserPulseFrequency>"
            "<DeadTime>4e-10</DeadTime><DataType>PulseVersion2</DataType>"
            "</Detectors>"
            for route in range(2)
        )
        + "</Detectors></SequenceItem>"
    )


def _raw(spec):
    sizes = {
        "X": spec.width,
        "Y": spec.height,
        "C": 4,
        "Z": spec.depths,
        "S": len(spec.cells),
        "T": spec.times,
    }
    dimensions = "".join(
        f"<Dimension><DimensionIdentifier>{axis}</DimensionIdentifier>"
        f"<Size>{sizes[axis]}</Size></Dimension>"
        for axis in spec.axes
    )
    channels = "".join(
        "<Channel><Detectors><DetectorReferences>"
        f"<SequenceItemIndex>{sequence}</SequenceItemIndex>"
        f"<DetectorIndex>{route}</DetectorIndex>"
        "</DetectorReferences></Detectors></Channel>"
        for sequence, route in product(range(2), range(2))
    )
    stages = "".join(
        f"<StagePositions><X>{column * 1e-5}</X><Y>{row * 1e-5}</Y>"
        "<Z>0</Z></StagePositions>"
        for column, row in spec.cells
    )
    return (
        "<RawData><Format>LMSRAW</Format>"
        "<VoxelSizeX>1e-6</VoxelSizeX><VoxelSizeY>1e-6</VoxelSizeY>"
        f"<SequentialMode>{spec.mode}</SequentialMode>"
        f"<Dimensions>{dimensions}</Dimensions><Channels>{channels}</Channels>"
        "<Sequence>"
        + _sequence(spec, 0)
        + _sequence(spec, 1)
        + "</Sequence></RawData>"
        + stages
    )


def _image(spec):
    plane_bytes = spec.width * spec.height * 4
    sizes = (
        (1, spec.width, 4),
        (2, spec.height, spec.width * 4),
        (3, spec.depths, plane_bytes * 4),
        (10, len(spec.cells), plane_bytes * 4 * spec.depths),
        (4, spec.times, plane_bytes * 4 * spec.depths * len(spec.cells)),
    )
    dimensions = "".join(
        f'<DimensionDescription DimID="{axis}" NumberOfElements="{size}" '
        f'BytesInc="{stride}"/>'
        for axis, size, stride in sizes
    )
    tiles = "".join(
        f'<Tile FieldX="{column}" FieldY="{row}" PosX="{column * 1e-5}" '
        f'PosY="{row * 1e-5}" PosZ="0"/>'
        for row, column in product(range(spec.rows), range(spec.columns))
    )
    return (
        "<Image><ImageDescription><Channels>"
        + "".join(
            f'<ChannelDescription BytesInc="{index * plane_bytes}"/>'
            for index in range(4)
        )
        + f"</Channels><Dimensions>{dimensions}</Dimensions>"
        "</ImageDescription>"
        '<Attachment Name="TileScanInfo" FlipX="0" FlipY="0" SwapXY="0">'
        + tiles
        + "</Attachment></Image>"
    )


def _optics():
    settings = []
    for sequence, (wavelength, source, name) in enumerate(
        ((555, "SuperContVisible Light", "WLL"), (740, "MP1", "MP"))
    ):
        settings.append(
            '<ATLConfocalSettingDefinition IsEnabledForScanning="1" '
            f'UserSettingName="Synthetic {name}">'
            + "".join(
                f'<Detector Channel="{(3 if sequence == 0 else 1001) + route}"'
                ' IsActive="1"/>'
                "<MultiBand "
                f'Channel="{(3 if sequence == 0 else 1001) + route}" '
                f'LeftWorld="{565 + 50 * route - sequence * 100}" '
                f'RightWorld="{630 + 50 * route - sequence * 100}"/>'
                for route in range(2)
            )
            + f'<Aotf LightSourceName="{source}">'
            f'<LaserLineSetting LaserLine="{wavelength}" '
            'IntensityDev="5"/></Aotf>'
            f'<Laser LightSourceName="{source}" LaserName="{name}"/>'
            "</ATLConfocalSettingDefinition>"
        )
    return (
        "<LDM_Block_Sequential_List>"
        + "".join(settings)
        + "</LDM_Block_Sequential_List>"
    )


def multichannel_mosaic_lif(
    path: Path, spec: MosaicSpec | None = None
) -> Path:
    """Write LIF records, offset tables, and linked intensities."""
    spec = spec or MosaicSpec()
    photons, lines, frames = _payload(spec)
    intensity = b"".join(
        expected_cube(spec, (time, stage, depth, sequence, route))
        .sum(axis=0)
        .astype("<f4")
        .tobytes()
        for time, stage, depth, sequence, route in product(
            range(spec.times),
            range(len(spec.cells)),
            range(spec.depths),
            range(2),
            range(2),
        )
    )
    image = _image(spec)
    blocks = (
        ("FLIM", _raw(spec), photons),
        ("Intensity", image, intensity),
        ("LineOffsets", "", lines),
        ("FrameOffsets", "", frames),
    )
    children = "".join(
        f'<Element Name="{name}"><Data>{body}</Data>'
        f'<Memory Size="{len(payload)}" MemoryBlockID="MemBlock_{index}"/>'
        "</Element>"
        for index, (name, body, payload) in enumerate(blocks, 1)
    )
    xml = (
        "<LMSDataContainerHeader>"
        '<Element Name="Synthetic multichannel mosaic">'
        f"<Data>{image}{_optics()}</Data><Children>{children}</Children>"
        "</Element></LMSDataContainerHeader>"
    ).encode("utf-16le")
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + b"".join(
            _record(index, payload)
            for index, (_name, _body, payload) in enumerate(blocks, 1)
        )
    )
    return path
