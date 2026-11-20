"""Compact exports retain missing samples and integer counts."""

import numpy as np
import pytest

from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics import write_ics
from tests.test_export_metadata import _ics_metadata


@pytest.mark.parametrize("compression", ["gzip", "uncompressed"])
def test_float32_roundtrip_and_precision_metadata(
    raw_dataset, tmp_path, compression
):
    """Read fractional payloads and keep NaNs at exact locations."""
    counts = np.arange(64, dtype=np.float64).reshape(16, 2, 2) / 7
    counts[4:8, 0, 1] = np.nan
    counts[0, 0, 0] = 65535
    original = counts.copy()
    path = tmp_path / "compact.ics"
    report = write_ics(path, counts, raw_dataset, compression)
    result = read_ics(path)
    assert result.counts.dtype == np.float32
    assert report["bits"] == 32
    assert report["payloadBytesUncompressed"] == counts.size * 4
    np.testing.assert_array_equal(np.isnan(result.counts), np.isnan(counts))
    assert result.counts[0, 0, 0] == 65535
    np.testing.assert_allclose(result.counts, counts, rtol=6e-8, atol=0)
    info = report["sampleEncoding"]
    assert info == _ics_metadata(path)["sampleEncoding"]
    assert info["missingSamples"] == 4
    assert info["integerValuesPreservedExactly"]
    assert info["maximumAbsoluteRoundingError"] == float(
        np.nanmax(np.abs(result.counts.astype(float) - counts))
    )
    np.testing.assert_array_equal(counts, original)


@pytest.mark.parametrize("value", [16777217.0, 1e40, 1e-50])
def test_float64_fallback_preserves_large_integers_and_finite_nonzeros(
    raw_dataset, tmp_path, value
):
    """Keep integers exact and preserve the finite count range."""
    counts = np.ones((16, 2, 2), dtype=np.float64)
    counts[0, 0, 0] = value
    counts[4, 0, 1] = np.nan
    path = tmp_path / "requires64.ics"
    report = write_ics(path, counts, raw_dataset)
    result = read_ics(path)
    assert result.counts.dtype == np.float64
    assert report["bits"] == 64
    assert report["sampleEncoding"]["maximumAbsoluteRoundingError"] == 0
    np.testing.assert_array_equal(result.counts, counts)


@pytest.mark.parametrize("maximum,bits", [(20, 16), (65536, 32)])
def test_simulated_integer_counts_use_exact_compact_storage(
    raw_dataset, tmp_path, maximum, bits
):
    """Integer simulations use the same widths as measured counts."""
    counts = np.ones((16, 2, 2), dtype=np.float64)
    counts[0, 0, 0] = maximum
    path = tmp_path / "simulated.ics"
    report = write_ics(path, counts, raw_dataset)
    assert report["sampleFormat"] == "integer"
    assert report["bits"] == bits
    np.testing.assert_array_equal(read_ics(path).counts, counts)


def test_all_missing_samples_remain_nan(raw_dataset, tmp_path):
    """Missing data never becomes zero even with no finite samples."""
    counts = np.full((16, 2, 2), np.nan)
    path = tmp_path / "missing.ics"
    report = write_ics(path, counts, raw_dataset)
    assert report["bits"] == 32 and report["missingSamples"] == 64
    assert np.isnan(read_ics(path).counts).all()
