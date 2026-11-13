"""Tile indexes, intensity ownership and independent decoding checks."""

import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import lif_flim_forensics as lif
from leica_flim_converter.catalog import (
    load_intensity,
    load_intensity_movie,
    scan_lif,
)
from leica_flim_converter.catalog_mosaic import attach_mosaic
from leica_flim_converter.event_flags import RAW_ALL_PHOTONS, RAW_FIRST_PHOTONS
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.mosaic_views import tile_view
from leica_flim_converter.native_decoder import (
    decode_histogram_cube,
    decode_histogram_plane,
)
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from tests.mosaic_fixture import mosaic_lif


def _edit_header(path: Path, old: str, new: str) -> Path:
    data = path.read_bytes()
    xml, end = lif.parse_lif_header(data)
    assert old in xml
    xml = xml.replace(old, new).encode("utf-16le")
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + data[end:]
    )
    return path


@pytest.mark.parametrize(("columns", "rows"), [(2, 2), (3, 2), (1, 3)])
@pytest.mark.parametrize("native", [True, False])
def test_mosaic_time_depth_and_channels(
    tmp_path: Path, columns: int, rows: int, native: bool
) -> None:
    """Keep stage, time and depth identities separate."""
    datasets = scan_lif(
        mosaic_lif(
            tmp_path / "tiles.lif",
            columns,
            rows,
            times=2,
            depths=2,
            channels=2,
        )
    )
    assert len(datasets) == 2
    for dataset in datasets:
        assert dataset.mosaic is not None
        assert (dataset.mosaic.columns, dataset.mosaic.rows) == (columns, rows)
        assert dataset.stage_count == columns * rows
        assert dataset.plane_count == dataset.stage_count * 4
        assert dataset.dimension_status.startswith("confirmed")
        assert dataset.t_count == dataset.z_count == 2
        assert len(dataset.intensity_plane_starts) == dataset.plane_count
        assert len(set(dataset.intensity_plane_starts)) == dataset.plane_count
        for index in range(dataset.stage_count):
            tile = tile_view(dataset, index)
            assert tile.plane_count == 4
            assert tile.key != dataset.key
            assert tile.pair_key == dataset.key
            assert tile.tile_index == index
            for plane in range(tile.plane_count):
                time, depth = tile.plane_indices(plane)
                cube = decode_histogram_plane(
                    tile,
                    plane,
                    bins=64,
                    prefer_native=native,
                    event_flag_mask=RAW_ALL_PHOTONS,
                )
                repeats = index + 1 + time + depth + dataset.channel_index
                arrival = (
                    2 + index * 3 + depth + time * 5 + dataset.channel_index
                )
                expected = np.zeros((64, 2, 3), dtype=np.uint64)
                expected[arrival] = 6 * repeats
                np.testing.assert_array_equal(cube.counts, expected)
                assert cube.events == cube.reference_events == 36 * repeats
                assert cube.decoded_rows == 12


def test_mosaic_snake_order(tmp_path: Path) -> None:
    """Stage matching restores the correct cells."""
    dataset = scan_lif(mosaic_lif(tmp_path / "tiles.lif"))[0]
    assert dataset.mosaic is not None
    assert [(tile.column, tile.row) for tile in dataset.mosaic.tiles] == [
        (0, 0),
        (1, 0),
        (1, 1),
        (0, 1),
    ]
    assert [dataset.plane_label(plane) for plane in range(4)] == [
        "tile_r01_c01",
        "tile_r01_c02",
        "tile_r02_c02",
        "tile_r02_c01",
    ]
    first = decode_histogram_plane(
        dataset, 0, bins=64, event_flag_mask=RAW_FIRST_PHOTONS
    )
    last = decode_histogram_plane(
        dataset, 3, bins=64, event_flag_mask=RAW_FIRST_PHOTONS
    )
    assert first.events == 36
    assert last.events == 144
    with pytest.raises(ValueError, match="tile"):
        decode_histogram_cube(dataset, bins=64)


def test_mosaic_intensity_matrix(tmp_path: Path) -> None:
    """Intensity overviews retain cells and sum only time and depth."""
    source = mosaic_lif(tmp_path / "tiles.lif", times=2, depths=2)
    dataset = scan_lif(source)[0]
    image = load_intensity(source.read_bytes(), dataset)
    movie = load_intensity_movie(dataset)
    assert image is not None and movie is not None
    assert image.shape == (4, 6)
    assert movie.shape == (16, 2, 3)
    for index, (column, row) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
        np.testing.assert_array_equal(
            image[row * 2 : row * 2 + 2, column * 3 : column * 3 + 3],
            np.full((2, 3), 24 * (index + 2)),
        )


@pytest.mark.parametrize(
    ("flip_x", "flip_y", "swap", "cells"),
    [
        (0, 0, 0, [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1)]),
        (1, 0, 0, [(2, 0), (1, 0), (0, 0), (0, 1), (1, 1), (2, 1)]),
        (0, 1, 0, [(0, 1), (1, 1), (2, 1), (2, 0), (1, 0), (0, 0)]),
        (1, 1, 0, [(2, 1), (1, 1), (0, 1), (0, 0), (1, 0), (2, 0)]),
        (0, 0, 1, [(0, 0), (0, 1), (0, 2), (1, 2), (1, 1), (1, 0)]),
        (1, 0, 1, [(1, 0), (1, 1), (1, 2), (0, 2), (0, 1), (0, 0)]),
        (0, 1, 1, [(0, 2), (0, 1), (0, 0), (1, 0), (1, 1), (1, 2)]),
        (1, 1, 1, [(1, 2), (1, 1), (1, 0), (0, 0), (0, 1), (0, 2)]),
    ],
)
def test_mosaic_grid_orientation(
    tmp_path: Path, flip_x: int, flip_y: int, swap: int, cells: list
) -> None:
    """Grid flags preserve the identities of photon planes."""
    source = _edit_header(
        mosaic_lif(tmp_path / "tiles.lif", 3, 2),
        'FlipX="0" FlipY="0" SwapXY="0"',
        f'FlipX="{flip_x}" FlipY="{flip_y}" SwapXY="{swap}"',
    )
    dataset = scan_lif(source)[0]
    assert dataset.mosaic is not None
    assert (dataset.mosaic.columns, dataset.mosaic.rows) == (
        (2, 3) if swap else (3, 2)
    )
    assert [(tile.column, tile.row) for tile in dataset.mosaic.tiles] == cells


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ('Name="TileScanInfo"', 'Name="Unknown"', "missing"),
        ('FieldX="1" FieldY="0"', 'FieldX="0" FieldY="0"', "rectangular"),
        ('FieldX="1"', 'FieldX="2"', "rectangular"),
        ("<X>0.0</X>", "<X>0.000123</X>", "ambiguous"),
        ('FlipX="0"', 'FlipX="2"', "orientation"),
        (
            "<StagePositions><X>0.0</X><Y>0.0</Y><Z>0</Z></StagePositions>",
            "",
            "counts differ",
        ),
    ],
)
def test_invalid_mosaic_geometry(
    tmp_path: Path, old: str, new: str, reason: str
) -> None:
    """Invalid tile geometry produces a clear failure."""
    source = _edit_header(mosaic_lif(tmp_path / "bad.lif"), old, new)
    dataset = scan_lif(source)[0]
    assert dataset.repetition_storage_model == "unresolved"
    assert reason in dataset.dimension_status
    with pytest.raises(RuntimeError, match=reason):
        decode_histogram_plane(dataset, 0, bins=64)


def test_mosaic_overlapping_rows(tmp_path: Path) -> None:
    """A frame table cannot assign the same encoded row to two tiles."""
    source = mosaic_lif(tmp_path / "bad.lif")
    dataset = scan_lif(source)[0]
    xml, _end = lif.parse_lif_header(source.read_bytes())
    invalid = attach_mosaic(
        replace(
            dataset,
            mosaic=None,
            plane_row_ranges=(),
            plane_row_starts=(0, 11, 24, 36),
        ),
        xml,
        xml,
    )
    assert invalid.repetition_storage_model == "unresolved"
    assert "distinct tiles" in invalid.dimension_status


def test_invalid_mosaic_frame_index(tmp_path: Path) -> None:
    """Missing frame entries cannot be inferred as a valid tile grid."""
    dataset = scan_lif(mosaic_lif(tmp_path / "bad.lif", bad_frames=True))[0]
    assert dataset.repetition_storage_model == "unresolved"
    with pytest.raises(RuntimeError, match="FrameOffsets"):
        decode_histogram_plane(dataset, 0, bins=64)


@pytest.mark.parametrize("mask", [256, 512, 1024])
def test_tile_exports(tmp_path: Path, mask: int) -> None:
    """Exports retain tile positions and photon counts."""
    dataset = scan_lif(mosaic_lif(tmp_path / "tiles.lif"))[0]
    images = export_ics_blocks(
        [dataset],
        tmp_path / "ics",
        IcsExportOptions(bins=64, event_flag_mask=mask),
    )
    ptus = export_ptu_blocks(
        [dataset], tmp_path / "ptu", PtuExportOptions(event_flag_mask=mask)
    )
    assert len(images) == len(ptus) == 4
    for plane, (image, ptu) in enumerate(zip(images, ptus, strict=True)):
        assert image["status"] == ptu["status"] == "exported"
        cube = decode_histogram_plane(
            dataset, plane, bins=64, event_flag_mask=mask
        )
        np.testing.assert_array_equal(
            read_ics(Path(image["path"])).counts, cube.counts
        )
        exported = inspect_ptu(Path(ptu["path"]))
        assert exported.photons == cube.events
        np.testing.assert_array_equal(
            exported.microtime[:64],
            cube.counts.sum(axis=(1, 2), dtype=np.uint64),
        )
        for result in (image, ptu):
            metadata = json.loads(
                Path(result["sidecar"]).read_text(encoding="utf-8")
            )
            assert metadata["mosaic"]["tileIndexZeroBased"] == plane
            assert (
                metadata["mosaic"]["columns"]
                == metadata["mosaic"]["rows"]
                == 2
            )
            assert dataset.plane_label(plane) in Path(result["path"]).stem
    failed = export_ics_blocks(
        [dataset],
        tmp_path / "integrated",
        IcsExportOptions(dimension_mode="integrate"),
    )
    assert failed[0]["status"] == "failed"
    assert "keep tiles separate" in failed[0]["error"]
