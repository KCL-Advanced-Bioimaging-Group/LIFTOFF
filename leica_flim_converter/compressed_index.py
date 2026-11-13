"""Bounded validation of compressed row descriptors before preview."""

import mmap
import struct

import numpy as np

import lif_flim_forensics as lif


def compressed_index_error(
    data: mmap.mmap, block: lif.MemoryBlock
) -> str | None:
    """Validate the declared index without decompressing image data."""
    if block.declared_size < 64:
        return "Compressed acquisition header is truncated"
    header = struct.unpack_from("<8Q", data, block.data_start)
    stream_start, stream_size, table_size = header[1:4]
    table_start = stream_start + stream_size
    if (
        stream_start < 64
        or table_size % 4
        or table_start + table_size > block.declared_size
    ):
        return "Compressed stream or descriptor table exceeds its memory block"
    values = np.frombuffer(
        data,
        dtype="<u4",
        count=table_size // 4,
        offset=block.data_start + table_start,
    )
    return _descriptor_error(values, header[5], stream_size)


def _descriptor_error(values, expected_rows, stream_size):
    lengths = values & 0x3FFFFFFF
    flags = values >> 30
    if not values.size or not np.any(lengths):
        return (
            "Compressed row descriptor table is empty; "
            "image rows cannot be located"
        )
    starts = np.flatnonzero(flags == 0)
    stops = np.r_[starts[1:], values.size]
    if not starts.size or starts[0] != 0 or np.any(stops - starts < 3):
        return "Compressed descriptor table has a group without row payload"
    if np.any(flags[starts + 1] != 3):
        return "Compressed descriptor table has invalid control flags"
    rows = values.size - 2 * starts.size
    if rows != expected_rows:
        return (
            f"Compressed descriptor table indexes {rows} rows; "
            f"header declares {expected_rows}"
        )
    if int(lengths.sum(dtype=np.uint64)) > stream_size * 8:
        return "Compressed descriptor bit lengths exceed the recorded stream"
    return None
