"""Exact supplied PTU arrival histograms through production readers."""

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.decay import native_period_bins
from leica_flim_converter.event_flags import RAW_ALL_PHOTONS
from leica_flim_converter.export_inspection import inspect_ptu
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import iter_lmsraw_vectors
from tests.test_reference_science import example_path


@pytest.fixture(scope="module", name="mixed_catalogue")
def mixed_catalogue_fixture() -> list[DatasetInfo]:
    """Keep optional private data outside the source repository."""
    path = example_path("HCC_mScr-pyr+mTFP-lact.lif")
    if path is None:
        pytest.skip("Optional mixed-excitation LIF is unavailable")
    return [
        dataset for dataset in scan_lif(path) if dataset.sequence_count > 1
    ]


@pytest.mark.real_data
@pytest.mark.parametrize(
    ("suffix", "sequence", "photons"),
    [
        ("LACT+PYR1", 0, 7058116),
        ("LACT+PYR1", 1, 1679644),
        ("LACT+PYR2", 0, 15994608),
        ("LACT+PYR2", 1, 108134341),
    ],
)
def test_supplied_sequence_ptu(
    mixed_catalogue: list[DatasetInfo],
    suffix: str,
    sequence: int,
    photons: int,
) -> None:
    """Check exact native arrivals and the displayed decay per pair."""
    dataset = next(
        item
        for item in mixed_catalogue
        if (item.acquisition_name or "").endswith(suffix)
        and item.sequence_index == sequence
    )
    companion = (
        dataset.source.parent
        / "HCC_mScr-pyr+mTFP-lact.sptw/Multi-Ex Multi-Em Examples"
        / f"{dataset.acquisition_name}_seq{sequence + 1}.ptu"
    )
    if not companion.exists():
        pytest.skip("Optional supplied PTU is unavailable")
    expected = inspect_ptu(companion)
    assert expected.photons == photons
    assert dataset.detector_route == 0
    assert dataset.sequence_count == 2
    assert dataset.plane_count == 1
    assert dataset.dimension_status == "confirmed"
    assert dataset.emission_filter_band == (
        "570 - 650 nm" if sequence == 0 else "470 - 560 nm"
    )
    histogram = np.zeros(32768, dtype=np.uint64)
    first, rows = dataset.plane_row_range(0)
    for _row, _x, arrivals in iter_lmsraw_vectors(
        dataset, first, rows, RAW_ALL_PHOTONS, lambda: False
    ):
        histogram += np.bincount(arrivals, minlength=32768).astype(np.uint64)
    assert np.array_equal(histogram, expected.microtime)
    bins = native_period_bins(
        dataset.clock_period_s, dataset.laser_frequency_hz
    )
    cube = decode_histogram_plane(
        dataset, 0, bins=bins, threads=4, event_flag_mask=RAW_ALL_PHOTONS
    )
    decay = expected.microtime[:bins].copy()
    decay[-1] += expected.microtime[bins:].sum(dtype=np.uint64)
    assert cube.events == photons
    assert cube.decoded_rows == rows
    assert cube.source_dataset_key == dataset.key
    assert np.array_equal(cube.counts.sum(axis=(1, 2), dtype=np.uint64), decay)
