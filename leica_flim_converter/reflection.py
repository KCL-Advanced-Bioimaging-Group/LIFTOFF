"""Locate visual reflection bounds using noise-supported derivatives."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
from numpy.typing import ArrayLike, NDArray

FloatArray = NDArray[np.float64]
_NORMAL_MAD = NormalDist().inv_cdf(0.75)


@dataclass(frozen=True)
class _DerivativeCurve:
    """Log decay, derivative stencils and propagated counting noise."""

    smooth: FloatArray
    first: FloatArray
    second: FloatArray
    variance: FloatArray
    first_sd: FloatArray
    second_sd: FloatArray
    kernel: FloatArray
    first_kernel: FloatArray
    valid: NDArray[np.bool_]


def _noise_scale(values: FloatArray) -> float:
    """Allow excess noise above the Poisson counting-noise floor."""
    usable = (values[:-2] > 0) & (values[1:-1] > 0) & (values[2:] > 0)
    if not np.any(usable):
        return 1.0
    left, middle, right = (
        part[usable] for part in (values[:-2], values[1:-1], values[2:])
    )
    variance = 1 / left + 4 / middle + 1 / right
    residual = (np.log(left) - 2 * np.log(middle) + np.log(right)) / np.sqrt(
        variance
    )
    scatter = np.median(np.abs(residual - np.median(residual)))
    return max(1.0, float(scatter) / _NORMAL_MAD)


def _derivatives(counts: FloatArray) -> _DerivativeCurve | None:
    """Smooth log counts and propagate noise through derivatives."""
    sigma = max(1.0, counts.size / 256)
    radius = int(np.ceil(3 * sigma))
    if counts.size < 2 * (radius + 2) + 3:
        return None
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma) ** 2)
    kernel /= kernel.sum()
    first_kernel = np.convolve(kernel, [0.5, 0, -0.5])
    second_kernel = np.convolve(first_kernel, [0.5, 0, -0.5])
    positive = counts > 0
    log_counts = np.zeros(counts.size, dtype=np.float64)
    log_counts[positive] = np.log10(counts[positive])
    start = min(int(np.argmax(counts)) + radius + 2, counts.size - 3)
    noise = _noise_scale(counts[start:])
    variance = np.zeros(counts.size, dtype=np.float64)
    variance[positive] = noise**2 / (np.log(10) ** 2 * counts[positive])
    # Missing log values never contribute to a usable stencil. Exclude
    # zero bins, gaps and edges by requiring the complete second-
    # derivative support to contain positive observations.
    valid = (
        np.convolve(
            positive.astype(np.int64),
            np.ones(second_kernel.size, dtype=np.int64),
            "same",
        )
        == second_kernel.size
    )
    return _DerivativeCurve(
        smooth=np.convolve(log_counts, kernel, "same"),
        first=np.convolve(log_counts, first_kernel, "same"),
        second=np.convolve(log_counts, second_kernel, "same"),
        variance=variance,
        first_sd=np.sqrt(np.convolve(variance, first_kernel**2, "same")),
        second_sd=np.sqrt(np.convolve(variance, second_kernel**2, "same")),
        kernel=kernel,
        first_kernel=first_kernel,
        valid=valid,
    )


def _contrast_noise(
    curve: _DerivativeCurve, left: int, right: int, index: int
) -> float:
    """Propagate covariance for a derivative minus its local trend."""
    radius = curve.first_kernel.size // 2
    start = left - radius
    weights = np.zeros(right - left + 2 * radius + 1, dtype=np.float64)
    # The local trend is the chord between smoothed log counts at the
    # candidate shoulders. Combine all weights before squaring so
    # shared observations, including smoothing covariance, are retained.
    weights[1 : curve.kernel.size + 1] += curve.kernel / (right - left)
    offset = right - left + 1
    weights[offset : offset + curve.kernel.size] -= curve.kernel / (
        right - left
    )
    offset = index - left
    weights[offset : offset + curve.first_kernel.size] += curve.first_kernel[
        ::-1
    ]
    return float(
        np.sqrt(
            np.sum(weights**2 * curve.variance[start : start + weights.size])
        )
    )


def _pattern_score(curve: _DerivativeCurve, left: int, right: int) -> float:
    """Score the weakest feature of the bump in units of noise."""
    if right - left < 3 or not np.all(curve.valid[left : right + 1]):
        return 0.0
    peak = left + 1 + int(np.argmax(curve.first[left + 1 : right]))
    if peak >= right - 1:
        return 0.0
    trough = peak + 1 + int(np.argmin(curve.first[peak + 1 : right]))
    trend = (curve.smooth[right] - curve.smooth[left]) / (right - left)
    if trend > 0:
        return 0.0
    return min(
        float(curve.first[peak] / curve.first_sd[peak]),
        float(curve.second[left] / curve.second_sd[left]),
        float(curve.second[right] / curve.second_sd[right]),
        float(curve.first[peak] - trend)
        / _contrast_noise(curve, left, right, peak),
        float(trend - curve.first[trough])
        / _contrast_noise(curve, left, right, trough),
    )


def detect_reflection_peak(
    values: ArrayLike, *, noise_sigma: float = 3.0
) -> tuple[float, float] | None:
    """Find a significant rise-and-fall in the smoothed log decay.

    Each feature must exceed ``noise_sigma`` estimated noise standard
    deviations (three by default). The first derivative must rise above
    zero and the local decay trend, then fall below that trend. The
    neighbouring positive second-derivative maxima define boundaries
    only when both are significant. Do not skip unsupported curvature
    peaks to pair distant features. Select the strongest complete
    pattern after the primary peak. No height percentages are used.

    Gaussian sigma is max(1, native bins / 256). Central differences
    match differentiating the smoothed log decay once and twice. Noise
    uses Poisson log-count variance with robust excess-noise inflation;
    complete stencils retain covariance through both derivatives and
    the local trend comparison. Log-undefined bins and edge stencils
    are excluded, without adding pseudocounts.
    """
    if not np.isfinite(noise_sigma) or noise_sigma <= 0:
        raise ValueError("The noise threshold must be finite and positive")
    counts = np.asarray(values, dtype=np.float64).reshape(-1)
    if (
        not counts.size
        or not np.all(np.isfinite(counts))
        or np.any(counts < 0)
        or not np.any(counts)
    ):
        return None
    curve = _derivatives(counts)
    if curve is None:
        return None
    maxima = (
        np.flatnonzero(
            (curve.second[1:-1] > curve.second[:-2])
            & (curve.second[1:-1] >= curve.second[2:])
        )
        + 1
    )
    main_end = int(np.argmax(counts)) + curve.first_kernel.size // 2 + 1
    maxima = maxima[
        curve.valid[maxima] & (maxima > main_end) & (curve.second[maxima] > 0)
    ]
    candidates = []
    for left, right in zip(maxima[:-1], maxima[1:], strict=True):
        score = _pattern_score(curve, int(left), int(right))
        if score >= noise_sigma:
            candidates.append((score, (float(left), float(right))))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None
