"""Compact ICS samples while preserving integer counts and NaNs."""

from __future__ import annotations

import numpy as np


def _real_encoding(stack):
    """Use float32 when integers, finite range and nonzeros survive."""
    maximum = rounding_error = 0.0
    missing = 0
    compact_safe = True
    all_integral = True
    for plane in stack:
        if np.any(np.isinf(plane)) or np.any(plane < 0):
            raise ValueError("ICS counts must be nonnegative or NaN")
        missing += int(np.count_nonzero(np.isnan(plane)))
        values = plane[np.isfinite(plane)]
        maximum = max(maximum, float(values.max(initial=0)))
        with np.errstate(over="ignore", under="ignore", invalid="ignore"):
            compact = values.astype(np.float32)
        fractional = values != np.floor(values)
        all_integral &= not bool(fractional.any())
        compact_safe &= bool(
            np.isfinite(compact).all()
            and np.all((values == 0) | (compact != 0))
            and np.all(fractional | (compact == values))
        )
        rounding_error = max(
            rounding_error,
            float(np.abs(values - compact).max(initial=0)),
        )
    if missing == 0 and all_integral and maximum <= np.iinfo(np.uint32).max:
        return _integer_encoding(int(maximum), stack.dtype.name)
    bits = 32 if compact_safe else 64
    dtype = np.dtype("<f4" if compact_safe else "<f8")
    details = {
        "sampleFormat": "real",
        "bitsPerSample": bits,
        "storageDtype": dtype.name,
        "sourceDtype": stack.dtype.name,
        "missingSamples": missing,
        "integerValuesPreservedExactly": True,
        "maximumAbsoluteRoundingError": rounding_error if compact_safe else 0,
        "precisionPolicy": (
            "Float32 with fractional rounding; use Float64 if integer "
            "counts would change, or finite nonzero values overflow or "
            "underflow. NaNs remain NaNs."
        ),
    }
    return bits, dtype, maximum, details


def _integer_encoding(maximum, source_dtype):
    """Use the smallest supported exact unsigned integer width."""
    bits = 16 if maximum <= np.iinfo(np.uint16).max else 32
    dtype = np.dtype("<u2" if bits == 16 else "<u4")
    return (
        bits,
        dtype,
        maximum,
        {
            "sampleFormat": "integer",
            "bitsPerSample": bits,
            "storageDtype": dtype.name,
            "sourceDtype": source_dtype,
            "missingSamples": 0,
            "integerValuesPreservedExactly": True,
            "maximumAbsoluteRoundingError": 0,
            "precisionPolicy": "Exact unsigned integer counts",
        },
    )


def sample_encoding(stack):
    """Keep raw integer widths and compact repaired real samples."""
    if stack.dtype.kind == "f":
        return _real_encoding(stack)
    maximum = int(stack.max())
    if maximum > np.iinfo(np.uint32).max or int(stack.min()) < 0:
        raise OverflowError(
            "ICS histogram counts must fit an unsigned 32-bit integer"
        )
    return _integer_encoding(maximum, stack.dtype.name)
