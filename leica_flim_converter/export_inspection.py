"""Independent readers for scientific export regression evidence."""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .ptu import parse_ptu


@dataclass(frozen=True)
class IcsImage:
    """An independently decoded ICS header and calibrated count
    array.
    """

    counts: NDArray[np.uint16 | np.uint32]
    header: dict[str, list[str]]


def read_ics(path: Path) -> IcsImage:
    """Read ICS v2 payload orientation independently of the writer."""
    header: dict[str, list[str]] = {}
    with path.open("rb") as stream:
        while True:
            raw = stream.readline()
            if not raw:
                raise ValueError("Truncated ICS header")
            fields = raw.decode("ascii").rstrip("\r\n").split("\t")
            if fields[0] == "end":
                break
            if len(fields) > 2:
                header[f"{fields[0]}/{fields[1]}"] = fields[2:]
        payload = stream.read()
    order = header["layout/order"]
    if (
        len(order) != 4
        or order[0] != "bits"
        or set(order[1:]) != {"x", "y", "t"}
    ):
        raise ValueError("Unsupported ICS axis order")
    bits, *sizes = map(int, header["layout/sizes"])
    if bits not in (16, 32):
        raise ValueError("Unsupported ICS integer size")
    if header["representation/compression"] == ["gzip"]:
        payload = gzip.decompress(payload)
    expected = int(np.prod(sizes)) * (bits // 8)
    if len(payload) != expected:
        raise ValueError("ICS payload length does not match its header")
    counts = np.frombuffer(payload, dtype="<u2" if bits == 16 else "<u4")
    storage_axes = list(reversed(order[1:]))
    counts = (
        counts.reshape(tuple(reversed(sizes)))
        .transpose(*(storage_axes.index(axis) for axis in ("t", "y", "x")))
        .copy()
    )
    return IcsImage(counts, header)


@dataclass(frozen=True)
class PtuScience:
    """Full photon, route, marker, overflow, and microtime evidence."""

    records: int
    photons: int
    record_sha256: str
    microtime: NDArray[np.uint64]
    routes: dict[int, int]
    markers: dict[int, int]
    overflow_records: int
    overflow_wraps: int
    monotonic_macrotime: bool
    record_type: int

    def metadata(self) -> dict:
        """Return portable evidence with only occupied microtime
        bins.
        """
        return {
            "records": self.records,
            "photons": self.photons,
            "recordSha256": self.record_sha256,
            "microtime": {
                str(index): int(self.microtime[index])
                for index in np.flatnonzero(self.microtime)
            },
            "routes": self.routes,
            "markers": self.markers,
            "overflowRecords": self.overflow_records,
            "overflowWraps": self.overflow_wraps,
            "monotonicMacrotime": self.monotonic_macrotime,
            "recordType": self.record_type,
        }


def rehistogram_arrivals(
    photons: PtuScience, image: IcsImage, clock_s: float
) -> tuple[np.ndarray, int]:
    """Bin PTU arrivals against the written ICS time axis."""
    unit = image.header["parameter/units"][-1]
    multiplier = {"s": 1.0, "ns": 1e-9, "ps": 1e-12}[unit]
    step = float(image.header["parameter/scale"][-1]) * multiplier
    edges = np.arange(image.counts.shape[0] + 1) * step
    arrivals = np.arange(photons.microtime.size) * clock_s
    # Exclude the final edge, which numpy.histogram otherwise includes.
    inside = (arrivals >= edges[0]) & (arrivals < edges[-1])
    counts = np.histogram(
        arrivals[inside], bins=edges, weights=photons.microtime[inside]
    )[0]
    return counts, int(photons.microtime[~inside].sum(dtype=np.uint64))


def _record_fields(
    words: NDArray[np.uint32], record_type: int
) -> tuple[
    NDArray[np.bool_],
    NDArray[np.uint32],
    NDArray[np.uint32],
    NDArray[np.uint32],
    NDArray[np.bool_],
    NDArray[np.uint64],
]:
    """Decode PicoHarp 300 and Generic T3 bit fields separately."""
    if record_type == 66307:
        channels = words >> 28
        microtime = words >> 16 & 4095
        photon = channels != 15
        overflow = ~photon & (microtime == 0)
        wraps = overflow.astype(np.uint64)
        sync = words & 65535
        marker = microtime & 15
    elif record_type == 66311:
        channels = words >> 25 & 63
        microtime = words >> 10 & 32767
        photon = words >> 31 == 0
        overflow = ~photon & (channels == 63)
        sync = words & 1023
        wraps = np.where(overflow, np.maximum(sync, 1), 0).astype(np.uint64)
        marker = channels
    else:
        raise ValueError(f"Unsupported PTU record type {record_type:#x}")
    return (
        photon,
        channels.astype(np.uint32, copy=False),
        microtime.astype(np.uint32, copy=False),
        marker.astype(np.uint32, copy=False),
        overflow,
        wraps,
    )


class _Digest(Protocol):
    """The narrow hash boundary used for complete payload
    comparisons.
    """

    def update(self, data: bytes, /) -> None:
        """Extend the record payload digest."""

    def hexdigest(self) -> str:
        """Return the complete payload digest."""


@dataclass
class _PtuAccumulator:
    """Bounded independent record counts and chronological state."""

    histogram: np.ndarray = field(
        default_factory=lambda: np.zeros(32768, dtype=np.uint64)
    )
    route_counts: np.ndarray = field(
        default_factory=lambda: np.zeros(64, dtype=np.uint64)
    )
    marker_counts: np.ndarray = field(
        default_factory=lambda: np.zeros(64, dtype=np.uint64)
    )
    digest: _Digest = field(default_factory=hashlib.sha256)
    overflows: int = 0
    wraps_total: int = 0
    previous_sync: int = 0
    monotonic: bool = True


def inspect_ptu(path: Path) -> PtuScience:
    """Validate complete record payloads using bounded vectorized
    reads.
    """
    info = parse_ptu(path)
    tags = {tag["ident"]: tag["value"] for tag in info["tags"]}
    count = int(tags["TTResult_NumberOfRecords"])
    record_type = int(tags["TTResultFormat_TTTRRecType"])
    if info["fileSize"] != info["dataOffset"] + count * 4:
        raise ValueError("PTU payload length does not match its header")
    state = _PtuAccumulator()
    period = 65536 if record_type == 66307 else 1024
    with path.open("rb") as stream:
        stream.seek(info["dataOffset"])
        remaining = count
        while remaining:
            size = min(remaining, 2**20)
            payload = stream.read(size * 4)
            words = np.frombuffer(payload, dtype="<u4")
            state.digest.update(payload)
            photon, channels, microtime, marker, overflow, wraps = (
                _record_fields(words, record_type)
            )
            state.histogram += np.bincount(
                microtime[photon], minlength=32768
            ).astype(np.uint64)
            state.route_counts += np.bincount(
                channels[photon], minlength=64
            ).astype(np.uint64)
            state.marker_counts += np.bincount(
                marker[~photon & ~overflow], minlength=64
            ).astype(np.uint64)
            sync_mask = 65535 if period == 65536 else 1023
            absolute = (
                np.cumsum(wraps, dtype=np.uint64) + state.wraps_total
            ) * period + (words & sync_mask)
            times = absolute[~overflow]
            if times.size:
                state.monotonic = state.monotonic and bool(
                    times[0] >= state.previous_sync
                    and np.all(times[1:] >= times[:-1])
                )
                state.previous_sync = int(times[-1])
            state.overflows += int(np.count_nonzero(overflow))
            state.wraps_total += int(wraps.sum(dtype=np.uint64))
            remaining -= size
    return PtuScience(
        count,
        int(state.histogram.sum(dtype=np.uint64)),
        state.digest.hexdigest(),
        state.histogram,
        {
            int(i): int(state.route_counts[i])
            for i in np.flatnonzero(state.route_counts)
        },
        {
            int(i): int(state.marker_counts[i])
            for i in np.flatnonzero(state.marker_counts)
        },
        state.overflows,
        state.wraps_total,
        state.monotonic,
        record_type,
    )
