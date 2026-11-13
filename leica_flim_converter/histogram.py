"""Streaming conversion from Leica token rows to an in-memory TCSPC
cube.
"""

from __future__ import annotations

from collections.abc import Callable

from .dataset import DatasetInfo
from .event_flags import PRIMARY_EVENT_FLAGS
from .histogram_core import (
    DecodeCancelled,
    DecodeCancelledError,
    HistogramAccumulator,
    HistogramCube,
    _spatial_views,
    _transform_cube,
    align_cube_to_linked_intensity,
    decode_histogram_cube_python,
    decode_histogram_plane_python,
)
from .native_decoder import decode_histogram_cube as dispatch
from .timing import TimeGrid


def decode_histogram_cube(
    dataset: DatasetInfo,
    bins: int = 128,
    threads: int | None = None,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    prefer_native: bool = True,
    event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    grid: TimeGrid | None = None,
) -> HistogramCube:
    """Compute decode histogram cube."""
    return dispatch(
        dataset,
        bins=bins,
        threads=threads,
        progress=progress,
        cancelled=cancelled,
        prefer_native=prefer_native,
        event_flag_mask=event_flag_mask,
        grid=grid,
    )


__all__ = [
    "HistogramCube",
    "HistogramAccumulator",
    "DecodeCancelledError",
    "_spatial_views",
    "_transform_cube",
    "align_cube_to_linked_intensity",
    "decode_histogram_cube_python",
    "decode_histogram_plane_python",
    "DecodeCancelled",
    "decode_histogram_cube",
]
