"""Sparse Leica MemBlock indexing and bounded fallback."""

from __future__ import annotations

import mmap
import re
import struct
from bisect import bisect_right
from collections.abc import Callable

import lif_flim_forensics as lif

IndexProgress = Callable[[str], None]
CancelCheck = Callable[[], bool]


class IndexCancelledError(RuntimeError):
    """Represent index cancelled error."""


def _locate_blocks_linear(
    data: mmap.mmap, declarations: list[lif.MemoryDecl], xml_end: int
) -> list[lif.MemoryBlock]:
    """Legacy O(file-size) marker scan retained only as an explicit
    fallback.
    """
    markers: list[int] = []
    offset = data.find(lif.LIF_MARKER, xml_end)
    while offset >= 0:
        markers.append(offset)
        offset = data.find(lif.LIF_MARKER, offset + len(lif.LIF_MARKER))
    by_id = {}
    record_offsets = []
    for offset in markers:
        memory_id = lif.read_memblock_id(data, offset)
        if memory_id:
            by_id[memory_id] = offset
            record_offsets.append(offset)
    record_offsets = sorted(set(record_offsets))
    blocks = []
    for declaration in declarations:
        if declaration.size <= 0 or declaration.memory_id not in by_id:
            continue
        record_offset = by_id[declaration.memory_id]
        marker_index = bisect_right(record_offsets, record_offset)
        next_offset = (
            record_offsets[marker_index]
            if marker_index < len(record_offsets)
            else len(data)
        )
        data_start = next_offset - declaration.size
        blocks.append(
            lif.MemoryBlock(
                declaration.memory_id,
                declaration.size,
                record_offset,
                data_start,
                next_offset,
                data_start - record_offset,
                0.0,
                (data[data_start : data_start + 16]).hex(" "),
            )
        )
    return blocks


def _parse_memblock_record(
    data: mmap.mmap, offset: int
) -> tuple[str, int, int] | None:
    """Return memory ID, payload size, and payload offset for a Leica
    record.
    """
    if (
        offset < 0
        or offset + 22 > len(data)
        or data[offset : offset + 4] != lif.LIF_MARKER
    ):
        return None
    fixed = data[offset : offset + 22]
    header_tail = struct.unpack_from("<I", fixed, 4)[0]
    if fixed[8] != 42 or fixed[17] != 42:
        return None
    payload_size = struct.unpack_from("<Q", fixed, 9)[0]
    character_count = struct.unpack_from("<I", fixed, 18)[0]
    header_bytes = 22 + character_count * 2
    if (
        not 1 <= character_count <= 128
        or header_tail + 8 != header_bytes
        or offset + header_bytes > len(data)
    ):
        return None
    raw_name = data[offset + 22 : offset + header_bytes]
    for encoding in ("utf-16-le", "utf-16-be"):
        try:
            memory_id = raw_name.decode(encoding)
        except UnicodeDecodeError:
            continue
        if re.fullmatch("MemBlock_\\d+", memory_id):
            return (memory_id, int(payload_size), offset + header_bytes)
    return None


def _next_valid_record(
    data: mmap.mmap, start: int, end: int, cancelled: CancelCheck
) -> tuple[int, tuple[str, int, int]] | None:
    cursor = max(0, start)
    limit = min(len(data), end)
    while cursor < limit:
        if cancelled():
            raise IndexCancelled("LIF indexing cancelled")
        marker = data.find(lif.LIF_MARKER, cursor, limit)
        if marker < 0:
            return None
        parsed = _parse_memblock_record(data, marker)
        if parsed is not None:
            return (marker, parsed)
        cursor = marker + len(lif.LIF_MARKER)
    return None


def _locate_blocks_sparse(
    data: mmap.mmap,
    declarations: list[lif.MemoryDecl],
    xml_end: int,
    progress: IndexProgress | None = None,
    cancelled: CancelCheck | None = None,
) -> list[lif.MemoryBlock]:
    """Index MemBlocks by seeking over declared payloads, independent of
    file size.
    """
    report = progress or (lambda _message: None)
    is_cancelled = cancelled or (lambda: False)
    declarations_by_id = {
        item.memory_id: item for item in declarations if item.size > 0
    }
    first = _next_valid_record(
        data, xml_end, min(len(data), xml_end + 8 * 1024 * 1024), is_cancelled
    )
    if first is None:
        raise ValueError(
            "No valid Leica MemBlock record found after the XML header"
        )
    blocks: list[lif.MemoryBlock] = []
    seen: set[str] = set()
    record_offset, parsed = first
    while parsed is not None:
        if is_cancelled():
            raise IndexCancelled("LIF indexing cancelled")
        memory_id, embedded_size, data_start = parsed
        data_end = data_start + embedded_size
        if data_end > len(data):
            raise ValueError(
                "Truncated Leica record "
                f"{memory_id}"
                ": payload ends at "
                f"{data_end:,}"
                ", file has "
                f"{len(data):,}"
                " bytes"
            )
        declaration = declarations_by_id.get(memory_id)
        if declaration is not None:
            if declaration.size != embedded_size:
                raise ValueError(
                    "Leica record "
                    f"{memory_id}"
                    " size mismatch: XML "
                    f"{declaration.size:,}"
                    ", record "
                    f"{embedded_size:,}"
                )
            blocks.append(
                lif.MemoryBlock(
                    memory_id,
                    embedded_size,
                    record_offset,
                    data_start,
                    data_end,
                    data_start - record_offset,
                    0.0,
                    (data[data_start : min(data_start + 16, data_end)]).hex(
                        " "
                    ),
                )
            )
            seen.add(memory_id)
        report(
            "Indexed "
            f"{len(blocks)}"
            " blocks; reached "
            f"{data_end / 1024**3:.2f}"
            " GiB"
        )
        if data_end == len(data):
            break
        following = _next_valid_record(
            data,
            data_end,
            min(len(data), data_end + 8 * 1024 * 1024),
            is_cancelled,
        )
        if following is None:
            if len(data) - data_end <= 8 * 1024 * 1024:
                break
            raise ValueError(
                "Could not parse the MemBlock record after "
                f"{memory_id}"
                " at "
                f"{data_end:,}"
                "; refusing an unbounded payload scan"
            )
        record_offset, parsed = following
    missing = [
        item.memory_id
        for item in declarations
        if item.size > 0 and item.memory_id not in seen
    ]
    if missing:
        raise ValueError(
            f"Declared Leica blocks were not indexed: {', '.join(missing[:5])}"
        )
    return blocks


def _locate_blocks_mapped(
    data: mmap.mmap,
    declarations: list[lif.MemoryDecl],
    xml_end: int,
    progress: IndexProgress | None = None,
    cancelled: CancelCheck | None = None,
    allow_linear_fallback: bool = False,
) -> list[lif.MemoryBlock]:
    """Use sparse indexing; optionally allow the legacy full scan for
    small files.
    """
    try:
        return _locate_blocks_sparse(
            data, declarations, xml_end, progress, cancelled
        )
    except (OSError, ValueError, OverflowError, struct.error) as exc:
        if not allow_linear_fallback:
            raise
        if len(data) > 2 * 1024**3:
            raise ValueError(
                "Sparse LIF indexing failed ("
                f"{exc}"
                "); linear fallback is disabled above 2 GiB to "
                "prevent a prolonged payload scan"
            ) from exc
        return _locate_blocks_linear(data, declarations, xml_end)


IndexCancelled = IndexCancelledError
