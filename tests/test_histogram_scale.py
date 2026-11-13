"""Photon-count display scales preserve counts and linear time bins."""

from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from pytestqt.qtbot import QtBot

from leica_flim_converter import gui_plot
from leica_flim_converter.gui_helpers import (
    _draw_histogram_axes_2,
    _draw_histogram_curves,
    _histogram_log_bounds,
)
from leica_flim_converter.gui_plot import HistogramPlot


def test_logarithmic_spacing_preserves_time_bins_and_counts() -> None:
    """Space decades equally while retaining each time-bin position."""
    counts = np.array([1, 10, 100, 1000, 10000], dtype=np.uint64)
    original = counts.copy()
    series = [("ROI 1", counts, QColor("blue"))]
    painter = Mock(spec=QPainter)
    rectangle = QRectF(20, 20, 400, 300)
    _draw_histogram_curves(painter, series, rectangle, 10000)
    linear_path = painter.drawPath.call_args.args[0]
    _draw_histogram_curves(painter, series, rectangle, 10000, True)
    log_path = painter.drawPath.call_args.args[0]
    for index in range(5):
        assert linear_path.elementAt(index).x == 20 + index * 100
        assert log_path.elementAt(index).x == linear_path.elementAt(index).x
        assert log_path.elementAt(index).y == pytest.approx(320 - index * 75)
    assert linear_path.elementAt(2).y == pytest.approx(317)
    np.testing.assert_array_equal(counts, original)


def test_zero_counts_break_logarithmic_curves() -> None:
    """Omitted zero bins cannot join separate positive runs."""
    painter = Mock(spec=QPainter)
    counts = np.array([0, 10, 100, 0, 1000, 0], dtype=np.uint64)
    _draw_histogram_curves(
        painter,
        [("ROI", counts, QColor("blue"))],
        QRectF(0, 0, 500, 300),
        1000,
        True,
    )
    path = painter.drawPath.call_args.args[0]
    assert path.elementCount() == 3
    assert [path.elementAt(index).x for index in range(3)] == [100, 200, 400]
    assert path.elementAt(0).type == QPainterPath.ElementType.MoveToElement
    assert path.elementAt(1).type == QPainterPath.ElementType.LineToElement
    assert path.elementAt(2).type == QPainterPath.ElementType.MoveToElement
    assert painter.drawPoint.call_count == 1


@pytest.mark.parametrize("counts", [[], [0, 0, 0], [0, 1, 0], [0, 10, 0]])
def test_logarithmic_sparse_curves(counts: list[int]) -> None:
    """Leave empty curves blank and show isolated positive bins."""
    image = QImage(240, 240, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    _draw_histogram_curves(
        painter,
        [("Pixel", np.array(counts, dtype=np.uint64), QColor("blue"))],
        QRectF(20, 20, 200, 200),
        max(counts, default=1),
        True,
    )
    painter.end()
    if 1 in counts:
        assert image.pixelColor(120, 220) == QColor("blue")
    elif 10 in counts:
        assert image.pixelColor(120, 20) == QColor("blue")
    else:
        blank = QImage(image.size(), image.format())
        blank.fill(Qt.GlobalColor.white)
        assert image == blank


def test_logarithmic_axis_labels(qtbot: QtBot) -> None:
    """Log ticks show photon counts, while x labels keep native bins."""
    plot = HistogramPlot()
    qtbot.addWidget(plot)
    plot.log_scale_button.click()
    painter = Mock(spec=QPainter)
    _draw_histogram_axes_2(
        painter, plot, 0, QRectF(80, 20, 400, 300), np.zeros(128), 1_000_000
    )
    labels = [call.args[-1] for call in painter.drawText.call_args_list]
    assert labels == [
        "1",
        "10",
        "10",
        "2",
        "10",
        "3",
        "10",
        "4",
        "10",
        "5",
        "10",
        "6",
        "0",
        "127",
        "Time bins",
        "Photon counts",
    ]


@pytest.mark.parametrize(
    ("curves", "maximum", "expected"),
    [
        ([], 1, (0, 1)),
        ([[0, 0]], 1, (0, 1)),
        ([[1]], 1, (0, 1)),
        ([[10]], 10, (0, 1)),
        ([[1000]], 1000, (2, 3)),
        ([[5000, 973718]], 973718, (3, 6)),
        ([[20000, 973718], [0, 5000, 100000]], 973718, (3, 6)),
        ([[5000, 973718], [0, 0]], 973718, (3, 6)),
        (
            [[1_000_000_000_000_000_001, 2_000_000_000_000_000_000]],
            2_000_000_000_000_000_000,
            (18, 19),
        ),
    ],
)
def test_logarithmic_bounds(
    curves: list[list[int]], maximum: int, expected: tuple[int, int]
) -> None:
    """Bracket positive counts, ignoring zeros and empty curves."""
    arrays = [np.array(values, dtype=np.uint64) for values in curves]
    assert _histogram_log_bounds(arrays, maximum) == expected


def test_logarithmic_curve_uses_adjusted_lower_limit() -> None:
    """Use the 1,000 baseline for counts between 5,000 and 973,718."""
    counts = np.array([5000, 10000, 100000, 973718], dtype=np.uint64)
    original = counts.copy()
    painter = Mock(spec=QPainter)
    series = [("All pixels", counts, QColor("blue"))]
    rectangle = QRectF(20, 20, 300, 300)
    _draw_histogram_curves(painter, series, rectangle, 973718, True)
    path = painter.drawPath.call_args.args[0]
    assert path.elementAt(1).y == pytest.approx(220)
    assert path.elementAt(2).y == pytest.approx(120)
    assert 250 < path.elementAt(0).y < 251
    assert 21 < path.elementAt(3).y < 22
    assert [path.elementAt(index).x for index in range(4)] == [
        20,
        120,
        220,
        320,
    ]
    _draw_histogram_curves(painter, series, rectangle, 973718)
    linear_path = painter.drawPath.call_args.args[0]
    assert linear_path.elementAt(3).y == 20
    assert linear_path.elementAt(0).y == pytest.approx(
        320 - 5000 / 973718 * 300
    )
    np.testing.assert_array_equal(counts, original)


@pytest.mark.parametrize("multichannel", [False, True])
def test_graph_axes_and_curves_share_log_limits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, multichannel: bool
) -> None:
    """Use all ROI curves for each graph's independently fitted axis."""
    plot = HistogramPlot()
    qtbot.addWidget(plot)
    plot.resize(1100, 400)
    counts = np.array([20000, 100000, 973718], dtype=np.uint64)
    low_counts = np.array([0, 5000, 20000], dtype=np.uint64)
    series = [
        ("ROI 1", counts, QColor("blue")),
        ("ROI 2", low_counts, QColor("orange")),
    ]
    plot.set_series(series)
    if multichannel:
        plot.multichannel_panels = [
            {"title": "Channel 1", "values": counts, "series": series},
            {
                "title": "Channel 2",
                "values": np.array([200000, 900000], dtype=np.uint64),
                "color": QColor("blue"),
            },
        ]
    axes = Mock(wraps=_draw_histogram_axes_2)
    curves = Mock(wraps=_draw_histogram_curves)
    monkeypatch.setattr(gui_plot, "_draw_histogram_axes_2", axes)
    monkeypatch.setattr(gui_plot, "_draw_histogram_curves", curves)
    plot.show()
    qtbot.wait(1)
    plot.log_scale_button.click()
    axes.reset_mock()
    curves.reset_mock()
    # Force rendering even when another window occludes this widget.
    plot.grab()
    expected = [(3, 6), (5, 6)] if multichannel else [(3, 6)]
    assert [call.kwargs["log_bounds"] for call in axes.call_args_list] == (
        expected
    )
    assert [call.kwargs["log_bounds"] for call in curves.call_args_list] == (
        expected
    )
    plot.log_scale_button.setChecked(False)
    axes.reset_mock()
    plot.grab()
    assert all(
        call.kwargs["log_bounds"] is None for call in axes.call_args_list
    )
