"""Strict indexed LMSRAW reader and bounded byte batches."""

from __future__ import annotations

import struct

import numpy as np

from .histogram_core import DecodeCancelled
from .linked_intensity import read_intensity_plane


class RawPreparedReader:
    """Hold the compact row table while reading only requested photon
    rows.
    """

    def __init__(self, dataset) -> None:
        if dataset.storage_format != "lmsraw":
            raise ValueError("RawPreparedDecoder requires an LMSRAW dataset")
        if dataset.detector_data_type not in (None, "PulseVersion2"):
            raise RuntimeError(
                "Unsupported LMSRAW detector data type: "
                f"{dataset.detector_data_type}"
            )
        if not 1 <= dataset.detector_route_count <= 4:
            raise RuntimeError(
                "PulseVersion2 supports 1-4 detector routes, found"
                " "
                f"{dataset.detector_route_count}"
            )
        if not 0 <= dataset.detector_route < dataset.detector_route_count:
            raise RuntimeError(
                "LMSRAW detector index is outside the channel dimension"
            )
        if dataset.line_offsets_start is None:
            raise RuntimeError("LMSRAW block has no linked LineOffsets table")
        self.dataset = dataset
        with dataset.source.open("rb") as handle:
            handle.seek(dataset.line_offsets_start)
            header = handle.read(40)
            if len(header) != 40:
                raise RuntimeError("Truncated LMSRAW LineOffsets header")
            version, row_count, payload_size, reserved_a, reserved_b = (
                struct.unpack("<5Q", header)
            )
            if (
                version != 1
                or row_count != dataset.decoded_rows
                or payload_size != dataset.compressed_bytes
                or reserved_a
                or reserved_b
            ):
                raise RuntimeError("Invalid LMSRAW LineOffsets header")
            table = handle.read(row_count * 16)
        if len(table) != row_count * 16:
            raise RuntimeError("Truncated LMSRAW LineOffsets table")
        stored = np.frombuffer(table, dtype="<u8").reshape(row_count, 2)
        if np.any(stored[:, 1]):
            raise RuntimeError("Unsupported nonzero LMSRAW line-offset flags")
        self.ends = np.empty(row_count, dtype=np.uint64)
        self.ends[:-1] = stored[:-1, 0]
        self.ends[-1] = payload_size
        if (
            np.any(self.ends == 0)
            or np.any(self.ends[1:] <= self.ends[:-1])
            or int(self.ends[-1]) != dataset.compressed_bytes
        ):
            raise RuntimeError("Invalid or non-monotonic LMSRAW line offsets")

    def close(self) -> None:
        """Release owned native handles and mapped source resources."""

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def _plane_rows(self, linear_plane: int) -> tuple[int, int]:
        return self.dataset.plane_row_range(linear_plane)

    def reference_events(self, linear_plane: int | None) -> int | None:
        """Reference events."""
        if linear_plane is None:
            return self.dataset.total_photons
        values = read_intensity_plane(self.dataset, linear_plane)
        if values is None:
            return None
        return int(np.rint(values).astype(np.uint64).sum())

    def iter_batches(
        self, handle, first_row: int, row_count: int, cancelled=None
    ):
        """Read consecutive rows in bounded batches, including on
        network shares.
        """
        limit = first_row + row_count
        row = first_row
        while row < limit:
            if cancelled and cancelled():
                raise DecodeCancelled("LMSRAW histogram decode cancelled")
            start = 0 if row == 0 else int(self.ends[row - 1])
            stop = min(
                limit,
                max(
                    row + 1,
                    int(
                        np.searchsorted(
                            self.ends, start + 8 * 1024 * 1024, side="right"
                        )
                    ),
                ),
            )
            end = int(self.ends[stop - 1])
            handle.seek(self.dataset.block_start + start)
            block = handle.read(end - start)
            if len(block) != end - start:
                raise RuntimeError(
                    f"Truncated LMSRAW photon batch at row {row}"
                )
            yield (row, stop, start, block)
            row = stop

    def iter_rows(
        self, handle, first_row: int, row_count: int, cancelled=None
    ):
        """Compute iter rows."""
        for row, stop, start, block in self.iter_batches(
            handle, first_row, row_count, cancelled
        ):
            view = memoryview(block)
            while row < stop:
                if cancelled and cancelled():
                    raise DecodeCancelled("LMSRAW histogram decode cancelled")
                row_start = 0 if row == 0 else int(self.ends[row - 1])
                row_end = int(self.ends[row])
                if (row_end - row_start) % 2:
                    raise RuntimeError(f"Unaligned LMSRAW photon row {row}")
                yield (row, view[row_start - start : row_end - start])
                row += 1
