"""Explicit synthetic or nominal reconstructed raster timelines."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dataset import DatasetInfo
from .timing import reconstruction_error, recorded_timing, require_calibration


@dataclass(frozen=True)
class RasterTiming:
    """Reconstruction places events at pixel centres, not hardware
    times.
    """

    quality: str
    pixel_ticks: float
    line_ticks: float
    frame_ticks: float
    reason: str | None = None

    def positions(self, frame: int, y: int, x: np.ndarray, width: int):
        """Round absolute positions to avoid cumulative drift."""
        origin = frame * self.frame_ticks + y * self.line_ticks
        start = round(origin)
        photons = np.rint(origin + (x + 0.5) * self.pixel_ticks).astype(
            np.uint64
        )
        stop = round(origin + width * self.pixel_ticks)
        return start, photons, stop

    def metadata(self, global_resolution: float) -> dict:
        """Retain the approximation and its limits in each output."""
        return {
            "quality": self.quality,
            "fallbackReason": self.reason,
            "pixelSpacingSeconds": self.pixel_ticks * global_resolution,
            "lineStartSpacingSeconds": self.line_ticks * global_resolution,
            "frameStartSpacingSeconds": self.frame_ticks * global_resolution,
            "originalPhotonMacrotimesPreserved": False,
            "individualPhotonTimes": (
                "unavailable; photons assigned to nominal pixel centres"
                if self.quality == "Reconstructed"
                else "unavailable; synthetic raster positions"
            ),
            "timeOrigin": (
                "zero at this output plane/tile; "
                "no inter-file elapsed-time relation"
            ),
            "rounding": (
                "absolute positions rounded to the nearest "
                "recorded laser period"
            ),
        }


def raster_timing(
    dataset: DatasetInfo, mode: str, pixel_ticks: int
) -> RasterTiming:
    """Decline reconstruction when scan metadata cannot establish a
    raster.
    """
    _clock, frequency = require_calibration(dataset)
    reason = reconstruction_error(dataset)
    if mode == "reconstructed" and reason is not None:
        raise ValueError(f"Cannot reconstruct PTU timing: {reason}")
    if mode != "synthetic" and reason is None:
        timing = recorded_timing(dataset)
        assert timing.pixel_dwell.value is not None
        assert timing.line_period.value is not None
        dwell = timing.pixel_dwell.value * frequency
        line = timing.line_period.value * frequency
        frame = (
            timing.frame_period.value
            or dataset.height * timing.line_period.value
        ) * frequency
        return RasterTiming("Reconstructed", dwell, line, frame)
    line = 2 + dataset.width * pixel_ticks
    return RasterTiming(
        "Synthetic", pixel_ticks, line, dataset.height * line, reason
    )
