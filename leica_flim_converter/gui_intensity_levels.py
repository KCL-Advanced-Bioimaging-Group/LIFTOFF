"""Raw intensity distributions and percentile display limits."""

import numpy as np
from PySide6.QtGui import QImage


class IntensityDistribution:
    """Retain raw frequencies and exact percentile endpoints."""

    def __init__(self, arrays) -> None:
        values = np.concatenate(
            [np.asarray(array).ravel() for array in arrays]
        )
        self.values, self.counts = np.unique(values, return_counts=True)
        self.cumulative = np.cumsum(self.counts)

    def quantile(self, percentile: float) -> float:
        """Interpolate percentile ranks without expanding counts."""
        rank = (self.cumulative[-1] - 1) * percentile / 100
        lower, upper = np.floor(rank), np.ceil(rank)
        indices = np.searchsorted(
            self.cumulative, [lower, upper], side="right"
        )
        low, high = self.values[indices].astype(np.float64)
        return float(low + (high - low) * (rank - lower))

    def curve(self) -> tuple[np.ndarray, np.ndarray]:
        """Count original pixels in equal-width intensity bins."""
        low, high = int(self.values[0]), int(self.values[-1])
        if high - low < 256:
            centres = np.arange(low, high + 1, dtype=np.float64)
            counts = np.zeros(centres.size, dtype=np.int64)
            counts[(self.values - low).astype(np.int64)] = self.counts
            return centres, counts
        edges = np.linspace(float(low), float(high), 257)
        counts, _edges = np.histogram(
            self.values, bins=edges, weights=self.counts
        )
        return (edges[:-1] + edges[1:]) / 2, counts

    def percentile(self, intensity: float) -> float:
        """Invert quantiles, using mid-ranks for tied values."""
        if intensity <= self.values[0]:
            return 0.0
        if intensity >= self.values[-1]:
            return 100.0
        index = int(np.searchsorted(self.values, intensity))
        if self.values[index] == intensity:
            rank = self.cumulative[index] - (self.counts[index] + 1) / 2
        else:
            lower, upper = self.values[index - 1 : index + 1].astype(
                np.float64
            )
            rank = (
                self.cumulative[index - 1]
                - 1
                + (intensity - lower) / (upper - lower)
            )
        return float(rank / (self.cumulative[-1] - 1) * 100)

    def axis_limits(self) -> tuple[float, float]:
        """Keep the full measured range, including bright outliers."""
        low, high = float(self.values[0]), float(self.values[-1])
        return low, high if high > low else low + 1


def render_intensity(intensity, low: float, high: float) -> QImage:
    """Apply contrast only when creating display pixels."""
    pixels = np.ascontiguousarray(
        np.clip(
            (np.asarray(intensity, dtype=np.float64) - low)
            * 255
            / max(1e-12, high - low),
            0,
            255,
        ).astype(np.uint8)
    )
    height, width = pixels.shape
    return QImage(
        pixels.data,
        width,
        height,
        pixels.strides[0],
        QImage.Format.Format_Grayscale8,
    ).copy()
