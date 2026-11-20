"""Missing samples, log-linear means and Poisson realizations."""

import math
from dataclasses import replace

import numpy as np

from .reflection_metadata import (
    MODE_LABELS,
    processing_description,
    simulation_context,
)

MODES = tuple(MODE_LABELS)


def count_dtype(values):
    """Preserve repaired floating counts during spatial aggregation."""
    return np.float64 if np.asarray(values).dtype.kind == "f" else np.uint64


def count_array(values):
    """Preserve missing and estimated count values."""
    return np.asarray(values, dtype=count_dtype(values))


def corrected_counts(values, bounds, mode="nan", *, seed=0) -> np.ndarray:
    """Repair a summed decay and distribute it over spatial pixels."""
    if mode not in MODES:
        raise ValueError(f"Unknown reflection processing mode: {mode!r}")
    result = np.array(values, dtype=np.float64, copy=True)
    start = max(0, math.ceil(bounds[0]))
    stop = min(result.shape[0], math.floor(bounds[1]) + 1)
    result[start:stop] = np.nan
    if mode == "nan" or start == stop:
        return result
    spatial_axes = tuple(range(1, result.ndim))
    curve = result.sum(axis=spatial_axes) if spatial_axes else result
    profile = _interpolated_profile(curve, start, stop)
    rng = (
        np.random.Generator(np.random.PCG64(seed))
        if mode == "simulate"
        else None
    )
    if not spatial_axes:
        result[start:stop] = _poisson_samples(profile, rng) if rng else profile
        return result
    weights = result[:start].sum(axis=0) + result[stop:].sum(axis=0)
    total = weights.sum()
    if not np.isfinite(total) or total <= 0:
        return result
    weights /= total
    for index, value in enumerate(profile, start):
        expected = value * weights
        result[index] = _poisson_samples(expected, rng) if rng else expected
    return result


def _interpolated_profile(curve, start, stop):
    """Join positive exterior log counts with one straight line."""
    missing = np.full(stop - start, np.nan)
    left, right = start - 1, stop
    if left < 0 or right >= curve.size:
        return missing
    shoulders = curve[[left, right]]
    if not np.all(np.isfinite(shoulders) & (shoulders > 0)):
        return missing
    logs = np.log(shoulders)
    fraction = (np.arange(start, stop) - left) / (right - left)
    values = np.exp((1 - fraction) * logs[0] + fraction * logs[1])
    return np.where(np.isfinite(values), values, np.nan)


def _poisson_samples(expected, rng):
    """Sample expected counts directly, preserving undefined means."""
    sampled = np.full_like(expected, np.nan, dtype=np.float64)
    valid = np.isfinite(expected) & (expected >= 0)
    sampled[valid] = rng.poisson(expected[valid])
    return sampled


def corrected_cube(cube, bounds, mode, *, seed=0):
    """Create a derived cube, retaining the decoded source unchanged."""
    resolved, context = simulation_context(cube, bounds, seed)
    counts = corrected_counts(cube.counts, bounds, mode, seed=resolved)
    interval = counts[max(0, math.ceil(bounds[0])) : math.floor(bounds[1]) + 1]
    metadata = processing_description(bounds, mode, seed)
    metadata.update(
        {
            "interpolationAvailable": bool(
                interval.size
                and np.isfinite(
                    interval.reshape(interval.shape[0], -1)[:, 0]
                ).all()
            )
            if mode != "nan"
            else None,
            "sourceNativeBins": cube.counts.shape[0],
        }
    )
    if mode == "simulate":
        metadata.update(randomSeed=str(resolved), seedContext=context)
    if mode != "nan" and not metadata["interpolationAvailable"]:
        metadata.update(
            appliedMode="nan",
            replacementKind="missing samples",
            syntheticNativeInterval=None,
        )
    return replace(
        cube,
        counts=counts,
        output_bits=64,
        reflection_processing=metadata,
    )
