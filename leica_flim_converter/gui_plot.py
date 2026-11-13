"""Maintained desktop component: plot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gui_workspace_state import WorkspaceState
import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QPushButton,
    QWidget,
)

from .gui_helpers import (
    _draw_histogram_axes_2,
    _draw_histogram_curves,
    _draw_histogram_header_2,
    _histogram_log_bounds,
    _numbered_legend_rows_2,
)
from .gui_models import connect_signal
from .gui_mosaic_graphs import combined_mosaic_graphs, separated_mosaic_graphs
from .gui_plot_controls import position_histogram_controls
from .gui_reflection import ReflectionMarkers


class HistogramPlot(QWidget):
    """Represent histogram plot."""

    multichannel_scope: str
    numbered_roi_legend_visible: bool

    def initialize_histogram_plot(self) -> None:
        """Initialize histogram plot."""
        super().__init__()
        self._last_histogram_layout = {}
        self.controls_bottom = 51
        self.setMinimumHeight(300)
        self.values = np.array([], dtype=np.uint64)
        self.all_pixel_values = self.values
        self.title = "Pixel arrival histogram"
        self.summary = ""
        self.message = ""

    def _histogram_plot_set_histogram_3(
        self, values=None, title="Pixel arrival histogram", summary=""
    ) -> None:
        self.values = np.asarray(
            values if values is not None else [], dtype=np.uint64
        )
        self.title, self.summary, self.message = (title, summary, "")
        self.update()

    def _histogram_plot_set_message_3(self, message: str) -> None:
        self.values = np.array([], dtype=np.uint64)
        self.title, self.summary, self.message = ("", "", message)
        self.update()

    def _histogram_owner_2(self):
        return getattr(self, "channel_owner", None)

    def _histogram_bin_width_2(self):
        owner = self._histogram_owner_2()
        if owner is not None:
            method = getattr(owner, "_bin_width_ps", None)
            if callable(method):
                try:
                    return float(method())
                except TypeError, ValueError:
                    pass
            selected = getattr(owner, "selected", None)
            clock_period = getattr(selected, "clock_period_s", None)
            if clock_period is not None:
                try:
                    return float(clock_period) * 1000000000000.0
                except TypeError, ValueError:
                    pass
        return None

    def histogram_x_axis_label(self):
        """Histogram x axis label."""
        width_ps = self._histogram_bin_width_2()
        return (
            "Time bins"
            if width_ps is None
            else f"Time bins | {width_ps:.2f} ps/bin"
        )

    @property
    def logarithmic_scale(self) -> bool:
        """Use a logarithmic photon-count axis when selected."""
        return self.log_scale_button.isChecked()

    def histogram_content_top(self) -> int:
        """Reserve space for graph controls and reflection detection."""
        return max(51, self.controls_bottom + 8)

    def _histogram_scope_2(self):
        owner = self._histogram_owner_2()
        active = getattr(
            getattr(owner, "image", None), "activated_rois", set()
        )
        return "Activated ROIs" if active else "All Pixels"

    def _paint_single_channel_histogram_2(self, _event):
        series = list(getattr(self, "series", ()) or ())
        key = self.reflection.graph_key(None, self.values.size)
        series = self.reflection.display_series(series, key)
        message = str(getattr(self, "message", "") or "")
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scope = self._histogram_scope_2()
        _draw_histogram_header_2(painter, self, scope)
        if message or not series:
            painter.setPen(QColor("#65707c"))
            painter.setFont(QFont("Arial", 9))
            painter.drawText(
                QRectF(
                    24,
                    55,
                    max(0, self.width() - 48),
                    max(0, self.height() - 75),
                ),
                Qt.AlignmentFlag.AlignCenter,
                message,
            )
            self._last_histogram_layout = {
                "header": "Pixel Photon-Arrival Histograms",
                "scope": scope,
                "state": "loading" if message else "empty",
                "message": message,
            }
            painter.end()
            return True
        legend_rows = _numbered_legend_rows_2(painter, self, series)
        top = self.histogram_content_top() + len(legend_rows) * 18 + 7
        bottom = self.height() - 55
        left_edge = 12
        panel_width = max(80, self.width() - 24)
        left = left_edge + 80
        right = left_edge + panel_width - 10
        maximum = max(
            1,
            max(
                (
                    int(np.asarray(entry[1]).max())
                    for entry in series
                    if np.asarray(entry[1]).size
                ),
                default=1,
            ),
        )
        log_bounds = (
            _histogram_log_bounds((entry[1] for entry in series), maximum)
            if self.logarithmic_scale
            else None
        )
        _draw_histogram_curves(
            painter,
            series,
            QRectF(left, top, right - left, bottom - top),
            maximum,
            self.logarithmic_scale,
            log_bounds=log_bounds,
            omitted=self.reflection.omitted(key),
        )
        representative = np.asarray(series[0][1]).reshape(-1)
        _draw_histogram_axes_2(
            painter,
            self,
            left_edge,
            QRectF(left, top, right - left, bottom - top),
            representative,
            maximum,
            log_bounds=log_bounds,
        )
        self.reflection.draw(
            painter,
            self.reflection.graph_key(None, representative.size),
            QRectF(left, top, right - left, bottom - top),
        )
        self._last_histogram_layout = {
            "header": "Pixel Photon-Arrival Histograms",
            "scope": scope,
            "xAxis": self.histogram_x_axis_label(),
            "yAxis": "Photon counts",
            "panels": [
                {
                    "title": "",
                    "plotRect": [left, top, right, bottom],
                    "axisCenter": (left + right) / 2.0,
                    "titleCenter": (left + right) / 2.0,
                    "xLabelCenter": (left + right) / 2.0,
                }
            ],
        }
        painter.end()
        return True

    def _paint_multichannel_histograms_2(self, _event):
        panels = self.graph_panels()
        if not panels:
            return False
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scope = str(getattr(self, "multichannel_scope", "All Pixels"))
        _draw_histogram_header_2(painter, self, scope)
        legend_rows = _numbered_legend_rows_2(
            painter, self, list(panels[0].get("series") or ())
        )
        count = len(panels)
        outer_left = 12
        gap = 18
        panel_width = max(
            80.0, (self.width() - 12 - outer_left - gap * (count - 1)) / count
        )
        channel_title_top = (
            self.histogram_content_top() + len(legend_rows) * 18
        )
        title_height = 18 if count > 1 else 0
        top = channel_title_top + title_height + 7
        bottom = self.height() - 55
        layout_panels = []
        for index, panel in enumerate(panels):
            left_edge = outer_left + index * (panel_width + gap)
            left = left_edge + 80
            right = left_edge + panel_width - 10
            title = " ".join(panel["title"].split()) if count > 1 else ""
            series = list(
                panel.get("series")
                or [("All pixels", panel["values"], panel["color"])]
            )
            values = (
                np.asarray(series[0][1]).reshape(-1)
                if series
                else np.asarray([])
            )
            key = self.reflection.graph_key(panel, values.size, index)
            series = self.reflection.display_series(series, key)
            maximum = max(
                1,
                max(
                    (
                        int(np.asarray(entry[1]).max())
                        for entry in series
                        if np.asarray(entry[1]).size
                    ),
                    default=1,
                ),
            )
            log_bounds = (
                _histogram_log_bounds((entry[1] for entry in series), maximum)
                if self.logarithmic_scale
                else None
            )
            painter.setFont(QFont("Arial", 9, QFont.Weight.DemiBold))
            painter.setPen(QColor("#33424f"))
            painter.drawText(
                QRectF(
                    left, channel_title_top, max(0, right - left), title_height
                ),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine,
                painter.fontMetrics().elidedText(
                    title,
                    Qt.TextElideMode.ElideRight,
                    max(0, round(right - left)),
                ),
            )
            _draw_histogram_curves(
                painter,
                series,
                QRectF(left, top, right - left, bottom - top),
                maximum,
                self.logarithmic_scale,
                log_bounds=log_bounds,
                omitted=self.reflection.omitted(key),
            )
            _draw_histogram_axes_2(
                painter,
                self,
                left_edge,
                QRectF(left, top, right - left, bottom - top),
                values,
                maximum,
                panel.get("x_axis_label"),
                log_bounds=log_bounds,
            )
            self.reflection.draw(
                painter,
                self.reflection.graph_key(panel, values.size, index),
                QRectF(left, top, right - left, bottom - top),
            )
            layout_panels.append(
                {
                    "title": title,
                    "xAxis": panel.get(
                        "x_axis_label", self.histogram_x_axis_label()
                    ),
                    "plotRect": [left, top, right, bottom],
                    "axisCenter": (left + right) / 2.0,
                    "titleCenter": (left + right) / 2.0,
                    "xLabelCenter": (left + right) / 2.0,
                    "photons": int(panel.get("photons", int(values.sum()))),
                    "seriesLabels": [str(entry[0]) for entry in series],
                }
            )
        self._last_histogram_layout = {
            "header": "Pixel Photon-Arrival Histograms",
            "scope": scope,
            "xAxis": self.histogram_x_axis_label(),
            "yAxis": "Photon counts",
            "panels": layout_panels,
        }
        painter.end()
        return True

    def _histogram_plot__ordered_numbered_roi_legend_series_2(self):
        series = list(getattr(self, "series", ()))

        def sort_key(item):
            """Compute sort key."""
            label = str(item[0])
            try:
                return (0, int(label))
            except ValueError:
                return (1, label.casefold())

        return sorted(series, key=sort_key)

    def position_combine_rois_button(self):
        """Arrange graph controls without covering the plotted data."""
        position_histogram_controls(self)

    def update_mosaic_graph_controls(self):
        """Offer tile separation only for a decoded mosaic."""
        self.separate_tiles_button.setVisible(
            any(
                panel.get("mosaic_pair_key")
                for panel in self.multichannel_panels or ()
            )
        )
        self.position_combine_rois_button()

    def graph_panels(self) -> list[dict]:
        """Return combined curves or separate tile graphs."""
        panels = list(self.multichannel_panels or ())
        return (
            separated_mosaic_graphs(panels, self.hovered_mosaic_tile)
            if self.separate_tiles_button.isChecked()
            else combined_mosaic_graphs(panels)
        )

    channel_owner: WorkspaceState
    combine_rois_button: QAbstractButton
    multichannel_panels: list[dict] | None
    message: str
    series: list[tuple[str, np.ndarray, QColor]]
    summary: str
    title: str

    def __init__(self):
        self.initialize_histogram_plot()
        self.series = []
        self.multichannel_panels = None
        self.hovered_mosaic_tile: int | None = None
        self.separate_tiles_button = QPushButton(
            "Separate graphs by tile", self
        )
        self.separate_tiles_button.setObjectName("separateTileGraphsButton")
        self.separate_tiles_button.setCheckable(True)
        self.separate_tiles_button.setToolTip(
            "Show a separate photon-arrival graph for each mosaic tile"
        )
        self.separate_tiles_button.hide()
        connect_signal(
            self.separate_tiles_button.toggled, lambda _checked: self.update()
        )
        self.log_scale_button = QPushButton("Log scale", self)
        self.log_scale_button.setObjectName("logScaleButton")
        self.log_scale_button.setToolTip(
            "Display Photon counts on a logarithmic y-axis; "
            "zero-count bins are omitted. Uncheck for a linear y-axis."
        )
        self.log_scale_button.setCheckable(True)
        connect_signal(
            self.log_scale_button.toggled, lambda _checked: self.update()
        )
        self.reflection = ReflectionMarkers(self)
        self.position_combine_rois_button()

    def set_histogram(
        self,
        values=None,
        title="Pixel arrival histogram",
        summary="",
        *,
        preserve_reflection=False,
    ):
        """Compute set histogram."""
        if not preserve_reflection:
            self.reflection.clear()
        self._histogram_plot_set_histogram_3(values, title, summary)
        array = np.asarray(
            values if values is not None else [], dtype=np.uint64
        )
        self.all_pixel_values = array
        self.series = [(title, array, QColor("#1769AA"))] if array.size else []
        self.hovered_mosaic_tile = None
        self.update_mosaic_graph_controls()

    def set_message(self, message):
        """Compute set message."""
        self.reflection.clear()
        self._histogram_plot_set_message_3(message)
        self.all_pixel_values = self.values
        self.series = []

    def paintEvent(self, event):  # noqa: N802
        """Compute paint event."""
        self.reflection.begin_frame()
        self.position_combine_rois_button()
        if self._paint_multichannel_histograms_2(event):
            return
        if self._paint_single_channel_histogram_2(event):
            return

    def set_series(self, series, title="Pixel arrival histogram", summary=""):
        """Compute set series."""
        prepared = []
        for label, values, color in series:
            array = np.asarray(values, dtype=np.uint64)
            prepared.append((str(label), array, QColor(color)))
        self.series = prepared
        self.values = (
            prepared[0][1] if prepared else np.array([], dtype=np.uint64)
        )
        self.title = str(title)
        self.summary = str(summary)
        self.message = ""
        self.update()

    def _ordered_numbered_roi_legend_series(self):
        series = list(getattr(self, "series", ()))

        def sort_key(item):
            """Compute sort key."""
            label = str(item[0])
            try:
                return (0, int(label))
            except ValueError:
                return (1, label.casefold())

        return sorted(series, key=sort_key)

    def resizeEvent(self, event):  # noqa: N802
        """Compute resize event."""
        QWidget.resizeEvent(self, event)
        self.position_combine_rois_button()
