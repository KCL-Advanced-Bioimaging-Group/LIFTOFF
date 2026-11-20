"""Missing counts and shared log-linear reflection interpolation."""

# Exercise the public preview through its retained source references.
# pylint: disable=protected-access

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from leica_flim_converter import gui_reflection
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.gui_helpers import _draw_histogram_curves
from leica_flim_converter.histogram_core import HistogramCube
from leica_flim_converter.ics import write_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.reflection_export import ReflectionWindow
from leica_flim_converter.reflection_processing import corrected_counts
from leica_flim_converter.timing import native_source_grid, time_grid
from tests.test_gui import switch_to_single, workspace_fixture
from tests.test_reflection_filter import _place

preview_fixture = workspace_fixture


@pytest.fixture(name="raw_dataset")
def numeric_export_dataset(raw_dataset):
    """Use a 128-bin native period for numeric export checks."""
    return replace(raw_dataset, laser_frequency_hz=78_125_000.0)


def test_exponential_repair_and_empty_pixels():
    """Recover a shared exponential even with entirely empty pixels."""
    expected = 100 * np.exp(-np.arange(16) / 4)
    original = np.broadcast_to(expected[:, None, None], (16, 2, 2)).copy()
    original[5:9] = 10000
    original[:, 1, 1] = 0
    repaired = corrected_counts(original, (4.2, 8.7), "interpolate")
    np.testing.assert_allclose(repaired[5:9, 0, 0], expected[5:9])
    assert np.all(repaired[5:9, 1, 1] == 0)
    np.testing.assert_array_equal(repaired[:5], original[:5])
    np.testing.assert_array_equal(repaired[9:], original[9:])
    assert np.all(original[5:9, 0, 0] == 10000)


def test_sparse_pixels_use_one_shared_decay():
    """Finite summed shoulders repair individually undefined pixels."""
    counts = np.zeros((16, 3, 3), dtype=np.uint32)
    counts[:, 0, 0] = 100
    counts[:, 1, 1] = 200
    counts[3, 2, 2] = 50
    counts[5:9] += 1000
    original = counts.copy()
    repaired = corrected_counts(counts, (5, 8), "interpolate")
    whole = counts.sum((1, 2), dtype=np.uint64)
    expected = corrected_counts(whole, (5, 8), "interpolate")
    np.testing.assert_allclose(repaired.sum((1, 2)), expected)
    assert np.isfinite(repaired).all()
    retained = counts[:5].sum(0) + counts[9:].sum(0)
    weights = retained / retained.sum()
    for index in range(5, 9):
        np.testing.assert_allclose(repaired[index], expected[index] * weights)
    np.testing.assert_array_equal(repaired[:5], counts[:5])
    np.testing.assert_array_equal(repaired[9:], counts[9:])
    np.testing.assert_array_equal(counts, original)


def test_missing_whole_image_shoulders_stay_nan():
    """A bridge requires two positive whole-image count endpoints."""
    counts = np.ones((16, 3, 3), dtype=np.uint32)
    counts[4] = 0
    repaired = corrected_counts(counts, (5, 8), "interpolate")
    assert np.isnan(repaired[5:9]).all()


def test_loglinear_bridge_uses_only_count_endpoints():
    """The bridge is independent of neighbouring slope estimates."""
    logs = np.zeros(14)
    logs[2:4] = (10, 4)
    logs[9:11] = (2, 0)
    counts = np.exp(logs)
    repaired = corrected_counts(counts, (4, 8), "interpolate")
    interior = np.arange(4, 9)
    expected_logs = 4 - (interior - 3) / 3
    np.testing.assert_allclose(np.log(repaired[4:9]), expected_logs)
    slopes = np.gradient(np.log(repaired))
    np.testing.assert_allclose(slopes[4:9], -1 / 3)
    assert repaired[9] == counts[9]
    changed = counts.copy()
    changed[2] = 1
    changed[10] = 1e9
    changed[4:9] = 1e12
    other = corrected_counts(changed, (4, 8), "interpolate")
    np.testing.assert_array_equal(other[4:9], repaired[4:9])


@pytest.mark.parametrize("mode", ["nan", "interpolate"])
def test_edges_remain_missing(mode):
    """Insufficient exterior samples never produce fabricated counts."""
    result = corrected_counts(np.ones(12), (0, 3), mode)
    assert np.isnan(result[:4]).all()
    np.testing.assert_array_equal(result[4:], 1)


@pytest.mark.parametrize("compression", ["gzip", "uncompressed"])
def test_real_ics_preserves_nan_fraction_and_orientation(
    raw_dataset, tmp_path, compression
):
    """Independently read actual floating-point ICS payloads."""
    counts = np.arange(64, dtype=np.float64).reshape(16, 2, 2) / 7
    counts[4:8, 0, 1] = np.nan
    path = tmp_path / "float.ics"
    report = write_ics(path, counts, raw_dataset, compression)
    image = read_ics(path)
    np.testing.assert_array_equal(image.counts, counts.astype(np.float32))
    assert image.header["representation/format"] == ["real"]
    assert image.header["representation/sign"] == ["signed"]
    assert report["bits"] == 32 and report["missingSamples"] == 4


@pytest.mark.parametrize("mode", ["nan", "interpolate"])
@pytest.mark.parametrize("bins", [None, 32])
def test_export_repairs_pixels_before_grouping(
    raw_dataset, tmp_path, mode, bins
):
    """ICS retains repaired pixels; PTU removes actual events."""
    grid = native_source_grid(raw_dataset, time_grid(raw_dataset, bins))
    counts = np.ones((grid.bins, 2, 2), dtype=np.uint16) * 100
    counts[5:9] = 1000
    cube = HistogramCube(
        counts,
        int(counts.sum()),
        0,
        grid.bins,
        2,
        source_dataset_key=raw_dataset.key,
        linear_plane=0,
        event_flag_mask=256,
        time_grid=grid,
    )
    window = ReflectionWindow(raw_dataset.key, 4.2, 8.5, mode=mode)
    report = export_ics_blocks(
        [raw_dataset],
        tmp_path / "ics",
        IcsExportOptions(
            bins=bins, event_flag_mask=256, reflection_windows=(window,)
        ),
        cached_cubes={raw_dataset.key: cube},
        plane_selection={raw_dataset.key: [0]},
    )[0]
    assert report["status"] == "exported", report
    output = read_ics(Path(report["path"])).counts
    expected = corrected_counts(counts, (4.2, 8.5), mode)
    target = time_grid(raw_dataset, bins)
    for index in range(target.bins):
        sources = target.indices(np.arange(grid.bins)) == index
        np.testing.assert_array_equal(
            output[index], expected[sources].sum(0).astype(output.dtype)
        )
    metadata = json.loads(Path(report["sidecar"]).read_text(encoding="utf-8"))
    assert metadata["reflectionFilter"]["mode"] == mode
    accounting = metadata["photonAccounting"]
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
    ptu = export_ptu_blocks(
        [raw_dataset],
        tmp_path / "ptu",
        PtuExportOptions(event_flag_mask=256, reflection_windows=(window,)),
        plane_selection={raw_dataset.key: [0]},
    )[0]
    assert ptu["status"] == "exported", ptu
    assert inspect_ptu(Path(ptu["path"])).microtime[5:9].sum() == 0


def test_preview_modes_pixel_roi_restore(workspace, qtbot):
    """Share per-pixel repairs across curves and restore raw counts."""
    switch_to_single(workspace, qtbot)
    original = workspace.cube
    assert original is not None
    original.counts[:] = 100
    original.counts[5:9] = 1000
    source = original.counts.copy()
    _place(workspace, qtbot)
    control = workspace.reflection_filter
    assert control.mode.currentText() == "Assign to NaNs"
    control.checkbox.click()
    assert workspace.cube is not original
    assert np.isnan(workspace.cube.counts).any()
    control.mode.setCurrentIndex(1)
    derived = workspace.cube
    assert derived.reflection_processing["mode"] == "interpolate"
    workspace.show_pixel(1, 1)
    np.testing.assert_array_equal(
        workspace.histogram.series[0][1], derived.pixel(1, 1)
    )
    workspace.image.rois = [(0, 0, 2, 2)]
    workspace.image.activated_rois = {0}
    workspace._refresh_roi_histogram()
    np.testing.assert_array_equal(
        workspace.histogram.series[0][1], derived.roi(0, 0, 2, 2)
    )
    assert control.export_windows()[0].mode == "interpolate"
    workspace.histogram.grab()  # Exercise dashed rendering.
    control.checkbox.click()
    assert workspace.cube is original
    np.testing.assert_array_equal(original.counts, source)


def test_dashed_curve_pen_and_nan_break():
    """Painter accepts fractional counts and NaNs with dashed pens."""
    image = QImage(200, 100, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    _draw_histogram_curves(
        painter,
        [("repair", np.array([1.5, np.nan, 2.3]), "blue")],
        image.rect().toRectF(),
        3,
        line_style=Qt.PenStyle.DashLine,
    )
    assert painter.pen().style() == Qt.PenStyle.DashLine
    painter.end()


def test_saved_modes_and_mixed_channel_restore(workspace, qtbot, monkeypatch):
    """Keep channel modes in previews and export snapshots."""
    monkeypatch.setattr(
        gui_reflection, "detect_reflection_peak", lambda _: (4, 8)
    )
    switch_to_single(workspace, qtbot)
    control = workspace.reflection_filter
    workspace.histogram.reflection.detect_button.click()
    control.mode.setCurrentIndex(1)
    control.checkbox.click()
    snapshot = control.export_windows()
    assert snapshot[0].mode == "interpolate"
    workspace.pair_selector.set_selection([workspace.datasets[1].key])
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert control.mode.currentData() == "nan"
    workspace.histogram.reflection.detect_button.click()
    control.checkbox.click()
    workspace.pair_selector.set_selection(
        [item.key for item in workspace.datasets]
    )
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert control.mode.currentIndex() == -1
    assert {window.mode for window in control.export_windows()} == {
        "nan",
        "interpolate",
    }
    assert {
        panel["cube"].reflection_processing["mode"]
        for panel in workspace._multichannel_channel_panels
    } == {"nan", "interpolate"}
    assert snapshot[0].mode == "interpolate"
    control.mode.setCurrentIndex(0)
    assert all(window.mode == "nan" for window in control.export_windows())


def test_unavailable_shared_model_reports_missing_data(workspace, qtbot):
    """Do not claim successful interpolation for undefined shoulders."""
    switch_to_single(workspace, qtbot)
    workspace.cube.counts[:] = 0
    _place(workspace, qtbot)
    control = workspace.reflection_filter
    control.mode.setCurrentIndex(1)
    control.checkbox.click()
    assert "Interpolation unavailable" in control.status.text()
    assert not workspace.cube.reflection_processing["interpolationAvailable"]
