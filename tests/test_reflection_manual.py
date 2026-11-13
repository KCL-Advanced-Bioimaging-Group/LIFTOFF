"""Manual reflection placement, pointer prompts and shared markers."""

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from leica_flim_converter.gui_plot import HistogramPlot
from tests.test_reflection import reflection_curve
from tests.test_reflection_gui import (
    _drag_boundary,
    _plot,
    _rectangle,
    open_example_workspace,
)


def _point(plot: HistogramPlot, fraction: float, panel: int = 0) -> QPoint:
    left, top, right, bottom = _rectangle(plot, panel)
    return QPoint(
        round(left + fraction * (right - left)),
        round(top + 0.25 * (bottom - top)),
    )


def _start(qtbot: QtBot, plot: HistogramPlot) -> None:
    plot.grab()
    qtbot.mouseClick(plot.reflection.manual_button, Qt.MouseButton.LeftButton)
    assert plot.reflection.manual.active
    assert plot.reflection.manual_button.isChecked()
    assert plot.reflection.manual.prompt.isVisible()
    assert plot.reflection.manual.prompt.text() == "Please drop first boundary"


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("logarithmic", [False, True])
def test_manual_boundaries_in_either_order(
    qtbot: QtBot, reverse: bool, logarithmic: bool
) -> None:
    """Place a line, then a shaded interval, with no count changes."""
    plot = _plot(qtbot)
    if logarithmic:
        plot.log_scale_button.click()
    markers = plot.reflection
    original = plot.values.copy()
    first, second = (0.86, 0.78) if reverse else (0.78, 0.86)
    _start(qtbot, plot)
    assert markers.manual_button.text() == "Manually-detect reflection peak"
    assert markers.manual.timer.isActive()
    probe = _point(plot, 0.82)
    before = plot.grab().toImage().pixelColor(probe)
    point = _point(plot, first)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=point)
    assert not markers.regions
    assert markers.manual.pending is not None
    assert markers.manual.prompt.text() == "Please drop second boundary"
    assert markers.manual.prompt.isVisible()
    image = plot.grab().toImage()
    assert (
        min(
            image.pixelColor(point.x() + offset, point.y()).lightness()
            for offset in (-1, 0, 1)
        )
        < 100
    )
    assert image.pixelColor(probe) == before
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, second))
    bounds = next(iter(markers.regions.values()))
    np.testing.assert_allclose(bounds, np.array([0.78, 0.86]) * 255, atol=0.3)
    assert not markers.manual.active
    assert not markers.manual.pending
    assert not markers.manual.prompt.isVisible()
    assert not markers.manual.timer.isActive()
    assert not markers.manual_button.isChecked()
    shade = plot.grab().toImage().pixelColor(probe)
    assert shade.red() == shade.green() == shade.blue() < before.red()
    np.testing.assert_array_equal(plot.values, original)
    _drag_boundary(qtbot, plot, 0, 0.7)
    assert next(iter(markers.regions.values()))[0] == pytest.approx(
        0.7 * 255, abs=0.3
    )
    regions = markers.regions.copy()
    plot.set_series([("ROI 1", original // 2, "orange")])
    plot.log_scale_button.click()
    plot.grab()
    assert markers.regions == regions


def test_manual_prompt_follows_pointer_and_ignores_margins(
    qtbot: QtBot,
) -> None:
    """Show a persistent prompt without counting non-graph clicks."""
    plot = _plot(qtbot)
    _start(qtbot, plot)
    manual = plot.reflection.manual
    prompt_positions = []
    for point in (QPoint(120, 150), QPoint(240, 150)):
        pointer = plot.mapToGlobal(point)
        QApplication.sendEvent(
            plot,
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(point),
                QPointF(pointer),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        assert manual.prompt.isVisible()
        assert not manual.prompt.geometry().contains(pointer)
        prompt_positions.append(manual.prompt.pos())
    assert prompt_positions[0] != prompt_positions[1]
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=QPoint(10, 200))
    qtbot.mouseClick(plot, Qt.MouseButton.RightButton, pos=_point(plot, 0.8))
    assert manual.pending is None
    assert manual.prompt.text() == "Please drop first boundary"
    position = _point(plot, 0.8)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=position)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=position)
    assert manual.active and manual.pending is not None
    assert manual.prompt.text() == "Please drop second boundary"
    assert not plot.reflection.regions


@pytest.mark.parametrize(
    "action", ["escape", "toggle", "clear", "auto", "load", "hide"]
)
def test_cancel_manual_placement(qtbot: QtBot, action: str) -> None:
    """Cancel a partial interval or switch to automatic detection."""
    plot = _plot(qtbot)
    markers = plot.reflection
    markers.detect_button.click()
    original = markers.regions.copy()
    _start(qtbot, plot)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.6))
    assert markers.regions == original
    if action == "escape":
        qtbot.keyClick(plot, Qt.Key.Key_Escape)
    elif action == "toggle":
        qtbot.mouseClick(markers.manual_button, Qt.MouseButton.LeftButton)
    elif action == "clear":
        markers.clear_button.click()
    elif action == "auto":
        markers.detect_button.click()
    elif action == "load":
        plot.set_histogram(reflection_curve())
    else:
        plot.hide()
    assert not markers.manual.active
    assert not markers.manual.prompt.isVisible()
    assert not markers.manual.timer.isActive()
    assert not markers.manual_button.isChecked()
    assert markers.regions == ({} if action in ("clear", "load") else original)


def test_both_manual_clicks_use_one_recorded_channel(qtbot: QtBot) -> None:
    """Different channel axes cannot contribute one boundary each."""
    plot = _plot(qtbot, multiple=True)
    _start(qtbot, plot)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.8))
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.9, 1))
    assert plot.reflection.manual.active
    assert not plot.reflection.regions
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.9))
    assert len(plot.reflection.regions) == 1
    assert next(iter(plot.reflection.regions))[0] == "graph:0"


def test_manual_mosaic_interval_is_shared_between_tiles(qtbot: QtBot) -> None:
    """Place on separate tiles with one shared image interval."""
    plot = _plot(qtbot)
    counts = reflection_curve()
    template = {
        "values": counts,
        "color": "blue",
        "photons": int(counts.sum()),
        "mosaic_pair_key": "pair",
        "mosaic_pair_title": "Mosaic",
    }
    plot.multichannel_panels = [
        dict(template, title=f"Tile {index}", mosaic_tile_index=index)
        for index in range(2)
    ]
    plot.update_mosaic_graph_controls()
    plot.separate_tiles_button.click()
    _start(qtbot, plot)
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.9))
    qtbot.mouseClick(plot, Qt.MouseButton.LeftButton, pos=_point(plot, 0.8, 1))
    assert len(plot.reflection.regions) == 1
    bounds = next(iter(plot.reflection.regions.values()))
    np.testing.assert_allclose(bounds, np.array([0.8, 0.9]) * 255, atol=0.6)
    for panel in (0, 1):
        shade = plot.grab().toImage().pixelColor(_point(plot, 0.85, panel))
        assert shade.red() == shade.green() == shade.blue() < 250
    regions = plot.reflection.regions.copy()
    plot.separate_tiles_button.click()
    plot.grab()
    assert plot.reflection.regions == regions


def test_manual_controls_fit_and_are_disabled_without_a_curve(
    qtbot: QtBot,
) -> None:
    """Wrap controls without covering plots in narrow windows."""
    plot = _plot(qtbot)
    buttons = (
        plot.reflection.manual_button,
        plot.reflection.detect_button,
        plot.reflection.clear_button,
    )
    for width in (350, 650, 1100):
        plot.resize(width, 370)
        plot.grab()
        for index, button in enumerate(buttons):
            assert plot.rect().contains(button.geometry())
            assert plot.histogram_content_top() > button.geometry().bottom()
            for other in buttons[index + 1 :]:
                assert not button.geometry().intersects(other.geometry())
    plot.set_message("Loading")
    plot.grab()
    assert not plot.reflection.manual_button.isEnabled()


@pytest.mark.real_data
def test_manual_placement_on_supplied_example(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify prompts and manual bounds on the actual LIF preview."""
    window = open_example_workspace(qtbot, monkeypatch)
    plot = window.histogram
    plot.log_scale_button.click()
    original = plot.series[0][1].copy()
    cube = window.cube
    output = Path("validation_artifacts/reflection-peak")
    output.mkdir(parents=True, exist_ok=True)
    _start(qtbot, plot)
    assert plot.reflection.manual.prompt.grab().save(
        str(output / "manual-first-prompt.png")
    )
    qtbot.mouseClick(
        plot, Qt.MouseButton.LeftButton, pos=_point(plot, 220 / 264)
    )
    assert window.grab().save(str(output / "manual-first-boundary.png"))
    assert plot.reflection.manual.prompt.grab().save(
        str(output / "manual-second-prompt.png")
    )
    qtbot.mouseClick(
        plot, Qt.MouseButton.LeftButton, pos=_point(plot, 209 / 264)
    )
    np.testing.assert_allclose(
        next(iter(plot.reflection.regions.values())), (209, 220), atol=0.3
    )
    assert window.grab().save(str(output / "manual-example-log.png"))
    assert window.cube is cube and window.decode_worker is None
    np.testing.assert_array_equal(plot.series[0][1], original)
