"""Photon oracles for multi-source Navigator acquisitions."""

import json
from itertools import product
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import load_intensity_movie, scan_lif
from leica_flim_converter.export_inspection import (
    inspect_ptu,
    read_ics,
    rehistogram_arrivals,
)
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.mosaic_views import tile_view
from leica_flim_converter.native_decoder import (
    decode_histogram_cube,
    decode_histogram_plane,
)
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.timing import time_grid
from tests.multichannel_mosaic_fixture import (
    MosaicSpec,
    expected_cube,
    multichannel_mosaic_lif,
)


@pytest.mark.parametrize("mode", ["SequentialFrame", "SequentialStack"])
@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("mask", [256, 512, 1024])
def test_multisource_mosaic_decode(tmp_path, mode, native, mask):
    """Decode every route, tile, T/Z plane and repetition."""
    spec = MosaicSpec(columns=3, rows=2, mode=mode)
    datasets = scan_lif(multichannel_mosaic_lif(tmp_path / "matrix.lif", spec))
    assert len(datasets) == 4
    assert len({dataset.key for dataset in datasets}) == 4
    assert {dataset.excitation_label for dataset in datasets} == {
        "555 nm (WLL)",
        "740 nm (MP)",
    }
    for pair, dataset in enumerate(datasets):
        sequence, route = divmod(pair, 2)
        assert dataset.dimension_status.startswith("confirmed")
        assert dataset.plane_count == 24
        assert dataset.mosaic is not None
        assert [
            (tile.column, tile.row) for tile in dataset.mosaic.tiles
        ] == spec.cells
        movie = load_intensity_movie(dataset)
        assert movie is not None
        for stage in range(6):
            tile = tile_view(dataset, stage)
            grid = time_grid(tile, None)
            oracle = np.zeros(
                (grid.bins, spec.height, spec.width), dtype=np.uint64
            )
            for plane in range(tile.plane_count):
                time, depth = tile.plane_indices(plane)
                identity = time, stage, depth, sequence, route
                expected = expected_cube(spec, identity, mask)
                cube = decode_histogram_plane(
                    tile,
                    plane,
                    bins=grid.bins,
                    grid=grid,
                    event_flag_mask=mask,
                    prefer_native=native,
                )
                np.testing.assert_array_equal(cube.counts, expected)
                assert cube.events == int(expected.sum())
                assert cube.overflow_events == 0
                oracle += expected
                # Independent intensity storage is C-fast in both modes.
                parent = next(
                    index
                    for index in range(dataset.plane_count)
                    if dataset.plane_indices(index) == (time, depth)
                    and dataset.plane_stage_index(index) == stage
                )
                np.testing.assert_array_equal(
                    movie[parent], expected_cube(spec, identity).sum(axis=0)
                )
            summed = decode_histogram_cube(
                tile,
                bins=grid.bins,
                grid=grid,
                event_flag_mask=mask,
                prefer_native=native,
            )
            np.testing.assert_array_equal(summed.counts, oracle)


@pytest.mark.parametrize("mode", ["SequentialFrame", "SequentialStack"])
@pytest.mark.parametrize("mask", [256, 512, 1024])
def test_multisource_mosaic_exports(tmp_path, mode, mask):
    """Round trip every source/tile/T/Z export and calibration."""
    spec = MosaicSpec(mode=mode)
    datasets = scan_lif(multichannel_mosaic_lif(tmp_path / "matrix.lif", spec))
    images = export_ics_blocks(
        datasets,
        tmp_path / "ics",
        IcsExportOptions(bins=None, event_flag_mask=mask),
    )
    ptus = export_ptu_blocks(
        datasets, tmp_path / "ptu", PtuExportOptions(event_flag_mask=mask)
    )
    assert len(images) == len(ptus) == 64
    assert len({result["path"] for result in images}) == 64
    assert len({result["path"] for result in ptus}) == 64
    identities = product(range(4), range(16))
    for (pair, plane), image, ptu in zip(
        identities, images, ptus, strict=True
    ):
        assert image["status"] == ptu["status"] == "exported"
        dataset = datasets[pair]
        sequence, route = divmod(pair, 2)
        time, depth = dataset.plane_indices(plane)
        stage = dataset.plane_stage_index(plane)
        expected = expected_cube(
            spec, (time, stage, depth, sequence, route), mask
        )
        exported = read_ics(Path(image["path"]))
        np.testing.assert_array_equal(exported.counts, expected)
        assert float(exported.header["parameter/scale"][-1]) == pytest.approx(
            spec.clock(sequence)
        )
        photons = inspect_ptu(Path(ptu["path"]))
        assert photons.photons == int(expected.sum())
        assert photons.monotonic_macrotime
        rebinned, excluded = rehistogram_arrivals(
            photons, exported, spec.clock(sequence)
        )
        assert excluded == 0
        np.testing.assert_array_equal(rebinned, expected.sum(axis=(1, 2)))
        for result in (image, ptu):
            metadata = json.loads(
                Path(result["sidecar"]).read_text(encoding="utf-8")
            )
            assert metadata["mosaic"]["tileIndexZeroBased"] == stage
            assert dataset.plane_label(plane) in Path(result["path"]).stem
