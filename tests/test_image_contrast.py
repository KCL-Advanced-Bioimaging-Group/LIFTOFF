"""Draggable display levels preserve scientific data and ROI state."""

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QFont, QPainter
from PySide6.QtWidgets import QApplication, QMenu

from leica_flim_converter.gui_canvas import ImageCanvas
from leica_flim_converter.gui_intensity_levels import IntensityDistribution
from tests.test_gui import workspace_fixture
from tests.test_reflection_filter import _place

preview_fixture = workspace_fixture


def _drag(qtbot, contrast, start, end):
    rect = contrast.plot_rect()
    y = round(rect.center().y())
    distribution = contrast.distributions[contrast.active_index]
    low, high = distribution.axis_limits()
    first = QPoint(
        round(
            rect.left()
            + (distribution.quantile(start) - low)
            / (high - low)
            * rect.width()
        ),
        y,
    )
    last = QPoint(
        round(
            rect.left()
            + (distribution.quantile(end) - low) / (high - low) * rect.width()
        ),
        y,
    )
    qtbot.mousePress(contrast, Qt.MouseButton.LeftButton, pos=first)
    qtbot.mouseMove(contrast, last)
    qtbot.mouseRelease(contrast, Qt.MouseButton.LeftButton, pos=last)


def test_image_levels_and_reset(qtbot):
    """Stretch brightness reversibly without changing input or ROIs."""
    canvas = ImageCanvas()
    qtbot.addWidget(canvas)
    contrast = canvas.contrast
    qtbot.addWidget(contrast)
    contrast.resize(500, 112)
    contrast.show()
    counts = np.arange(1024, dtype=np.uint64).reshape(32, 32)
    original = counts.copy()
    canvas.set_counts(counts)
    assert canvas.image is not None
    image = canvas.image.copy()
    levels = contrast.levels.copy()
    assert not contrast.log_scale_button.isChecked()
    contrast.log_scale_button.click()
    contrast.grab()
    assert contrast.log_scale_button.isChecked()
    assert contrast.levels == levels
    assert canvas.image == image
    contrast.log_scale_button.click()
    canvas.rois = [(1, 2, 10, 12)]
    screenshot = contrast.grab().toImage()
    rect = contrast.plot_rect()
    x = round(rect.center().x())
    assert any(
        screenshot.pixelColor(x, y).blue()
        > screenshot.pixelColor(x, y).red() + 40
        for y in range(round(rect.top()), round(rect.bottom()) + 1)
    )
    assert contrast.frequencies.sum() == 1024
    _drag(qtbot, contrast, 0, 20)
    assert 19 < contrast.black_level < 21
    assert canvas.image != image
    _drag(qtbot, contrast, 99.8, 70)
    assert 69 < contrast.white_level < 71
    assert canvas.rois == [(1, 2, 10, 12)]
    np.testing.assert_array_equal(counts, original)
    _reset(contrast)
    assert canvas.image == image


@pytest.mark.parametrize(("width", "tick_count"), [(155, 2), (800, 5)])
def test_scientific_tick_labels_fit(qtbot, monkeypatch, width, tick_count):
    """Keep scientific labels complete near the widget edge."""
    ticks = []
    draw_text = QPainter.drawText

    def record_ticks(painter, box, alignment, label):
        if label == "0" or "e+" in label:
            advance = painter.fontMetrics().horizontalAdvance(label)
            ticks.append((box, label, advance))
        return draw_text(painter, box, alignment, label)

    monkeypatch.setattr(QPainter, "drawText", record_ticks)
    canvas = ImageCanvas()
    qtbot.addWidget(canvas)
    contrast = canvas.contrast
    font = QFont("Arial")
    font.setPixelSize(12)
    contrast.setFont(font)
    contrast.resize(width, contrast.height())
    canvas.set_counts(np.array([[0, 2_260_000]], dtype=np.uint64))
    contrast.grab()

    assert ticks[0][1] == "0"
    assert ticks[-1][1] == "2.26e+06"
    assert len(ticks) >= tick_count
    previous_right = 0.0
    for box, _label, advance in ticks:
        assert box.width() >= advance
        assert previous_right <= box.left() < box.right() <= width
        previous_right = box.right()


def test_multichannel_levels_and_reflection(qtbot, workspace):
    """Keep contrast when reflection photons return to a composite."""
    contrast = workspace.image.contrast
    _place(workspace, qtbot)
    assert len(contrast.groups) == 2
    assert contrast.panels is not None
    panel = contrast.panels[1]
    image = workspace.image.image
    assert image is not None
    untouched = image.copy(
        panel["composite_x"], 0, panel["image"].width(), image.height()
    )
    _drag(qtbot, contrast, 99.8, 70)
    image = workspace.image.image
    assert image is not None
    assert (
        image.copy(
            panel["composite_x"], 0, panel["image"].width(), image.height()
        )
        == untouched
    )
    assert contrast.levels[1] == (0, 99.8)
    original = workspace.image.image.copy()
    workspace.reflection_filter.checkbox.click()
    assert contrast.white_level < 71
    workspace.reflection_filter.checkbox.click()
    assert workspace.image.image == original
    assert workspace.decode_worker is None
    first_levels = contrast.levels[0]
    contrast.active_index = 1
    _drag(qtbot, contrast, 99.8, 60)
    assert contrast.levels[0] == first_levels
    assert 58 < contrast.levels[1][1] < 62
    _reset(contrast)
    assert contrast.levels == [first_levels, (0, 99.8)]


def _reset(contrast):
    point = contrast.plot_rect().center().toPoint()
    QApplication.sendEvent(
        contrast,
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, point, contrast.mapToGlobal(point)
        ),
    )
    menu = contrast.findChildren(QMenu)[-1]
    assert menu.actions()[0].text() == "Reset (P0 - P99.8)"
    menu.actions()[0].trigger()
    menu.close()


def test_unclipped_original_percentiles():
    """Include zeros and an unclipped extreme when resolving P100."""
    values = np.array(
        [0] * 900 + list(range(1, 100)) + [1_000_000], dtype=np.uint64
    )
    distribution = IntensityDistribution([values.reshape(20, 50)])
    assert distribution.counts.sum() == 1000
    assert distribution.values[-1] == 1_000_000
    for percentile in (0, 1, 50, 90, 99.8, 100):
        np.testing.assert_allclose(
            distribution.quantile(percentile),
            np.percentile(values, percentile),
        )
    assert distribution.quantile(0) == 0
    assert distribution.quantile(100) == 1_000_000
    assert distribution.quantile(99.8) < 1_000_000


def test_histogram_uses_equal_intensity_bins():
    """Keep gaps and peaks on an evenly spaced intensity axis."""
    distribution = IntensityDistribution([np.array([3, 3, 3, 5, 5, 8])])
    centres, counts = distribution.curve()
    np.testing.assert_array_equal(centres, [3, 4, 5, 6, 7, 8])
    np.testing.assert_array_equal(counts, [3, 0, 2, 0, 0, 1])
    assert distribution.axis_limits() == (3, 8)
    for intensity in (3, 3.5, 5, 7, 8):
        np.testing.assert_allclose(
            distribution.quantile(distribution.percentile(intensity)),
            intensity,
        )
    values = np.r_[np.arange(1024), [1_000_000] * 5]
    distribution = IntensityDistribution([values])
    centres, counts = distribution.curve()
    expected, _edges = np.histogram(values, bins=256, range=(0, 1_000_000))
    np.testing.assert_array_equal(counts, expected)
    np.testing.assert_allclose(np.diff(centres), np.diff(centres)[0])
    assert counts.sum() == values.size
