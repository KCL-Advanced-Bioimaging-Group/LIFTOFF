"""Visual reflection detection on decays and noisy controls."""

from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.event_flags import RAW_SINGLE_EVENT
from leica_flim_converter.histogram import decode_histogram_cube
from leica_flim_converter.reflection import (
    _contrast_noise,
    _derivatives,
    _noise_scale,
    detect_reflection_peak,
)
from leica_flim_converter.timing import time_grid
from tests.test_reference_science import example_path


def reflection_curve(bins: int = 256, center: float = 0.8) -> np.ndarray:
    """Generate a narrow reflection on a decaying photon population."""
    x = np.arange(bins) / bins
    baseline = np.where(x < 0.06, 10, 100000 * np.exp(-(x - 0.06) * 9))
    reflection = 300 * np.exp(-0.5 * ((x - center) / 0.008) ** 2)
    return np.rint(baseline + reflection).astype(np.uint64)


@pytest.mark.parametrize("bins", [128, 256, 512, 1024])
@pytest.mark.parametrize("noisy", [False, True])
def test_reflection_brackets_both_flanks(bins: int, noisy: bool) -> None:
    """Track native resolution and include the descending reflection."""
    counts = reflection_curve(bins)
    if noisy:
        counts = np.random.default_rng(53).poisson(counts)
    original = counts.copy()
    bounds = detect_reflection_peak(counts)
    assert bounds is not None
    left, right = np.asarray(bounds) / bins
    assert 0.76 < left < 0.794
    assert 0.808 < right < 0.84
    np.testing.assert_array_equal(counts, original)


@pytest.mark.parametrize("level", [10, 1000, 100000])
def test_noise_and_monotone_decays_are_not_reflections(level: int) -> None:
    """Noise, a second exponential and a background need no markers."""
    x = np.arange(256) / 256
    decay = level * (np.exp(-10 * x) + 0.02 * np.exp(-2 * x)) + 2
    baseline = np.where(x < 0.06, 1, decay)
    assert detect_reflection_peak(baseline) is None
    for seed in range(100):
        counts = np.random.default_rng(seed).poisson(baseline)
        assert detect_reflection_peak(counts) is None, seed


def _small_log_peak(sign: int = 1) -> np.ndarray:
    """Supply a precise, high-count bump smaller than eight percent."""
    x = np.arange(256)
    log_baseline = np.where(x < 12, np.log(100), np.log(1e8) - 0.0005 * x)
    return np.rint(
        np.exp(
            log_baseline + sign * 0.03 * np.exp(-0.5 * ((x - 200) / 2) ** 2)
        )
    ).astype(np.uint64)


def test_small_significant_peak_uses_curvature_shoulders() -> None:
    """Resolve a 3% bump at its expected curvature shoulders."""
    counts = _small_log_peak()
    bounds = detect_reflection_peak(counts)
    assert bounds is not None
    # Gaussian log counts have positive curvature maxima at +/-sqrt(3)
    # widths. Smoothing combines both Gaussian widths in quadrature.
    shoulder_distance = np.sqrt(3) * np.sqrt(2**2 + 1**2)
    np.testing.assert_allclose(
        bounds, (200 - shoulder_distance, 200 + shoulder_distance), atol=1
    )
    assert detect_reflection_peak(_small_log_peak(-1)) is None


def test_incomplete_pattern_and_zero_gap_are_not_reflections() -> None:
    """Reject rises without recovery or across undefined logs."""
    counts = _small_log_peak()
    counts[200] = 0
    assert detect_reflection_peak(counts) is None
    counts = _small_log_peak()
    counts[200:] = counts[200]
    assert detect_reflection_peak(counts) is None


@pytest.mark.parametrize("threshold", [0, -1, float("nan"), float("inf")])
def test_invalid_noise_threshold(threshold: float) -> None:
    """Require a finite positive multiple of the noise deviation."""
    with pytest.raises(ValueError, match="finite and positive"):
        detect_reflection_peak(_small_log_peak(), noise_sigma=threshold)


def test_both_derivative_uncertainties_match_poisson_simulations() -> None:
    """Check covariance propagation against photon simulations."""
    curve = _derivatives(np.full(256, 1e6))
    assert curve is not None
    samples = np.random.default_rng(71).poisson(1e6, size=(4096, 256))
    offsets = np.arange(-3, 4)
    kernel = np.exp(-0.5 * offsets**2)
    kernel /= kernel.sum()
    smoothed = np.apply_along_axis(
        np.convolve, 1, np.log10(samples), kernel, "same"
    )
    first = np.gradient(smoothed, axis=1)
    second = np.gradient(first, axis=1)
    trend = (smoothed[:, 130] - smoothed[:, 126]) / 4
    observed = [
        first[:, 128].std(ddof=1),
        second[:, 128].std(ddof=1),
        (first[:, 128] - trend).std(ddof=1),
    ]
    expected = [
        curve.first_sd[128],
        curve.second_sd[128],
        _contrast_noise(curve, 126, 130, 128),
    ]
    np.testing.assert_allclose(observed, expected, rtol=0.06)


def test_distant_noise_features_cannot_form_one_reflection() -> None:
    """Do not bridge a long flat tail by skipping weaker curvature."""
    x = np.arange(256)
    baseline = np.where(
        x < 12, 2, 100000 * np.exp(-0.5 * np.maximum(x - 12, 0)) + 1000
    )
    counts = np.random.default_rng(698).poisson(baseline)
    assert detect_reflection_peak(counts) is None


def test_flat_tail_poisson_false_positive_rate() -> None:
    """Check false detections across complete searched curves."""
    x = np.arange(256)
    baseline = np.where(
        x < 12, 2, 100000 * np.exp(-0.5 * np.maximum(x - 12, 0)) + 1000
    )
    detections = sum(
        detect_reflection_peak(np.random.default_rng(seed).poisson(baseline))
        is not None
        for seed in range(1000)
    )
    assert detections <= 5


def test_decay_curvature_is_not_interpreted_as_excess_noise() -> None:
    """An exact exponential is linear in log counts at any intensity."""
    counts = 1e14 * np.exp(-np.arange(256) * 0.04)
    assert _noise_scale(counts) == 1.0


@pytest.mark.parametrize(
    "counts",
    [
        [],
        [0] * 256,
        [1] * 256,
        [100, 90, 110, 80],
        [0] * 40 + [10] + [0] * 215,
        [0] * 230 + list(range(26)),
        [float("nan")] * 256,
        [float("inf")] * 256,
        [-1] * 256,
    ],
)
def test_unusable_or_sparse_curves(counts: list[float]) -> None:
    """Avoid fabricated intervals for missing or insufficient signal."""
    assert detect_reflection_peak(counts) is None


def load_example_reflection() -> tuple[np.ndarray, str]:
    """Decode the user's example through the production preview path."""
    path = example_path("CellMaskandmScar3.lif")
    if path is None:
        pytest.skip("Optional reflection example LIF is unavailable")
    dataset = next(
        item
        for item in scan_lif(Path(path))
        if item.acquisition_name == "mScar3-Pyr_FLIM04_40MHz"
    )
    grid = time_grid(dataset, None)
    cube = decode_histogram_cube(
        dataset,
        bins=grid.bins,
        grid=grid,
        threads=4,
        event_flag_mask=RAW_SINGLE_EVENT,
    )
    return cube.counts.sum(axis=(1, 2), dtype=np.uint64), dataset.key


@pytest.mark.real_data
def test_supplied_reflection_example() -> None:
    """Find the small late peak rather than the dominant excitation."""
    counts, _key = load_example_reflection()
    original = counts.copy()
    bounds = detect_reflection_peak(counts)
    assert bounds is not None
    assert bounds == (209, 220)
    # Both curvature shoulders must independently satisfy the threshold.
    assert detect_reflection_peak(counts, noise_sigma=5) is None
    np.testing.assert_array_equal(counts, original)
