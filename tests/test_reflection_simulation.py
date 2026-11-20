"""Log-linear means, per-pixel Poisson draws and export provenance."""

# Inspect the scientific cubes used by the actual preview controls.
# pylint: disable=protected-access

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.histogram_core import HistogramCube
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.reflection_export import ReflectionWindow
from leica_flim_converter.reflection_processing import (
    corrected_counts,
    corrected_cube,
)
from leica_flim_converter.timing import time_grid
from tests.test_export_metadata import _ics_metadata
from tests.test_gui import switch_to_single, workspace_fixture
from tests.test_reflection_filter import _place

preview_fixture = workspace_fixture


def test_bridge_needs_only_one_exterior_bin_each_side():
    """The bridge needs just the two exterior count endpoints."""
    counts = np.array([100, 1000, 1000, 1000, 1000, 25], dtype=float)
    result = corrected_counts(counts, (1, 4), "interpolate")
    np.testing.assert_allclose(
        np.log(result), np.linspace(np.log(100), np.log(25), 6)
    )


def test_pixel_poisson_statistics_and_reproducibility():
    """Independent pixel draws have the expected Poisson moments."""
    counts = np.full((16, 128, 128), 3, dtype=np.uint16)
    counts[4:12] = 1000
    original = counts.copy()
    result = corrected_counts(counts, (4, 11), "simulate", seed=12345)
    values = result[4:12].ravel()
    np.testing.assert_array_equal(values, np.floor(values))
    assert np.all(values >= 0)
    assert abs(values.mean() - 3) < 6 * np.sqrt(3 / values.size)
    assert abs(values.var() - 3) < 6 * np.sqrt((3 + 2 * 3**2) / values.size)
    np.testing.assert_array_equal(result[:4], counts[:4])
    np.testing.assert_array_equal(result[12:], counts[12:])
    np.testing.assert_array_equal(
        result, corrected_counts(counts, (4, 11), "simulate", seed=12345)
    )
    assert not np.array_equal(
        result, corrected_counts(counts, (4, 11), "simulate", seed=67890)
    )
    np.testing.assert_array_equal(counts, original)


@pytest.mark.parametrize("mode", ["interpolate", "simulate"])
def test_unknown_endpoint_stays_missing(mode):
    """Missing whole-image endpoints leave missing replacements."""
    counts = np.ones((16, 2, 2), dtype=np.uint32)
    counts[3] = 0
    counts[:, 1, 1] = 0
    result = corrected_counts(counts, (4, 8), mode, seed=123)
    assert np.isnan(result[4:9]).all()
    cube = HistogramCube(counts, int(counts.sum()), 0, 16, 2)
    metadata = corrected_cube(cube, (4, 8), mode).reflection_processing
    assert metadata["appliedMode"] == "nan"
    assert metadata["syntheticNativeInterval"] is None


def test_simulation_context_is_independent_of_execution_details():
    """Seeds follow data contexts, not execution details."""
    cube = HistogramCube(
        np.full((16, 8, 8), 10, dtype=np.uint16),
        10240,
        0,
        16,
        8,
        source_dataset_key="data-A",
        linear_plane=0,
    )
    expected = corrected_cube(cube, (4, 8), "simulate", seed=456)
    for other in (
        replace(cube, thread_count=16),
        replace(cube, linear_plane=None),
    ):
        replay = corrected_cube(other, (4, 8), "simulate", seed=456)
        np.testing.assert_array_equal(replay.counts, expected.counts)
    for other in (
        replace(cube, source_dataset_key="data-B"),
        replace(cube, linear_plane=1),
        replace(cube, event_flag_mask=1),
    ):
        changed = corrected_cube(other, (4, 8), "simulate", seed=456)
        assert not np.array_equal(changed.counts, expected.counts)
    metadata = expected.reflection_processing
    replay = corrected_counts(
        cube.counts, (4, 8), "simulate", seed=int(metadata["randomSeed"])
    )
    np.testing.assert_array_equal(replay, expected.counts)
    assert metadata["baseSeed"] == "456"
    assert metadata["randomGenerator"] == "numpy.random.PCG64"


@pytest.mark.parametrize("mode", ["interpolate", "simulate"])
@pytest.mark.parametrize("bins", [None, 32])
def test_preview_export_and_rebinned_synthetic_metadata(
    raw_dataset, tmp_path, mode, bins
):
    """One realization survives native export and rebinning."""
    dataset = replace(raw_dataset, laser_frequency_hz=78_125_000.0)
    grid = time_grid(dataset, None)
    assert grid.bins == 128
    counts = np.broadcast_to(
        np.array([[2, 4], [6, 8]], dtype=np.uint16), (128, 2, 2)
    ).copy()
    counts[41:48] = 1000
    cube = HistogramCube(
        counts,
        int(counts.sum()),
        0,
        128,
        2,
        source_dataset_key=dataset.key,
        linear_plane=0,
        event_flag_mask=256,
        time_grid=grid,
    )
    counts.flags.writeable = False
    window = ReflectionWindow(
        dataset.key, 40.2, 47.8, mode=mode, seed=987654321
    )
    preview = corrected_cube(
        cube, (window.lower, window.upper), mode, seed=window.seed
    )
    result = export_ics_blocks(
        [dataset],
        tmp_path,
        IcsExportOptions(
            bins=bins, event_flag_mask=256, reflection_windows=(window,)
        ),
        cached_cubes={dataset.key: cube},
        plane_selection={dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    image = read_ics(Path(result["path"]))
    expected = (
        preview.counts
        if bins is None
        else preview.counts.reshape(32, 4, 2, 2).sum(1)
    )
    np.testing.assert_array_equal(
        image.counts, expected.astype(image.counts.dtype)
    )
    sidecar = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
    embedded = _ics_metadata(Path(result["path"]))
    info = sidecar["reflectionFilter"]
    assert info == embedded["reflectionFilter"]
    assert info["syntheticNativeInterval"] == {
        "firstBin": 41,
        "lastBin": 47,
        "scope": "all spatial pixels",
    }
    assert info["containsSyntheticSamples"]
    assert not info["replacementValuesAreMeasuredPhotons"]
    assert info["syntheticOutputBins"] == (
        list(range(41, 48)) if bins is None else [10, 11]
    )
    assert "log-linear" in info["interpolationModel"]
    if mode == "simulate":
        assert (
            info["randomSeed"] == preview.reflection_processing["randomSeed"]
        )
        assert info["simulatedCountSum"] == int(preview.counts[41:48].sum())
    readable = Path(result["path"] + ".metadata.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "Synthetic output bins" in readable
    assert "Replacement count interpretation" in readable
    accounting = sidecar["photonAccounting"]
    assert (
        sum(
            accounting[key]
            for key in (
                "exportedPhotons",
                "excludedReflectionPhotons",
                "excludedOutsideTimeWindow",
            )
        )
        == cube.events
    )
    np.testing.assert_array_equal(cube.counts, counts)


def test_simulation_selection_survives_toggle_and_repaint(workspace, qtbot):
    """Keep one pixel cube behind graphs and exact requested labels."""
    switch_to_single(workspace, qtbot)
    control = workspace.reflection_filter
    assert [control.mode.itemText(i) for i in range(control.mode.count())] == [
        "Assign to NaNs",
        "Interpolate values (smooth)",
        "Simulate photon counts from interpolation",
    ]
    _place(workspace, qtbot)
    control.mode.setCurrentIndex(2)
    control.checkbox.click()
    original = workspace.cube.counts.copy()
    windows = control.export_windows()
    assert windows[0].mode == "simulate" and windows[0].seed >= 0
    workspace.show_pixel(1, 1)
    assert workspace.histogram._histogram_scope_2() == "Pixel 1, 1"
    np.testing.assert_array_equal(
        workspace.histogram.series[0][1], workspace.cube.pixel(1, 1)
    )
    workspace.histogram.grab()
    control.checkbox.click()
    control.checkbox.click()
    np.testing.assert_array_equal(workspace.cube.counts, original)
    assert control.export_windows() == windows
    control.mode.setCurrentIndex(1)
    control.mode.setCurrentIndex(2)
    np.testing.assert_array_equal(workspace.cube.counts, original)
    workspace.event_flags.raw_first.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    workspace.event_flags.raw_all.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    np.testing.assert_array_equal(workspace.cube.counts, original)


def test_ptu_simulation_choice_still_excludes_events(raw_dataset, tmp_path):
    """A requested simulation never creates fabricated PTU events."""
    window = ReflectionWindow(
        raw_dataset.key, 9.5, 12.5, mode="simulate", seed=123
    )
    result = export_ptu_blocks(
        [raw_dataset],
        tmp_path,
        PtuExportOptions(event_flag_mask=256, reflection_windows=(window,)),
        plane_selection={raw_dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    assert inspect_ptu(Path(result["path"])).microtime[10:13].sum() == 0
    sidecar = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
    info = sidecar["export"]["reflectionFilter"]
    assert info["requestedMode"] == "simulate"
    assert info["appliedMode"] == "exclude events"
    assert not info["containsSyntheticSamples"]
    assert info["randomSeed"] is None
