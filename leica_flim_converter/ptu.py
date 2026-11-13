"""PicoQuant PTU header and Generic T3 record support.

The Leica reduced stream preserves detector route, pixel position, and
microtime, but not the original hardware macrotime.  This writer
therefore uses a synthetic raster sync clock while retaining every
decoded photon and its native microtime value.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .acquisition_metadata import header_fields, metadata_json
from .data_types import PtuFileInfo, PtuRecordSummary, PtuTag
from .header_metadata import ptu_acquisition_comment
from .raster_timing import RasterTiming
from .spatial_metadata import positive_spacing
from .version import APPLICATION_NAME, APPLICATION_VERSION

TY_EMPTY8 = 4294901768
TY_BOOL8 = 8
TY_INT8 = 268435464
TY_FLOAT8 = 536870920
TY_ANSI_STRING = 1073872895
RT_GENERIC_T3 = 66311
T3_WRAPAROUND = 1024
T3_MAX_DTIME = 32767


def _tag(
    ident: str, value=0, tag_type: int = TY_INT8, index: int = -1
) -> bytes:
    encoded = ident.encode("ascii")
    if len(encoded) > 31:
        raise ValueError(f"PTU tag name is too long: {ident}")
    name = encoded.ljust(32, b"\x00")
    payload = b""
    if tag_type == TY_FLOAT8:
        raw = struct.unpack("<q", struct.pack("<d", float(value)))[0]
    elif tag_type == TY_ANSI_STRING:
        payload = str(value).encode("utf-8") + b"\x00"
        payload += b"\x00" * ((8 - len(payload) % 8) % 8)
        raw = len(payload)
    else:
        raw = int(value)
    return struct.pack("<32siIq", name, index, tag_type, raw) + payload


# Explicit keyword fields mirror the PTU format.
# pylint: disable-next=too-many-arguments
def build_header(
    *,
    filename: str,
    width: int,
    height: int,
    microtime_resolution_s: float,
    sync_rate_hz: int,
    pixel_size_um: float | None,
    input_channels: int,
    record_count: int = 0,
    global_resolution_s: float | None = None,
    timing_quality: str = "Synthetic",
    metadata: dict | None = None,
) -> tuple[bytes, int]:
    """Return a complete PTU header and the record-count value
    offset.
    """
    if width <= 0 or height <= 0:
        raise ValueError("PTU image dimensions must be positive")
    if microtime_resolution_s <= 0 or sync_rate_hz <= 0:
        raise ValueError("PTU timing resolutions must be positive")
    tags: list[tuple[str, bytes]] = []

    def add(name: str, value=0, kind: int = TY_INT8, index: int = -1) -> None:
        """Compute add."""
        tags.append((name, _tag(name, value, kind, index)))

    add("File_GUID", "{" + str(uuid.uuid4()) + "}", TY_ANSI_STRING)
    add("CreatorSW_Name", APPLICATION_NAME, TY_ANSI_STRING)
    add("CreatorSW_Version", APPLICATION_VERSION, TY_ANSI_STRING)
    add(
        "File_Comment",
        (
            ptu_acquisition_comment(metadata, timing_quality)
            if metadata is not None
            else (
                "Decoded Leica FLIM events; raster macrotime is "
                f"{timing_quality.lower()}. See JSON sidecar."
            )
        ),
        TY_ANSI_STRING,
    )
    add("$Filename", filename, TY_ANSI_STRING)
    add("Measurement_Mode", 3)
    add("Measurement_SubMode", 3)
    add("ImgHdr_Dimensions", 3)
    add("ImgHdr_Ident", 3)
    add("ImgHdr_PixX", width)
    add("ImgHdr_PixY", height)
    if positive_spacing(pixel_size_um) is not None:
        add("ImgHdr_PixResol", pixel_size_um, TY_FLOAT8)
    add("ImgHdr_LineStart", 1)
    add("ImgHdr_LineStop", 2)
    add("ImgHdr_Frame", 3)
    add("ImgHdr_BiDirect", 0)
    add("ImgHdr_SinCorrection", 0)
    add(
        "HW_Type",
        f"Generic T3 ({timing_quality.lower()} Leica raster)",
        TY_ANSI_STRING,
    )
    add("Leica_TimingQuality", timing_quality, TY_ANSI_STRING)
    add("HW_InpChannels", max(1, input_channels))
    add("MeasDesc_Resolution", microtime_resolution_s, TY_FLOAT8)
    add(
        "MeasDesc_GlobalResolution",
        global_resolution_s or 1.0 / sync_rate_hz,
        TY_FLOAT8,
    )
    add("TTResult_SyncRate", sync_rate_hz)
    add("TTResult_NumberOfRecords", record_count)
    add("TTResultFormat_TTTRRecType", RT_GENERIC_T3)
    add("TTResultFormat_BitsPerRecord", 32)
    if metadata is not None:
        add("Leica_Acquisition", metadata_json(metadata), TY_ANSI_STRING)
        for name, value in header_fields(metadata).items():
            kind = (
                TY_ANSI_STRING
                if isinstance(value, str)
                else (TY_FLOAT8 if isinstance(value, float) else TY_INT8)
            )
            add(name, value, kind)
    add("Header_End", 0, TY_EMPTY8)
    header = bytearray(b"PQTTTR\x00\x00" + b"1.0\x00\x00\x00\x00\x00")
    count_offset = -1
    for name, encoded_tag in tags:
        if name == "TTResult_NumberOfRecords":
            count_offset = len(header) + 40
        header.extend(encoded_tag)
    if count_offset < 0 or len(header) % 8:
        raise AssertionError("invalid PTU header alignment")
    return (bytes(header), count_offset)


@dataclass
class PtuWriteStats:
    """Counters for emitted photons, markers and overflow wraps."""

    records: int = 0
    photons: int = 0
    overflows: int = 0
    line_markers: int = 0
    frame_markers: int = 0
    primary_photons: int = 0
    reference_photons: int = 0


@dataclass(slots=True)
class VectorEvents:
    """Selected vector columns for one Generic T3 logical line."""

    x: np.ndarray
    microtime: np.ndarray
    channel: np.ndarray | None = None


def _sorted_events(
    events, width: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate and stably sort native microtimes, routes and pixel
    positions.
    """
    if isinstance(events, VectorEvents):
        x = np.asarray(events.x, dtype=np.int64)
        microtime = np.asarray(events.microtime, dtype=np.int64)
        if events.channel is None:
            channel = np.zeros(x.size, dtype=np.int64)
        else:
            channel = np.asarray(events.channel, dtype=np.int64)
    else:
        if isinstance(events, np.ndarray):
            array = np.asarray(events, dtype=np.int64)
        else:
            array = np.asarray(list(events), dtype=np.int64)
        if array.size == 0:
            array = np.empty((0, 3), dtype=np.int64)
        array = array.reshape((-1, 3))
        x, microtime, channel = (array[:, 0], array[:, 1], array[:, 2])
    count = x.size
    if microtime.size != count or channel.size != count:
        raise ValueError("PTU vector event columns have different lengths")
    if count:
        if int(x.min()) < 0 or int(x.max()) >= (width):
            raise ValueError(f"decoded x coordinate is outside width {width}")
        if int(channel.min()) < 0 or int(channel.max()) > 62:
            raise ValueError("PTU input channel is outside Generic T3")
        if int(microtime.min()) < 0 or int(microtime.max()) > 32767:
            raise ValueError(
                "Leica microtime exceeds Generic T3's 15-bit field"
            )
        order = np.lexsort((channel, microtime, x))
        x, microtime, channel = (x[order], microtime[order], channel[order])
    return (x, microtime, channel)


class GenericT3Writer:
    """Streaming Generic T3 writer with compressed overflow records."""

    def __init__(
        self,
        handle: BinaryIO,
        *,
        width: int,
        pixel_ticks: int = 3,
        line_gap_ticks: int = 1,
        timing: RasterTiming | None = None,
    ) -> None:
        if width <= 0 or pixel_ticks <= 0 or line_gap_ticks < 0:
            raise ValueError("invalid synthetic raster dimensions")
        self.handle = handle
        self.width = width
        self.pixel_ticks = pixel_ticks
        self.line_gap_ticks = line_gap_ticks
        self.next_sync = 0
        self.current_wrap = 0
        self.stats = PtuWriteStats()
        self.timing = timing

    def _record(self, value: int) -> None:
        self.handle.write(struct.pack("<I", value & 4294967295))
        self.stats.records += 1

    def _at_sync(self, sync: int) -> int:
        wanted = sync // T3_WRAPAROUND
        remaining = wanted - self.current_wrap
        while remaining > 0:
            count = min(remaining, 1023)
            self._record(1 << 31 | 63 << 25 | count)
            self.stats.overflows += count
            self.current_wrap += count
            remaining -= count
        return sync & 1023

    def marker(self, marker_number: int, sync: int) -> None:
        """Compute marker."""
        if not 1 <= marker_number <= 4:
            raise ValueError("PTU marker number must be 1-4")
        marker_bits = 1 << marker_number - 1
        nsync = self._at_sync(sync)
        self._record(1 << 31 | marker_bits << 25 | nsync)

    def photon(self, channel: int, microtime: int, sync: int) -> None:
        """Compute photon."""
        if not 0 <= channel <= 62:
            raise ValueError(
                f"PTU input channel is outside Generic T3: {channel}"
            )
        if not 0 <= microtime <= T3_MAX_DTIME:
            raise ValueError(
                "Leica microtime "
                f"{microtime}"
                " exceeds Generic T3's 15-bit field"
            )
        nsync = self._at_sync(sync)
        self._record(channel << 25 | microtime << 10 | nsync)
        self.stats.photons += 1
        if channel == 1:
            self.stats.reference_photons += 1
        else:
            self.stats.primary_photons += 1

    def write_line(self, events, *, frame_start=False, frame=0, y=0):
        """Compute write line."""
        start = self.next_sync
        x, microtime, channel = _sorted_events(events, self.width)
        positions = None
        reconstructed_stop = 0
        if self.timing is not None and self.timing.quality == "Reconstructed":
            start, positions, reconstructed_stop = self.timing.positions(
                frame, y, x, self.width
            )
        count = x.size
        prefix = 2 if frame_start else 1
        item_count = prefix + count + 1
        syncs = np.empty(item_count, dtype=np.uint64)
        records = np.empty(item_count, dtype=np.uint32)
        cursor = 0

        def add_marker(marker_number, sync):
            """Compute add marker."""
            nonlocal cursor
            syncs[cursor] = sync
            marker_bits = 1 << marker_number - 1
            records[cursor] = np.uint32(
                2147483648 | marker_bits << 25 | sync & 1023
            )
            cursor += 1

        if frame_start:
            add_marker(3, start)
        add_marker(1, start)
        if count:
            photon_sync = (
                start
                + 1
                + x.astype(np.uint64, copy=False) * (self.pixel_ticks)
            )
            if positions is not None:
                photon_sync = positions
            syncs[cursor : cursor + count] = photon_sync
            encoded = (
                channel.astype(np.uint32, copy=False) << np.uint32(25)
                | microtime.astype(np.uint32, copy=False) << np.uint32(10)
                | photon_sync.astype(np.uint32, copy=False) & np.uint32(1023)
            )
            records[cursor : cursor + count] = encoded
            cursor += count
        stop = start + 1 + (self.width) * (self.pixel_ticks)
        if positions is not None:
            stop = reconstructed_stop
        add_marker(2, stop)
        self._write_with_overflows(syncs, records)
        self.next_sync = stop + (self.line_gap_ticks)
        self.stats.photons += count
        if count:
            reference = int(np.count_nonzero(channel == 1))
            self.stats.reference_photons += reference
            self.stats.primary_photons += count - reference
        self.stats.line_markers += 2
        if frame_start:
            self.stats.frame_markers += 1

    def _write_with_overflows(
        self, syncs: np.ndarray, records: np.ndarray
    ) -> None:
        """Insert counted overflow records while retaining stable record
        order.
        """
        item_count = records.size
        wraps = (syncs // np.uint64(1024)).astype(np.int64, copy=False)
        previous_wraps = np.empty(item_count, dtype=np.int64)
        previous_wraps[0] = self.current_wrap
        previous_wraps[1:] = wraps[:-1]
        deltas = wraps - previous_wraps
        if bool(np.any(deltas < 0)):
            raise ValueError("PTU synthetic macrotime moved backwards")
        overflow_slots = (deltas + 1022) // 1023
        positions = np.arange(item_count, dtype=np.int64) + np.cumsum(
            overflow_slots, dtype=np.int64
        )
        output = np.empty(
            item_count + int(overflow_slots.sum()), dtype=np.uint32
        )
        output[positions] = records
        for index in np.flatnonzero(overflow_slots):
            remaining = int(deltas[index])
            write_at = int(positions[index] - overflow_slots[index])
            while remaining > 0:
                represented = min(remaining, 1023)
                output[write_at] = np.uint32(4261412864 | represented)
                write_at += 1
                remaining -= represented
        self.handle.write(output.astype("<u4", copy=False).tobytes())
        self.current_wrap = int(wraps[-1])
        self.stats.records += output.size
        self.stats.overflows += int(deltas.sum())


def _read_records(handle: BinaryIO, tags: list[PtuTag]) -> PtuRecordSummary:
    """Count Generic T3 records and reject truncation or trailing
    bytes.
    """
    values = {tag["ident"]: tag["value"] for tag in tags}
    count = int(values["TTResult_NumberOfRecords"])
    photons = markers = overflow_records = overflow_wraps = 0
    channels: dict[int, int] = {}
    marker_bits: dict[int, int] = {}
    for _ in range(count):
        raw_record = handle.read(4)
        if len(raw_record) != 4:
            raise ValueError("truncated PTU record array")
        record = struct.unpack("<I", raw_record)[0]
        special, channel = (record >> 31, record >> 25 & 63)
        if not special:
            photons += 1
            channels[channel] = channels.get(channel, 0) + 1
        elif channel == 63:
            overflow_records += 1
            overflow_wraps += record & 1023 or 1
        else:
            markers += 1
            marker_bits[channel] = marker_bits.get(channel, 0) + 1
    if handle.read(1):
        raise ValueError("PTU has trailing bytes beyond declared records")
    return {
        "count": count,
        "photons": photons,
        "markers": markers,
        "overflowRecords": overflow_records,
        "overflowWraps": overflow_wraps,
        "channels": channels,
        "markerBits": marker_bits,
    }


def parse_ptu(path: str | Path, *, parse_records: bool = False) -> PtuFileInfo:
    """Independent structural reader used by tests and release
    validation.
    """
    source = Path(path)
    tags: list[PtuTag] = []
    with source.open("rb") as handle:
        if handle.read(8) != b"PQTTTR\x00\x00":
            raise ValueError("not a PTU file")
        version = (
            handle.read(8).split(b"\x00", 1)[0].decode("ascii", "replace")
        )
        while True:
            raw = handle.read(48)
            if len(raw) != 48:
                raise ValueError("truncated PTU header")
            ident_raw, index, kind, value = struct.unpack("<32siIq", raw)
            ident = ident_raw.split(b"\x00", 1)[0].decode("ascii", "replace")
            decoded: int | float | str = value
            if kind == TY_FLOAT8:
                decoded = struct.unpack("<d", struct.pack("<q", value))[0]
            elif kind == TY_ANSI_STRING:
                payload = handle.read(value)
                if len(payload) != value:
                    raise ValueError("truncated PTU string tag")
                decoded = payload.split(b"\x00", 1)[0].decode(
                    "utf-8", "replace"
                )
            tags.append(
                {
                    "ident": ident,
                    "index": index,
                    "type": kind,
                    "value": decoded,
                }
            )
            if ident == "Header_End":
                break
        data_offset = handle.tell()
        result: PtuFileInfo = {
            "version": version,
            "tags": tags,
            "dataOffset": data_offset,
            "fileSize": source.stat().st_size,
        }
        if parse_records:
            result["records"] = _read_records(handle, tags)
    return result
