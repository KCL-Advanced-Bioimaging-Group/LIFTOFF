"""Cross-format timing checks on supplied Leica acquisitions."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.mosaic_views import tile_view
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.timing import time_grid
from tests.test_reference_science import example_path
from tests.test_timing import assert_cross_format

FILES = [
    "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif",
    "Autofluorescence.lif",
    "HCC1954 mS3-mitoPyr-ShadowR.lif",
    "HCC_mScr-pyr+mTFP-lact.lif",
    "HCConly.lif",
    "No 2.lif",
    "PL109 R72C CC CCCP NH4Cl\\PL109 R72C CC CCCP NH4Cl.lif",
    "Sample2_HCC_mTFP1_12days\\Sample2_HCC_mTFP1_12days.lif",
    "X03_CC_Biosensor_90min\\X03_CC_Biosensor_90min.lif",
]


@pytest.mark.real_data
@pytest.mark.parametrize("filename", FILES)
def test_supplied_timing_samples(tmp_path, filename):
    """Check source formats and calibration across all nine LIFs."""
    path = example_path(filename)
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    datasets = [
        d for d in scan_lif(path) if d.repetition_storage_model != "unresolved"
    ]
    if filename.startswith("20251009"):
        datasets = [
            d for d in datasets if d.acquisition_name == "paneth_ctx555_1"
        ]
    elif "mitoPyr" in filename:
        mosaic = next(d for d in datasets if d.acquisition_name == "R1 (4)")
        datasets = [tile_view(mosaic, index) for index in range(4)]
    else:
        datasets = [min(datasets, key=lambda d: d.compressed_bytes)]
    for index, dataset in enumerate(datasets):
        first, rows = dataset.plane_row_range(0)
        sample = replace(
            dataset,
            plane_row_ranges=((first, min(rows, 64)),),
            plane_row_starts=(first,),
            t_count=1,
            z_count=1,
            stage_count=1,
            intensity_start=None,
            intensity_end=None,
            intensity_plane_starts=(),
            total_photons=None,
        )
        for bins in (None, 128):
            assert_cross_format(sample, tmp_path / f"{index}-{bins}", bins, 7)


@pytest.mark.real_data
def test_full_navigator_tile_timebase(tmp_path):
    """Verify a complete tile, including all frame repeats."""
    path = example_path("HCC1954 mS3-mitoPyr-ShadowR.lif")
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    mosaic = next(d for d in scan_lif(path) if d.acquisition_name == "R1 (4)")
    dataset = tile_view(mosaic, 0)
    result = assert_cross_format(dataset, tmp_path, 128, 1024)
    assert result["timing"]["pixelDwell"]["value"] == 1.4e-6
    assert result["timing"]["timestampLists"]["rawXml"]
    assert result["mosaic"]["tileIndexZeroBased"] == 0


@pytest.mark.real_data
@pytest.mark.parametrize("filename", [FILES[0], "No 2.lif"])
def test_supplied_fixed_native_grouping(tmp_path: Path, filename: str) -> None:
    """Compare every exported pixel/bin with native count groups."""
    path = example_path(filename)
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    datasets = scan_lif(path)
    datasets = (
        [d for d in datasets if d.acquisition_name == "paneth_ctx555_1"]
        if filename.startswith("20251009")
        else datasets[:1]
    )
    for index, dataset in enumerate(datasets):
        first, rows = dataset.plane_row_range(0)
        sample = replace(
            dataset,
            plane_row_ranges=((first, min(rows, 32)),),
            plane_row_starts=(first,),
            t_count=1,
            z_count=1,
            stage_count=1,
            intensity_start=None,
            intensity_end=None,
            intensity_plane_starts=(),
            total_photons=None,
        )
        native_grid = time_grid(sample, None)
        native = decode_histogram_plane(
            sample,
            0,
            bins=native_grid.bins,
            grid=native_grid,
            event_flag_mask=7,
        )
        assert native.counts.shape[0] >= 128
        for bins in (16, 32, 64, 128):
            expected = (
                native.counts[:128]
                .reshape(bins, 128 // bins, sample.height, sample.width)
                .sum(axis=1, dtype=np.uint64)
            )
            result = export_ics_blocks(
                [sample],
                tmp_path / f"{index}-{bins}",
                IcsExportOptions(bins=bins, event_flag_mask=7),
                plane_selection={sample.key: [0]},
            )[0]
            assert result["status"] == "exported", result
            image = read_ics(Path(result["path"]))
            np.testing.assert_array_equal(image.counts, expected)
            assert image.header["representation/compression"] == [
                "uncompressed"
            ]
            assert float(image.header["parameter/scale"][-1]) == (
                native_grid.clock_s * (128 // bins)
            )
            metadata = json.loads(
                Path(result["sidecar"]).read_text(encoding="utf-8")
            )
            accounting = metadata["photonAccounting"]
            assert accounting["selectedPhotons"] == (
                native.events + native.overflow_events
            )
            assert accounting["exportedPhotons"] == int(expected.sum())
            assert accounting["excludedOutsideTimeWindow"] == (
                native.events + native.overflow_events - int(expected.sum())
            )
