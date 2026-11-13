"""Independent file checks for optional reflection photon exclusion."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from leica_flim_converter import ics_export
from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.histogram_core import DecodeCancelled
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.reflection_export import (
    ReflectionWindow,
    filter_native_cube,
)
from leica_flim_converter.timing import time_grid
from tests.compressed_fixture import mixed_compressed_lif


def _export_pair(dataset, directory, bins, mask, windows=()):
    """Export both actual formats using the same native interval."""
    selections = {dataset.key: [0]}
    ptu = export_ptu_blocks(
        [dataset],
        directory / "ptu",
        PtuExportOptions(event_flag_mask=mask, reflection_windows=windows),
        plane_selection=selections,
    )[0]
    ics = export_ics_blocks(
        [dataset],
        directory / "ics",
        IcsExportOptions(
            bins=bins, event_flag_mask=mask, reflection_windows=windows
        ),
        plane_selection=selections,
    )[0]
    assert ptu["status"] == ics["status"] == "exported", (ptu, ics)
    return (
        inspect_ptu(Path(ptu["path"])),
        read_ics(Path(ics["path"])),
        json.loads(Path(ptu["sidecar"]).read_text(encoding="utf-8"))["export"],
        json.loads(Path(ics["sidecar"]).read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("grammar", ["raw", "compressed"])
@pytest.mark.parametrize("mode", [0, 1, 2])
@pytest.mark.parametrize("bins", [None, 32, 128])
def test_reflection_exclusion_in_written_files(
    raw_dataset: DatasetInfo,
    tmp_path: Path,
    grammar: str,
    mode: int,
    bins: int | None,
) -> None:
    """Reconcile photons and spatial histograms in both formats."""
    dataset = (
        raw_dataset
        if grammar == "raw"
        else scan_lif(mixed_compressed_lif(tmp_path / "compressed.lif"))[0]
    )
    mask = (256, 512, 1024)[mode] if grammar == "raw" else (7, 3, 1)[mode]
    lower, upper = (9.5, 12.5) if grammar == "raw" else (2, 4)
    window = ReflectionWindow(dataset.key, lower, upper)
    original, native, _, _ = _export_pair(
        dataset, tmp_path / "baseline", None, mask
    )
    photons, image, ptu_metadata, metadata = _export_pair(
        dataset, tmp_path / "filtered", bins, mask, (window,)
    )
    expected_microtime = original.microtime.copy()
    removed = int(
        expected_microtime[
            int(np.ceil(lower)) : int(np.floor(upper)) + 1
        ].sum()
    )
    expected_microtime[int(np.ceil(lower)) : int(np.floor(upper)) + 1] = 0
    np.testing.assert_array_equal(photons.microtime, expected_microtime)
    assert photons.photons == original.photons - removed
    assert photons.markers == original.markers
    assert photons.monotonic_macrotime
    grid = time_grid(dataset, bins)
    expected = np.zeros_like(image.counts, dtype=np.uint64)
    destinations = grid.indices(np.arange(native.counts.shape[0]))
    for arrival, counts in enumerate(native.counts):
        if lower <= arrival <= upper:
            continue
        destination = destinations[arrival]
        if 0 <= destination < grid.bins:
            expected[destination] += counts
    np.testing.assert_array_equal(image.counts, expected)
    accounting = metadata["photonAccounting"]
    assert accounting["selectedPhotons"] == original.photons
    assert accounting["excludedReflectionPhotons"] == removed
    assert accounting["exportedPhotons"] == int(expected.sum())
    assert (
        sum(
            accounting[key]
            for key in (
                "exportedPhotons",
                "excludedReflectionPhotons",
                "excludedOutsideTimeWindow",
            )
        )
        == original.photons
    )
    assert ptu_metadata["selectedPhotons"] == original.photons
    assert ptu_metadata["excludedReflectionPhotons"] == removed
    assert ptu_metadata["reflectionFilter"]["lowerNativeBin"] == lower
    assert metadata["reflectionFilter"]["upperNativeBin"] == upper


@pytest.mark.parametrize("bounds", [(-1, 2), (2, 1), (1, float("nan"))])
def test_invalid_export_boundaries(bounds: tuple) -> None:
    """Reject invalid filter options before any output is written."""
    window = ReflectionWindow("dataset", *bounds)
    for options in (
        IcsExportOptions(reflection_windows=(window,)),
        PtuExportOptions(reflection_windows=(window,)),
    ):
        with pytest.raises(ValueError, match="reflection"):
            options.validate()


def test_all_reflection_photons_preserve_empty_scan(
    tmp_path: Path,
) -> None:
    """Retain complete scan markers even when no photons remain."""
    dataset = scan_lif(mixed_compressed_lif(tmp_path / "empty.lif"))[0]
    grid = time_grid(dataset, None)
    original, _, _, _ = _export_pair(dataset, tmp_path / "original", None, 7)
    photons, image, ptu_metadata, metadata = _export_pair(
        dataset,
        tmp_path / "filtered",
        32,
        7,
        (ReflectionWindow(dataset.key, 0, grid.bins - 1),),
    )
    assert photons.photons == 0 and not image.counts.any()
    assert photons.markers == original.markers
    assert ptu_metadata["excludedReflectionPhotons"] == original.photons
    assert metadata["photonAccounting"]["exportedPhotons"] == 0


def test_plane_and_dataset_boundaries(raw_dataset: DatasetInfo) -> None:
    """A plane's boundaries never leak to another plane or detector."""
    dataset = replace(raw_dataset, t_count=2, frame_count=2, t_stride=1)
    window = ReflectionWindow(dataset.key, 3, 5, (0,))
    assert window.covers(dataset, 0)
    assert not window.covers(dataset, 1)
    assert not window.covers(dataset, None)
    assert not window.covers(replace(dataset, channel_index=1), 0)


def test_filter_native_cache_and_cancellation(
    raw_dataset: DatasetInfo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse a native cache and support cancellation."""
    grid = time_grid(raw_dataset, None)
    cube = decode_histogram_plane(
        raw_dataset, 0, bins=grid.bins, grid=grid, event_flag_mask=256
    )
    original = cube.counts.copy()
    cube.counts.flags.writeable = False
    window = ReflectionWindow(raw_dataset.key, 9.5, 12.5)
    decoder = Mock(side_effect=AssertionError("Cache must be reused"))
    monkeypatch.setattr(ics_export, "decode_histogram_plane", decoder)
    result = export_ics_blocks(
        [raw_dataset],
        tmp_path / "cached",
        IcsExportOptions(
            bins=32, event_flag_mask=256, reflection_windows=(window,)
        ),
        cached_cubes={raw_dataset.key: cube},
        plane_selection={raw_dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    np.testing.assert_array_equal(cube.counts, original)
    assert cube.reflection_excluded_events == 0
    with pytest.raises(DecodeCancelled, match="Reflection"):
        filter_native_cube(cube, grid, window, lambda: True)
