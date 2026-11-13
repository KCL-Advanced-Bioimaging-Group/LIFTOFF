"""Bounded selected photon rows shared by both scientific exports."""

from __future__ import annotations

import mmap
from collections.abc import Callable

import numpy as np

import patent_guided_deflate_attack as codec

from .dataset import DatasetInfo
from .event_flags import (
    PRIMARY_EVENT_FLAGS,
    RAW_ALL_PHOTONS,
    markers_from_mask,
)
from .histogram_core import DecodeCancelled
from .photon_selection import dead_time_info, plane_starts, select_raw_vectors
from .raw_decoder import RawPreparedDecoder

CancelCheck = Callable[[], bool]


class PhotonStreamCancelled(DecodeCancelled):
    """A bounded photon stream stopped at the user's request."""


def _compressed_rows(
    dataset: DatasetInfo,
    first_row: int,
    row_count: int,
    consume: Callable[[int, list[tuple[int, int, int]]], None],
    report: Callable[[str], None],
    cancelled: CancelCheck,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
) -> int:
    with dataset.source.open("rb") as handle:
        handle.seek(dataset.block_start)
        data = handle.read(dataset.block_end - dataset.block_start)
    _header, stream, lengths, flags = codec.load_container_bytes(data)
    seen = 0

    def row_callback(row: dict) -> None:
        """Compute row callback."""
        nonlocal seen
        if cancelled():
            raise PhotonStreamCancelled("PTU export cancelled")
        line = int(row["line"])
        if first_row <= line < first_row + row_count:
            events = [
                (x, dt, 1 if marker & 0xF8 == 184 else 0)
                for _line, x, dt, marker in codec.iter_event_tuples(
                    [row],
                    set(
                        markers_from_mask(
                            event_flag_mask, dataset.detector_route
                        )
                    ),
                )
            ]
            consume(line, events)
            seen += 1
            update_interval = max(64, row_count // 200)
            if seen % update_interval == 0:
                report(f"Decoding PTU events: {seen}/{row_count} rows")

    _rows, _groups, errors, _consumed = codec.decode_descriptor_rows(
        stream,
        lengths,
        flags,
        row_callback=row_callback,
        keep_rows=False,
        row_range=(first_row, row_count),
    )
    if errors or seen != row_count:
        raise RuntimeError(
            "Incomplete PTU event decode: "
            f"{seen}"
            "/"
            f"{row_count}"
            " rows; "
            f"{errors[:3]}"
        )
    return seen


def iter_lmsraw_vectors(dataset, first_row, row_count, mode, cancelled):
    """Compute iter lmsraw vectors."""
    threshold = (
        int(dead_time_info(dataset)["minimumSubsequentArrivalDeltaBins"])
        if mode == RAW_ALL_PHOTONS
        else 0
    )
    state = [False, 0]
    starts = plane_starts(dataset)
    with (
        RawPreparedDecoder(dataset) as prepared,
        dataset.source.open("rb") as handle,
    ):
        mapped = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for relative in range(row_count):
                if cancelled():
                    raise PhotonStreamCancelled("PTU export cancelled")
                line = first_row + relative
                if relative == 0 or line in starts:
                    state[:] = [False, 0]
                start = 0 if line == 0 else int(prepared.ends[line - 1])
                end = int(prepared.ends[line])
                if start > end or end - start & 1:
                    raise RuntimeError(f"Invalid LMSRAW photon row {line}")
                view = memoryview(mapped)[
                    dataset.block_start + start : dataset.block_start + end
                ]
                words = np.frombuffer(view, dtype=">u2")
                x, microtime = select_raw_vectors(
                    words, dataset, mode, state, threshold
                )
                del words, view
                yield (line, x, microtime)
        finally:
            mapped.close()
