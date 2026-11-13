"""Real Navigator decoding and independently inspected ICS output."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.mosaic_views import tile_view
from leica_flim_converter.native_decoder import decode_histogram_plane
from tests.test_reference_science import example_path


@pytest.fixture(scope="module", name="navigator")
def navigator_fixture() -> DatasetInfo:
    """Read the supplied example without making it a dependency."""
    path = example_path("HCC1954 mS3-mitoPyr-ShadowR.lif")
    if path is None:
        pytest.skip("Optional Navigator mosaic is unavailable")
    return next(d for d in scan_lif(path) if d.acquisition_name == "R1 (4)")


@pytest.mark.real_data
@pytest.mark.parametrize("mode", [256, 512, 1024])
def test_native_python_mosaic_samples(
    navigator: DatasetInfo, mode: int
) -> None:
    """Compare every bin and pixel in samples from all four tiles."""
    assert navigator.stage_count == 4
    assert navigator.frame_repetitions == 120
    assert navigator.t_count == navigator.z_count == 1
    for index in range(4):
        view = tile_view(navigator, index)
        first, _length = view.plane_row_range(0)
        sample = replace(
            view,
            plane_row_ranges=((first, 64),),
            plane_row_starts=(first,),
            intensity_start=None,
            intensity_end=None,
            intensity_plane_starts=(),
            total_photons=None,
        )
        native = decode_histogram_plane(
            sample, 0, bins=8, threads=4, event_flag_mask=mode
        )
        python = decode_histogram_plane(
            sample, 0, bins=8, prefer_native=False, event_flag_mask=mode
        )
        np.testing.assert_array_equal(native.counts, python.counts)
        assert native.decoded_rows == python.decoded_rows == 64
        assert native.events == python.events > 0


@pytest.mark.real_data
def test_supplied_tile_ics(navigator: DatasetInfo, tmp_path: Path) -> None:
    """Export full tiles and verify their counts and provenance."""
    results = export_ics_blocks(
        [navigator], tmp_path, IcsExportOptions(bins=32)
    )
    assert len(results) == 4
    totals = [9167961, 16303227, 10354944, 12144951]
    for index, result in enumerate(results):
        assert result["status"] == "exported", result
        image = read_ics(Path(result["path"]))
        assert image.counts.shape == (32, 1024, 1024)
        metadata = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )
        assert metadata["photonAccounting"]["selectedPhotons"] == totals[index]
        assert (
            int(image.counts.sum(dtype=np.uint64))
            == metadata["totalPhotonCount"]
        )
        assert metadata["mosaic"]["tileIndexZeroBased"] == index
        assert metadata["plane"]["encodedRowCount"] == 122880
        assert metadata["sourceStorage"]["frameRepetitionsPerPlane"] == 120
