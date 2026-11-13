"""Reflection shading, manual boundaries and intact histogram data."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_plot import HistogramPlot
from tests.test_reference_science import example_path
from tests.test_reflection import load_example_reflection, reflection_curve


def _plot(qtbot: QtBot, multiple: bool = False) -> HistogramPlot:
    plot = HistogramPlot()
    qtbot.addWidget(plot)
    plot.resize(1100, 370)
    counts = reflection_curve()
    plot.set_histogram(counts)
    if multiple:
        plot.multichannel_panels = [
            {
                "title": "Repeated channel label",
                "values": curve,
                "color": "blue",
            }
            for curve in (counts, reflection_curve(center=0.72))
        ]
    plot.show()
    qtbot.wait(1)
    return plot


def _rectangle(plot: HistogramPlot, index: int = 0) -> tuple:
    """Read diagnostic graph geometry after forcing a complete paint."""
    plot.grab()
    layout = getattr(plot, "_last_histogram_layout", {})
    return tuple(layout["panels"][index]["plotRect"])


@pytest.mark.parametrize("multiple", [False, True])
def test_reflection_controls_and_shading(qtbot: QtBot, multiple: bool) -> None:
    """Show independent intervals with black lines and grey fill."""
    plot = _plot(qtbot, multiple)
    markers = plot.reflection
    original = plot.series[0][1].copy()
    assert markers.detect_button.text() == "Auto-detect reflection peak"
    assert (
        markers.detect_button.y() > plot.log_scale_button.geometry().bottom()
    )
    assert (
        plot.histogram_content_top()
        > markers.detect_button.geometry().bottom()
    )
    for control in (markers.detect_button, markers.clear_button):
        assert plot.rect().contains(control.geometry())
    qtbot.mouseClick(markers.detect_button, Qt.MouseButton.LeftButton)
    plot.repaint()
    assert len(markers.regions) == (2 if multiple else 1)
    image = plot.grab().toImage()
    for index, (key, bounds) in enumerate(markers.regions.items()):
        left, top, right, bottom = _rectangle(plot, index)
        y = round((top + bottom) / 2)
        x0, x1 = (
            left + value / (key[2] - 1) * (right - left) for value in bounds
        )
        for x in (x0, x1):
            assert (
                min(
                    image.pixelColor(round(x) + offset, y).lightness()
                    for offset in (-1, 0, 1)
                )
                < 100
            )
        shade = image.pixelColor(round((x0 + x1) / 2), y)
        assert shade.red() == shade.green() == shade.blue() < 250
    np.testing.assert_array_equal(plot.series[0][1], original)
    regions = markers.regions.copy()
    plot.log_scale_button.click()
    plot.resize(1250, 420)
    plot.repaint()
    assert markers.regions == regions
    markers.clear_button.click()
    assert not markers.regions and not markers.clear_button.isEnabled()


def _drag_boundary(
    qtbot: QtBot, plot: HistogramPlot, boundary: int, target: float
) -> None:
    key, bounds = next(iter(plot.reflection.regions.items()))
    left, top, right, bottom = _rectangle(plot)
    origin = QPoint(
        round(left + bounds[boundary] / (key[2] - 1) * (right - left)),
        round((top + bottom) / 2),
    )
    destination = QPoint(round(left + target * (right - left)), origin.y())
    qtbot.mousePress(plot, Qt.MouseButton.LeftButton, pos=origin)
    qtbot.mouseMove(plot, destination)
    qtbot.mouseRelease(plot, Qt.MouseButton.LeftButton, pos=destination)
    plot.repaint()


def test_dragging_both_lines_and_preserving_annotations(qtbot: QtBot) -> None:
    """Keep bounds on ROI refresh and constrain dragging to bins."""
    plot = _plot(qtbot)
    markers = plot.reflection
    markers.detect_button.click()
    plot.repaint()
    _drag_boundary(qtbot, plot, 0, 0.7)
    _drag_boundary(qtbot, plot, 1, 0.9)
    bounds = next(iter(markers.regions.values()))
    assert bounds[0] == pytest.approx(0.7 * 255, abs=0.3)
    assert bounds[1] == pytest.approx(0.9 * 255, abs=0.3)
    plot.set_series([("ROI 1", reflection_curve() // 2, "orange")])
    plot.repaint()
    assert next(iter(markers.regions.values())) == bounds
    _drag_boundary(qtbot, plot, 0, 1.5)
    left, right = next(iter(markers.regions.values()))
    assert left == right - 1
    _drag_boundary(qtbot, plot, 0, -0.2)
    assert next(iter(markers.regions.values()))[0] == 0
    _drag_boundary(qtbot, plot, 1, 1.1)
    assert next(iter(markers.regions.values()))[1] == 255
    markers.detect_button.click()
    assert next(iter(markers.regions.values())) != (0, 255)
    plot.set_histogram(reflection_curve())
    assert not markers.regions


def test_no_detection_and_new_acquisition(qtbot: QtBot) -> None:
    """Report no peak, and discard annotations on a dataset change."""
    plot = _plot(qtbot)
    markers = plot.reflection
    markers.detect_button.click()
    plot.grab()
    plot.channel_owner = Mock(
        selected=None,
        current_plane=1,
        image=None,
        cube=None,
        decode_worker=None,
    )
    plot.grab()
    assert not markers.regions
    plot.set_histogram(np.arange(256, 0, -1, dtype=np.uint64))
    plot.grab()
    markers.detect_button.click()
    assert not markers.regions
    assert markers.status.text() == "No reflection peak detected."
    plot.set_message("Loading")
    plot.grab()
    assert not markers.detect_button.isEnabled()


@pytest.mark.parametrize("multiple", [False, True])
def test_detect_uses_all_pixels_even_during_roi_inspection(
    qtbot: QtBot, multiple: bool
) -> None:
    """Displayed curves cannot bias the whole-image peak detection."""
    plot = _plot(qtbot, multiple)
    markers = plot.reflection
    markers.detect_button.click()
    expected = markers.regions.copy()
    roi_curve = np.arange(256, 0, -1, dtype=np.uint64)
    plot.set_series([("Pixel 1, 1", roi_curve, "orange")])
    for panel in plot.multichannel_panels or ():
        panel["series"] = [("ROI 1", roi_curve, "orange")]
    plot.grab()
    markers.detect_button.click()
    assert markers.regions == expected
    assert expected
    np.testing.assert_array_equal(plot.series[0][1], roi_curve)
    if not multiple:
        plot.set_histogram(roi_curve)
        plot.set_series([("Misleading pixel", reflection_curve(), "blue")])
        plot.grab()
        markers.detect_button.click()
        assert not markers.regions


def test_mosaic_shares_whole_image_bounds_with_separate_tiles(
    qtbot: QtBot,
) -> None:
    """Use one interval from the pooled mosaic for all its tiles."""
    plot = _plot(qtbot)
    counts = reflection_curve()
    plot.multichannel_panels = [
        {
            "title": f"Tile {index}",
            "values": counts // (index + 1),
            "color": "blue",
            "photons": int((counts // (index + 1)).sum()),
            "mosaic_pair_key": "pair",
            "mosaic_pair_title": "Mosaic",
            "mosaic_tile_index": index,
        }
        for index in range(2)
    ]
    plot.update_mosaic_graph_controls()
    plot.grab()
    plot.reflection.detect_button.click()
    expected = plot.reflection.regions.copy()
    assert len(expected) == 1
    plot.separate_tiles_button.click()
    plot.grab()
    assert plot.reflection.regions == expected
    plot.reflection.detect_button.click()
    assert plot.reflection.regions == expected
    _drag_boundary(qtbot, plot, 0, 0.7)
    key, bounds = next(iter(plot.reflection.regions.items()))
    assert bounds[0] == pytest.approx(0.7 * 255, abs=0.6)
    image = plot.grab().toImage()
    for index in range(2):
        left, top, right, bottom = _rectangle(plot, index)
        x = round(left + bounds[0] / (key[2] - 1) * (right - left))
        y = round((top + bottom) / 2)
        assert (
            min(
                image.pixelColor(x + offset, y).lightness()
                for offset in (-1, 0, 1)
            )
            < 100
        )


@pytest.mark.real_data
def test_real_example_graph(qtbot: QtBot) -> None:
    """Render the supplied late reflection using a logarithmic axis."""
    counts, _key = load_example_reflection()
    plot = _plot(qtbot)
    plot.set_histogram(counts)
    plot.log_scale_button.click()
    plot.repaint()
    plot.reflection.detect_button.click()
    plot.repaint()
    assert next(iter(plot.reflection.regions.values())) == (209, 220)
    _drag_boundary(qtbot, plot, 0, 0.78)
    np.testing.assert_array_equal(plot.values, counts)


def open_example_workspace(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> MainWindow:
    """Open the supplied example using production controls."""
    source = example_path("CellMaskandmScar3.lif")
    if source is None:
        pytest.skip("Optional reflection example LIF is unavailable")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", lambda *args: ([str(source)], "")
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1500, 930)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=30000)
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            dataset := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and dataset.acquisition_name == "mScar3-Pyr_FLIM04_40MHz"
    )
    window.select_block(item)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    window.event_flags.raw_standard.click()
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    return window


@pytest.mark.real_data
def test_real_example_workspace(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open the example and retain markers on pixel inspection."""
    window = open_example_workspace(qtbot, monkeypatch)
    plot = window.histogram
    plot.log_scale_button.click()
    qtbot.wait(10)
    plot.reflection.detect_button.click()
    plot.repaint()
    regions = plot.reflection.regions.copy()
    assert list(regions.values()) == [(209, 220)]
    assert window.cube is not None
    cube = window.cube
    all_pixels = plot.series[0][1].copy()
    window.show_pixel(500, 500)
    plot.repaint()
    assert plot.reflection.regions == regions
    plot.reflection.detect_button.click()
    assert plot.reflection.regions == regions
    window.image.hover_ended.emit()
    plot.repaint()
    assert plot.reflection.regions == regions
    np.testing.assert_array_equal(plot.series[0][1], all_pixels)
    assert window.cube is cube and window.decode_worker is None
    # Retain a preview for visual review with the real window font.
    output = Path("validation_artifacts/reflection-peak")
    output.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(output / "example-log.png"))
    plot.log_scale_button.setChecked(False)
    qtbot.wait(10)
    assert plot.reflection.regions == regions
    assert window.grab().save(str(output / "example-linear.png"))
    plot.reflection.clear_button.click()
    assert not plot.reflection.regions
