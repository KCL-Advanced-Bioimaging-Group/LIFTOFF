"""Compact graph controls with related actions kept together."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QAbstractButton

if TYPE_CHECKING:
    from .gui_plot import HistogramPlot


def _size(button: QAbstractButton, height: int, available: int) -> None:
    button.resize(
        min(button.sizeHint().width() + 12, max(1, available)), height
    )


def _reflection_controls(plot: HistogramPlot, height: int) -> int:
    """Keep Clear immediately to the right of automatic detection."""
    markers = plot.reflection
    right = plot.width() - 16
    top = height + 9
    _size(markers.clear_button, height, plot.width() - 32)
    _size(
        markers.detect_button,
        height,
        plot.width() - 38 - markers.clear_button.width(),
    )
    markers.clear_button.move(right - markers.clear_button.width(), top)
    markers.detect_button.move(
        markers.clear_button.x() - 6 - markers.detect_button.width(), top
    )
    _size(markers.manual_button, height, plot.width() - 32)
    left = markers.detect_button.x() - 6 - markers.manual_button.width()
    markers.manual_button.move(
        left if left >= 16 else 16,
        top if left >= 16 else top + height + 4,
    )
    return (
        max(
            button.geometry().bottom()
            for button in (
                markers.clear_button,
                markers.detect_button,
                markers.manual_button,
            )
        )
        + 5
    )


def position_histogram_controls(plot: HistogramPlot) -> None:
    """Place scale, reflection and ROI actions on three compact rows."""
    height = max(24, plot.log_scale_button.sizeHint().height())
    right = plot.width() - 16
    button = plot.log_scale_button
    _size(button, height, plot.width() - 32)
    button.move(max(16, right - button.width()), 5)
    top = _reflection_controls(plot, height)
    bottom = top + height
    left = plot.width() - 16
    combine = getattr(plot, "combine_rois_button", None)
    if combine is not None:
        _size(combine, height, plot.width() - 32)
        combine.move(
            min(
                plot.reflection.clear_button.geometry().right()
                + 1
                - combine.width(),
                plot.width() - 16 - combine.width(),
            ),
            top,
        )
        left = combine.x() - 6
    separate = plot.separate_tiles_button
    if not separate.isHidden():
        _size(separate, height, plot.width() - 32)
        separate.move(
            left - separate.width() if left - separate.width() >= 16 else 16,
            top if left - separate.width() >= 16 else bottom + 4,
        )
        left = min(left, separate.x() - 6)
        bottom = max(bottom, separate.geometry().bottom())
    status = plot.reflection.status
    if (
        status.text()
        and status.fontMetrics().horizontalAdvance(status.text()) > left - 16
    ):
        status.setGeometry(16, bottom + 4, max(1, plot.width() - 32), height)
        bottom = status.geometry().bottom()
    else:
        status.setGeometry(16, top, max(0, left - 16), height)
    plot.controls_bottom = bottom
