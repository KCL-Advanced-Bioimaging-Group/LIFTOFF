"""Canvas mouse events restore the correct default graph data."""

# Inspect the production canvas mapping and graph state.
# pylint: disable=protected-access

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_canvas import ImageCanvas
from tests.mosaic_fixture import mosaic_lif
from tests.test_mosaic_gui import _open_mosaic
from tests.test_reference_science import example_path


def _move_cursor(canvas: ImageCanvas, point: QPoint) -> None:
    # Dispatch widget events without depending on desktop focus.
    QApplication.sendEvent(
        canvas,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(canvas.mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def _move_to_image(window: MainWindow, x: float, y: float) -> tuple[int, int]:
    canvas = window.image
    base, source = canvas._base_image_rect_2(), canvas._source_rect_2()
    point = QPoint(
        round(
            base.left() + (x - source.left()) / source.width() * base.width()
        ),
        round(
            base.top() + (y - source.top()) / source.height() * base.height()
        ),
    )
    pixel = canvas._pixel(point)
    assert pixel is not None
    _move_cursor(canvas, point)
    return pixel


def _assert_all_pixels(window: MainWindow, separate: bool) -> None:
    plot = window.histogram
    panels = window._multichannel_channel_panels
    assert panels is not None
    excluded = sum(panel["cube"].overflow_events for panel in panels)
    assert (
        f"excludes {excluded:,} selected photons"
        in window.fields["Histogram cube"].toolTip()
    )
    expected = [panel["values"] for panel in panels]
    if not separate:
        expected = [np.sum(expected, axis=0, dtype=np.uint64)]
    assert plot.multichannel_scope == "All Pixels"
    graphs = plot.graph_panels()
    assert len(graphs) == len(expected)
    for graph, values in zip(graphs, expected, strict=True):
        np.testing.assert_array_equal(graph["series"][0][1], values)
    plot.repaint()
    assert len(plot._last_histogram_layout["panels"]) == len(expected)


@pytest.mark.parametrize(
    ("real", "mode"),
    [
        (False, 256),
        (False, 512),
        (False, 1024),
        pytest.param(True, 1024, marks=pytest.mark.real_data),
    ],
)
def test_hover_restores_all_pixels(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    real: bool,
    mode: int,
) -> None:
    """Margins, tile gaps and leaving the canvas restore defaults."""
    source = (
        example_path("HCC1954 mS3-mitoPyr-ShadowR.lif")
        if real
        else mosaic_lif(tmp_path / "tiles.lif")
    )
    if source is None:
        pytest.skip("Optional Navigator mosaic is unavailable")
    window = _open_mosaic(
        source, "R1 (4)" if real else "Mosaic", qtbot, monkeypatch
    )
    window.event_flags.set_mask(mode, emit=True)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    panels = window._multichannel_channel_panels
    assert panels is not None
    target = panels[3]
    x = target["composite_x"] + target["dataset"].width / 2
    y = (
        target["composite_y"]
        + target["header_height"]
        + target["dataset"].height / 2
    )
    margin = QPoint(window.image.width() - 2, window.image.height() // 2)
    assert window.image._pixel(margin) is None
    for separate in (False, True):
        window.histogram.separate_tiles_button.setChecked(separate)
        _assert_all_pixels(window, separate)
        for destination in ("margin", "gap", "leave"):
            pixel = _move_to_image(window, x, y)
            assert "pixel (" in window.histogram.multichannel_scope
            local_x = pixel[0] - target["composite_x"]
            local_y = (
                pixel[1] - target["composite_y"] - target["header_height"]
            )
            values = target["cube"].pixel(local_x, local_y)
            graphs = window.histogram.graph_panels()
            np.testing.assert_array_equal(
                graphs[3 if separate else 0]["series"][0][1], values
            )
            if separate:
                for graph, panel in zip(graphs[:3], panels[:3], strict=True):
                    np.testing.assert_array_equal(
                        graph["series"][0][1], panel["values"]
                    )
            if destination == "margin":
                _move_cursor(window.image, margin)
            elif destination == "gap":
                _move_to_image(window, x, target["composite_y"] + 0.5)
            else:
                QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
            _assert_all_pixels(window, separate)
    if real:
        path = Path(
            "validation_artifacts/screenshots/mosaic-hover-restored.png"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(path))


def test_leaving_hover_preserves_active_roi(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaving the image keeps explicitly selected ROI curves."""
    window = _open_mosaic(
        mosaic_lif(tmp_path / "tiles.lif"), "Mosaic", qtbot, monkeypatch
    )
    layout = window.image.multichannel_mirror_layout[0]
    window.image.rois = [
        (
            layout["x"],
            layout["header"],
            layout["x"] + layout["width"],
            layout["header"] + layout["height"],
        )
    ]
    window.image.roi_colors = [QColor("#38bdf8")]
    window.image.activated_rois = {0}
    window._refresh_roi_histogram()
    expected = window.histogram.graph_panels()[0]["series"][0][1].copy()
    _move_to_image(window, layout["x"] + 1, layout["header"] + 1)
    QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
    assert window.histogram.multichannel_scope == "Activated ROIs"
    assert window.image.activated_rois == {0}
    np.testing.assert_array_equal(
        window.histogram.graph_panels()[0]["series"][0][1], expected
    )
