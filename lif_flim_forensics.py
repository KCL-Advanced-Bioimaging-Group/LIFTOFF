"""Forensic decoder for Leica LAS X LIF files that store FALCON/FLIM
data in LMSDataContainerHeader + MemBlock records.

The script parses the LIF container directly, extracts the UTF-16BE
XML header, maps MemoryBlockID values to payload offsets, exports
directly readable image blocks as OME-TIFF when tifffile is
available, and records Leica-specific FLIM "compressed" blocks as
unresolved binary.
"""

from __future__ import annotations

import gzip
import math
import mmap
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from leica_xml import reject_xml_declarations

LIF_MARKER = b"p\x00\x00\x00"


@dataclass
class MemoryDecl:
    """Represent memory decl."""

    memory_id: str
    size: int


@dataclass
class MemoryBlock:
    """A bounded memory-block descriptor from the LIF container."""

    memory_id: str
    declared_size: int
    record_offset: int
    data_start: int
    data_end: int
    header_bytes: int
    entropy: float
    first16: str


def entropy(data: bytes) -> float:
    """Compute entropy."""
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts if c)


def hex_prefix(data: bytes, n: int = 16) -> str:
    """Compute hex prefix."""
    return " ".join(f"{b:02x}" for b in data[:n])


def parse_attrs(text: str) -> dict[str, str]:
    """Compute parse attrs."""
    return dict(re.findall('([\\w:.-]+)="([^"]*)"', text))


def parse_lif_header(buf: bytes | mmap.mmap) -> tuple[str, int]:
    """Read the bounded Leica XML header across LAS X endian/newline
    variants.
    """
    prefix = buf[12:16]
    encodings = (
        ("utf-16-le", "utf-16-be")
        if prefix.startswith(b"<\x00")
        else ("utf-16-be", "utf-16-le")
    )
    candidates = [
        (encoding, suffix.encode(encoding))
        for encoding in encodings
        for suffix in (
            "</LMSDataContainerHeader>\r\n",
            "</LMSDataContainerHeader>\n",
            "</LMSDataContainerHeader>",
        )
    ]
    xml_end = -1
    encoding = encodings[0]
    close_length = 0
    if len(buf) >= 12:
        declared_end = struct.unpack_from("<I", buf, 4)[0] + 7
        if 12 < declared_end <= len(buf):
            search_end = min(
                len(buf),
                declared_end + max(len(item[1]) for item in candidates),
            )
            for candidate_encoding, close in candidates:
                candidate = buf.rfind(close, 12, search_end)
                if (
                    candidate >= 0
                    and abs(candidate + len(close) - declared_end) <= 64
                ):
                    xml_end, encoding, close_length = (
                        candidate,
                        candidate_encoding,
                        len(close),
                    )
                    break
    if xml_end < 0:
        search_end = min(len(buf), 64 * 1024 * 1024)
        for candidate_encoding, close in candidates:
            candidate = buf.rfind(close, 12, search_end)
            if candidate > xml_end:
                xml_end, encoding, close_length = (
                    candidate,
                    candidate_encoding,
                    len(close),
                )
    if xml_end < 0:
        raise ValueError("Could not find closing LMSDataContainerHeader tag")
    xml_end += close_length
    xml = (buf[12:xml_end]).decode(encoding, errors="replace")
    reject_xml_declarations(xml)
    return (xml, xml_end)


def memory_declarations(xml: str) -> list[MemoryDecl]:
    """Compute memory declarations."""
    decls: list[MemoryDecl] = []
    for match in re.finditer("<Memory\\b([^>]*)/>", xml):
        attrs = parse_attrs(match.group(1))
        if "MemoryBlockID" in attrs:
            decls.append(
                MemoryDecl(attrs["MemoryBlockID"], int(attrs.get("Size", "0")))
            )
    return decls


def read_memblock_id(buf: bytes | mmap.mmap, record_offset: int) -> str | None:
    """Compute read memblock id."""
    for start_delta in range(4, 33):
        start = record_offset + start_delta
        for byteorder in ("little", "big"):
            chars: list[str] = []
            for off in range(start, min(start + 80, len(buf) - 1), 2):
                code = int.from_bytes(buf[off : off + 2], byteorder)
                if code < 32 or code > 126:
                    break
                chars.append(chr(code))
            text = "".join(chars)
            if re.fullmatch("MemBlock_\\d+", text):
                return text
    return None


def locate_memory_blocks(
    buf: bytes, decls: list[MemoryDecl], xml_end: int, strict: bool = True
) -> list[MemoryBlock]:
    """Compute locate memory blocks."""
    markers = [
        xml_end + m.start()
        for m in re.finditer(re.escape(LIF_MARKER), buf[xml_end:])
    ]
    records = {off: read_memblock_id(buf, off) for off in markers}
    by_id = {mid: off for off, mid in records.items() if mid}
    blocks: list[MemoryBlock] = []
    for decl in [d for d in decls if d.size > 0]:
        if decl.memory_id not in by_id:
            if strict:
                raise ValueError(
                    "Declared block "
                    f"{decl.memory_id}"
                    " not found in binary section"
                )
            continue
        off = by_id[decl.memory_id]
        next_offsets = [x for x in markers if x > off]
        next_off = min(next_offsets) if next_offsets else len(buf)
        data_start, data_end = (next_off - decl.size, next_off)
        data = buf[data_start:data_end]
        blocks.append(
            MemoryBlock(
                decl.memory_id,
                decl.size,
                off,
                data_start,
                data_end,
                data_start - off,
                entropy(data),
                hex_prefix(data),
            )
        )
    return blocks


def block_metadata(xml: str, memory_id: str) -> dict[str, Any]:
    """Compute block metadata."""
    idx = xml.find(f'MemoryBlockID="{memory_id}"')
    if idx < 0:
        return {}
    start = xml.rfind("<Element ", 0, idx)
    open_end = xml.find(">", start)
    context = xml[max(0, start) : min(len(xml), idx + 2500)]
    channel = re.search("<ChannelDescription\\b([^>]*)>", context)
    scaling = re.search("<ChannelScalingInfo\\b([^>]*)>", context)
    dims = [
        parse_attrs(m.group(1))
        for m in re.finditer("<DimensionDescription\\b([^>]*)>", context)
    ]
    return {
        "element": parse_attrs(xml[start:open_end])
        if start >= 0 and open_end >= 0
        else {},
        "channel": parse_attrs(channel.group(1)) if channel else {},
        "dimensions": dims,
        "scaling": parse_attrs(scaling.group(1)) if scaling else {},
    }


def dtype_from_meta(meta: dict[str, Any]) -> tuple[str, int, int]:
    """Compute dtype from meta."""
    dims = meta.get("dimensions") or []
    width = int(dims[0]["NumberOfElements"]) if len(dims) > 0 else 0
    height = int(dims[1]["NumberOfElements"]) if len(dims) > 1 else 0
    channel = meta.get("channel") or {}
    resolution = int(channel.get("Resolution", "8"))
    data_type = int(channel.get("DataType", "0"))
    if data_type == 1 and resolution == 32:
        dtype = "float32"
    elif resolution == 32:
        dtype = "uint32"
    elif resolution == 16:
        dtype = "uint16"
    else:
        dtype = "uint8"
    return (dtype, width, height)


def probe_compression(data: bytes) -> dict[str, str]:
    """Compute probe compression."""
    probes = {
        "zlib": zlib.decompress,
        "raw_deflate": lambda x: zlib.decompress(x, -zlib.MAX_WBITS),
        "gzip": gzip.decompress,
    }
    results: dict[str, str] = {}
    for name, fn in probes.items():
        try:
            results[name] = f"ok:{len(fn(data))}"
        except (OSError, EOFError, zlib.error) as exc:
            results[name] = f"fail:{exc}"
    return results


def parse_ptu_tags(path: Path) -> dict[str, Any]:
    """Compute parse ptu tags."""
    buf = path.read_bytes()
    if not buf.startswith(b"PQTTTR"):
        raise ValueError("PTU file does not start with PQTTTR")

    def cstr(raw: bytes) -> str:
        """Compute cstr."""
        return raw.split(b"\x00", 1)[0].decode("latin1", errors="replace")

    off, tags = (16, [])
    while off + 48 <= len(buf):
        ident = cstr(buf[off : off + 32])
        idx = struct.unpack_from("<i", buf, off + 32)[0]
        typ = struct.unpack_from("<I", buf, off + 36)[0]
        raw_val = struct.unpack_from("<q", buf, off + 40)[0]
        value: Any = raw_val
        extra = 0
        if typ in (536870920, 553648136):
            value = struct.unpack_from("<d", buf, off + 40)[0]
        elif typ in (1073872895, 1073938431, 4294967295, 537001983):
            extra = int(raw_val)
            payload = buf[off + 48 : off + 48 + extra]
            value = cstr(payload) if typ == 1073872895 else f"<{extra} bytes>"
        tags.append(
            {
                "ident": ident,
                "idx": idx,
                "type": (f"0x{typ:08x}"),
                "value": value,
            }
        )
        off += 48 + extra
        if ident == "Header_End":
            break
    return {
        "magic": "PQTTTR",
        "tags": tags,
        "data_offset": off,
        "file_size": len(buf),
    }
