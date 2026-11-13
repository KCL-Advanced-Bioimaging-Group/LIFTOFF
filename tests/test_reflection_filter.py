"""Reflection photon exclusion, graph gaps and reversible previews."""

# Inspect retained scientific cubes and ROI state behind the preview.
# pylint: disable=protected-access

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath
from pytestqt.qtbot import QtBot

from leica_flim_converter import gui_plot
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_canvas import image_from_counts
from leica_flim_converter.gui_helpers import (
    _compose_channel_images_2,
    _draw_histogram_curves,
)
from leica_flim_converter.gui_reflection_filter import filtered_intensity
from tests.test_gui import switch_to_single, workspace_fixture
from tests.test_multichannel_mosaic_gui import _open_matrix
from tests.test_reflection_gui import (
    _drag_boundary,
    _rectangle,
    open_example_workspace,
)
from tests.test_reflection_manual import _point, _start

preview_fixture = workspace_fixture


@pytest.mark.parametrize("bounds", [(4, 7), (4.2, 7.8), (0, 15), (0, 1)])
def test_excluded_bin_centres_and_wide_sums(bounds: tuple) -> None:
    """Exclude inclusive native bins without overflowing uint16."""
    counts = np.full((16, 4, 4), 65535, dtype=np.uint16)
    original = counts.copy()
    expected = np.zeros((4, 4), dtype=np.uint64)
    for index in range(16):
        if not bounds[0] <= index <= bounds[1]:
            expected += counts[index]
    actual = filtered_intensity(counts, bounds)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(counts, original)
    assert actual.dtype == np.uint64


def _place(window: MainWindow, qtbot: QtBot, panel: int = 0) -> None:
    """Use the manual two-click interaction to identify an interval."""
    plot = window.histogram
    _start(qtbot, plot)
    qtbot.mouseClick(
        plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.25, panel)
    )
    assert not window.reflection_filter.checkbox.isEnabled()
    qtbot.mouseClick(
        plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.65, panel)
    )
    assert window.reflection_filter.checkbox.isEnabled()


def _assert_band(window: MainWindow, white: bool, panel: int = 0) -> None:
    """Inspect the rendered band, away from the black boundary lines."""
    plot = window.histogram
    image = plot.grab().toImage()
    x = _point(plot, 0.45, panel).x()
    _, top, _, bottom = _rectangle(plot, panel)
    colors = [
        image.pixelColor(x, y)
        for y in range(round(top) + 2, round(bottom) - 2)
    ]
    if white:
        assert all(color == QColor("white") for color in colors)
    else:
        assert any(
            color.red() == color.green() == color.blue() < 250
            for color in colors
        )


def test_filter_single_image_restore_and_boundary_lock(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Filter both views, retain ROIs and unlock on restore."""
    switch_to_single(workspace, qtbot)
    control = workspace.reflection_filter
    assert control.checkbox.text() == ""
    assert not control.checkbox.isEnabled()
    assert control.status.text() == "No reflection peak identified."
    assert control.y() > workspace.event_flags.geometry().bottom()
    cube = workspace.cube
    assert cube is not None
    cube.counts[4:9, 1, 1] += 1000
    workspace.image.image = image_from_counts(cube.intensity)
    workspace.image.contrast.set_intensities([cube.intensity])
    original = cube.counts.copy()
    image = workspace.image.image.copy()
    workspace.image.rois = [(0, 0, 2, 2)]
    workspace.image.roi_colors = [QColor("orange")]
    workspace.image.activated_rois = {0}
    workspace._refresh_roi_histogram()
    workspace.image.view_zoom = 2.0
    _place(workspace, qtbot)
    markers = workspace.histogram.reflection
    regions = markers.regions.copy()
    bounds = next(iter(regions.values()))
    _assert_band(workspace, False)
    control.checkbox.click()
    assert workspace.image.image == image_from_counts(
        filtered_intensity(original, bounds)
    )
    assert workspace.image.image != image
    assert workspace.image.rois == [(0, 0, 2, 2)]
    assert workspace.image.activated_rois == {0}
    assert workspace.image.view_zoom == 2.0
    for button in (
        markers.detect_button,
        markers.manual_button,
        markers.clear_button,
    ):
        assert not button.isEnabled()
    _drag_boundary(qtbot, workspace.histogram, 0, 0.1)
    assert markers.regions == regions
    _assert_band(workspace, True)
    workspace.show_pixel(1, 1)
    workspace.histogram.log_scale_button.click()
    _assert_band(workspace, True)
    workspace._refresh_roi_histogram()
    _assert_band(workspace, True)
    workspace.clear_roi()
    assert control.checkbox.isChecked()
    assert markers.regions == regions
    _assert_band(workspace, True)
    np.testing.assert_array_equal(cube.counts, original)
    assert workspace.decode_worker is None
    control.checkbox.click()
    assert workspace.image.image == image
    assert markers.regions == regions
    _assert_band(workspace, False)
    _drag_boundary(qtbot, workspace.histogram, 0, 0.1)
    assert markers.regions != regions
    markers.clear_button.click()
    assert not control.checkbox.isEnabled()
    assert control.status.text() == "No reflection peak identified."


def test_channel_filter_and_new_event_selection(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Reapply saved native bounds after event selection changes."""
    panels = workspace._multichannel_channel_panels
    assert panels is not None and len(panels) == 2
    original = workspace.image.image
    assert original is not None
    originals = [panel["cube"].counts.copy() for panel in panels]
    _place(workspace, qtbot)
    bounds = next(iter(workspace.histogram.reflection.regions.values()))
    expected = [panel.copy() for panel in panels]
    expected[0]["image"] = image_from_counts(
        filtered_intensity(originals[0], bounds)
    )
    workspace.reflection_filter.checkbox.click()
    assert workspace.image.image == _compose_channel_images_2(expected)
    _assert_band(workspace, True)
    for panel, counts in zip(panels, originals, strict=True):
        np.testing.assert_array_equal(panel["cube"].counts, counts)
    workspace.reflection_filter.checkbox.click()
    assert workspace.image.image == original
    workspace.reflection_filter.checkbox.click()
    workspace.event_flags.raw_first.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.reflection_filter.checkbox.isChecked()
    assert workspace.reflection_filter.checkbox.isEnabled()
    assert list(workspace.histogram.reflection.regions.values()) == [bounds]
    assert workspace.image.image == _compose_channel_images_2(expected)
    workspace.reflection_filter.checkbox.click()
    assert workspace.image.image == original


@pytest.mark.parametrize("logarithmic", [False, True])
def test_curve_filter_breaks_paths(logarithmic: bool) -> None:
    """Break paths across omitted bins on both graph scales."""
    painter = Mock()
    counts = np.array([100, 80, 60, 40, 20, 10], dtype=np.uint64)
    _draw_histogram_curves(
        painter,
        [("All pixels", counts, QColor("blue"))],
        QRectF(0, 0, 500, 100),
        100,
        logarithmic,
        omitted=(2, 3),
    )
    path = painter.drawPath.call_args.args[0]
    assert [path.elementAt(i).x for i in range(path.elementCount())] == [
        0,
        100,
        400,
        500,
    ]
    assert path.elementAt(2).type == QPainterPath.ElementType.MoveToElement


def test_mosaic_filter_shares_channel_bounds(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Apply one channel's bounds to all its tiles and graph layouts."""
    window = _open_matrix(tmp_path, qtbot, monkeypatch)
    panels = window._multichannel_channel_panels
    assert panels is not None
    original = window.image.image
    _place(window, qtbot)
    key, bounds = next(iter(window.histogram.reflection.regions.items()))
    expected = [panel.copy() for panel in panels]
    for panel in expected:
        if panel["dataset"].pair_key == key[0]:
            panel["image"] = image_from_counts(
                filtered_intensity(panel["cube"].counts, bounds)
            )
    window.reflection_filter.checkbox.click()
    assert window.image.image == _compose_channel_images_2(expected)
    window.histogram.separate_tiles_button.click()
    window.histogram.grab()
    for index, graph in enumerate(window.histogram.graph_panels()):
        graph_key = window.histogram.reflection.graph_key(
            graph, graph["values"].size, index
        )
        assert window.histogram.reflection.omitted(graph_key) == (
            bounds if graph["mosaic_pair_key"] == key[0] else None
        )
    window.reflection_filter.checkbox.click()
    assert window.image.image == original


@pytest.mark.real_data
def test_example_reflection_filter(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exclude the measured reflection in the supplied acquisition."""
    window = open_example_workspace(qtbot, monkeypatch)
    cube = window.cube
    assert cube is not None
    plot = window.histogram
    plot.reflection.detect_button.click()
    bounds = next(iter(plot.reflection.regions.values()))
    original = window.image.image
    total = int(cube.counts.sum(dtype=np.uint64))
    expected = filtered_intensity(cube.counts, bounds)
    curves = Mock(wraps=_draw_histogram_curves)
    monkeypatch.setattr(gui_plot, "_draw_histogram_curves", curves)
    window.reflection_filter.checkbox.click()
    plot.log_scale_button.click()
    plot.grab()
    assert curves.call_args.kwargs["omitted"] == bounds
    assert window.image.image == image_from_counts(expected)
    removed = total - int(expected.sum())
    assert removed > 0
    assert (
        f"{removed:,} photons filtered"
        in window.reflection_filter.status.text()
    )
    target = Path("validation_artifacts/reflection-peak/filtered-example.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    qtbot.wait(200)
    assert window.grab().save(str(target))
    window.reflection_filter.checkbox.click()
    assert window.image.image == original
    assert int(cube.counts.sum(dtype=np.uint64)) == total
