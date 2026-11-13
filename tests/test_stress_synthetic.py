"""Larger rectangular mosaics with unequal T and Z dimensions."""

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.timing import time_grid
from tests.multichannel_mosaic_fixture import (
    MosaicSpec,
    expected_cube,
    multichannel_mosaic_lif,
)


@pytest.mark.parametrize("mode", ["SequentialFrame", "SequentialStack"])
@pytest.mark.parametrize("mask", [256, 512, 1024])
def test_rectangular_mosaic_unequal_time_z(tmp_path, mode, mask):
    """Check every pixel across 288 channel/tile/T/Z planes."""
    spec = MosaicSpec(
        columns=3, rows=2, width=31, height=17, times=3, depths=4, mode=mode
    )
    datasets = scan_lif(multichannel_mosaic_lif(tmp_path / "stress.lif", spec))
    assert len(datasets) == 4
    for pair, dataset in enumerate(datasets):
        assert dataset.plane_count == 72
        sequence, route = divmod(pair, 2)
        grid = time_grid(dataset, None)
        visited = set()
        for plane in range(dataset.plane_count):
            time, depth = dataset.plane_indices(plane)
            stage = dataset.plane_stage_index(plane)
            visited.add((time, stage, depth))
            cube = decode_histogram_plane(
                dataset,
                plane,
                bins=grid.bins,
                grid=grid,
                event_flag_mask=mask,
                threads=4,
            )
            expected = expected_cube(
                spec, (time, stage, depth, sequence, route), mask
            )
            np.testing.assert_array_equal(cube.counts, expected)
            assert cube.events == int(expected.sum())
            assert cube.overflow_events == 0
        assert len(visited) == 72
