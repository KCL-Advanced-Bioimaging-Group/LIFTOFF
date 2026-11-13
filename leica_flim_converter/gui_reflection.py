"""Display-only reflection markers and their graph interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QEvent, QLineF, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QPushButton

from .gui_helpers import _histogram_values_2
from .gui_models import connect_signal
from .gui_mosaic_graphs import combined_mosaic_graphs
from .gui_reflection_manual import ManualReflectionPlacement
from .reflection import detect_reflection_peak

if TYPE_CHECKING:
    from .gui_plot import HistogramPlot

GraphKey = tuple[str, int | None, int]


class ReflectionMarkers(QObject):
    """Own visual intervals separately from histograms and exports."""

    changed = Signal()
    regions_changed = Signal()

    def __init__(self, plot: HistogramPlot) -> None:
        super().__init__(plot)
        self.plot = plot
        self.regions: dict[GraphKey, tuple[float, float]] = {}
        self._filtered_keys: set[GraphKey] = set()
        self._areas: list[tuple[GraphKey, QRectF]] = []
        self._drag: tuple[GraphKey, int, QRectF] | None = None
        self._context: tuple | None = None
        self.detect_button = QPushButton("Auto-detect reflection peak", plot)
        self.detect_button.setObjectName("autoDetectReflectionPeakButton")
        self.detect_button.setToolTip(
            "Find a rise-and-fall in the all-pixels log decay using "
            "noise-supported derivatives. Boundaries mark the outer "
            "positive second-derivative peaks. "
            "Use the whole image even when a pixel or ROI is displayed. "
            "Drag the black boundaries to adjust the grey region. "
            "Markers only affect the display."
        )
        self.clear_button = QPushButton("Clear", plot)
        self.clear_button.setObjectName("clearReflectionPeakButton")
        self.clear_button.setToolTip("Remove the reflection peak markers")
        self.clear_button.setEnabled(False)
        self.status = QLabel(plot)
        self.status.setObjectName("reflectionPeakStatus")
        self.status.setStyleSheet("color: #65707c;")
        self.manual = ManualReflectionPlacement(self)
        self.manual_button = self.manual.button
        connect_signal(self.detect_button.clicked, self.auto_detect)
        connect_signal(self.clear_button.clicked, self._clear_saved_regions)
        plot.setMouseTracking(True)
        plot.installEventFilter(self)

    def clear(self) -> None:
        """Reset the displayed annotations."""
        self.manual.cancel()
        self.regions.clear()
        self._filtered_keys.clear()
        self._areas.clear()
        self._drag = None
        self.plot.unsetCursor()
        self.clear_button.setEnabled(False)
        self.status.clear()
        self.changed.emit()
        self.plot.update()

    def _clear_saved_regions(self) -> None:
        self.clear()
        self.regions_changed.emit()

    def sync_context(self) -> None:
        """Discard annotations when the acquisition or plane changes."""
        owner = getattr(self.plot, "channel_owner", None)
        context = (
            getattr(getattr(owner, "selected", None), "key", None),
            getattr(owner, "current_plane", None),
        )
        if context != self._context:
            self._context = context
            self.clear()

    def begin_frame(self) -> None:
        """Refresh drag geometry and reset on acquisition changes."""
        self.sync_context()
        owner = getattr(self.plot, "channel_owner", None)
        ready = getattr(owner, "decode_worker", None) is None
        self._areas.clear()
        self.detect_button.setEnabled(
            bool(
                self.plot.multichannel_panels
                or self.plot.all_pixel_values.size
                or getattr(owner, "cube", None) is not None
            )
            and bool(self.plot.multichannel_panels or self.plot.series)
            and not self.plot.message
            and ready
            and not self.filtered
        )
        self.manual_button.setEnabled(
            bool(self.plot.multichannel_panels or self.plot.series)
            and not self.plot.message
            and ready
            and not self.filtered
        )
        if self.manual.active and not self.manual_button.isEnabled():
            self.manual.cancel()
        self.clear_button.setEnabled(
            bool(self.regions or self.manual.active) and not self.filtered
        )

    def graph_at(self, point: QPointF) -> tuple[GraphKey, QRectF] | None:
        """Identify a usable plot area, excluding margins."""
        return next(
            (
                (key, rectangle)
                for key, rectangle in self._areas
                if key[2] > 1
                and rectangle.isValid()
                and rectangle.contains(point)
            ),
            None,
        )

    def graph_key(
        self, panel: dict | None, bins: int, index: int = 0
    ) -> GraphKey:
        """Keep annotations specific to a graph and its native bins."""
        if panel is None:
            return ("single", None, bins)
        return (
            str(panel.get("mosaic_pair_key") or f"graph:{index}"),
            None,
            bins,
        )

    def auto_detect(self) -> None:
        """Detect on whole images and share bounds across views."""
        if self.filtered:
            return
        self.begin_frame()
        self.clear()
        panels = combined_mosaic_graphs(self.plot.multichannel_panels or [])
        owner = getattr(self.plot, "channel_owner", None)
        cube = getattr(owner, "cube", None)
        panels = panels or [None]
        for index, panel in enumerate(panels):
            counts = (
                panel["values"]
                if panel is not None
                else _histogram_values_2(cube, None)
                if cube is not None
                else self.plot.all_pixel_values
            )
            if not np.asarray(counts).size:
                continue
            bounds = detect_reflection_peak(counts)
            if bounds is not None:
                self.regions[self.graph_key(panel, counts.size, index)] = (
                    bounds
                )
        self.clear_button.setEnabled(bool(self.regions))
        self.status.setText(
            "Drag black lines to adjust."
            if self.regions
            else "No reflection peak detected."
        )
        self.changed.emit()
        self.regions_changed.emit()
        self.plot.update()

    @property
    def filtered(self) -> bool:
        """Whether any displayed interval is active."""
        return bool(self._filtered_keys)

    def set_filtered(self, keys: set[GraphKey]) -> None:
        """Lock completed bounds while excluding their photons."""
        self._filtered_keys = keys
        self._drag = None
        self.plot.unsetCursor()
        self.begin_frame()
        self.status.setText(
            "Boundaries locked."
            if keys
            else "Drag black lines to adjust."
            if self.regions
            else ""
        )
        self.plot.update()

    def omitted(self, key: GraphKey) -> tuple[float, float] | None:
        """Return the active filter for this channel's graph."""
        return self.regions.get(key) if key in self._filtered_keys else None

    def display_series(self, series: list, key: GraphKey) -> list:
        """Exclude filtered bins from scales without changing data."""
        bounds = self.omitted(key)
        if bounds is None:
            return series
        result = []
        for label, values, color in series:
            displayed = np.asarray(values).copy()
            bins = np.arange(displayed.size)
            displayed[(bins >= bounds[0]) & (bins <= bounds[1])] = 0
            result.append((label, displayed, color))
        return result

    def draw(
        self, painter: QPainter, key: GraphKey, rectangle: QRectF
    ) -> None:
        """Shade the interval and keep plotted counts visible."""
        self._areas.append((key, QRectF(rectangle)))
        bounds: tuple[float, ...] | None = self.regions.get(key)
        if self.manual.pending is not None and self.manual.pending[0] == key:
            bounds = (self.manual.pending[1],)
        if bounds is None or rectangle.width() <= 0 or rectangle.height() <= 0:
            return
        positions = tuple(
            rectangle.left() + value / max(1, key[2] - 1) * rectangle.width()
            for value in bounds
        )
        painter.save()
        painter.setClipRect(rectangle.adjusted(-1, 0, 1, 0))
        if len(positions) == 2:
            painter.fillRect(
                QRectF(
                    positions[0],
                    rectangle.top(),
                    positions[1] - positions[0],
                    rectangle.height(),
                ),
                QColor("white")
                if key in self._filtered_keys
                else QColor(128, 128, 128, 65),
            )
        painter.setPen(QPen(Qt.GlobalColor.black, 1.5))
        for x in positions:
            painter.drawLine(QLineF(x, rectangle.top(), x, rectangle.bottom()))
        painter.restore()

    def _nearest_line(
        self, event: QMouseEvent
    ) -> tuple[GraphKey, int, QRectF] | None:
        candidates = []
        for key, rectangle in self._areas:
            if key not in self.regions or rectangle.width() <= 0:
                continue
            if (
                not rectangle.top()
                <= event.position().y()
                <= rectangle.bottom()
            ):
                continue
            for index, value in enumerate(self.regions[key]):
                x = rectangle.left() + value / (key[2] - 1) * rectangle.width()
                distance = abs(event.position().x() - x)
                if distance <= 7:
                    candidates.append((distance, key, index, rectangle))
        if not candidates:
            return None
        _, key, index, rectangle = min(candidates, key=lambda item: item[0])
        return key, index, rectangle

    def _move_line(self, event: QMouseEvent) -> None:
        if self._drag is None:
            return
        key, index, rectangle = self._drag
        if rectangle.width() <= 0:
            return
        position = (
            (event.position().x() - rectangle.left())
            / rectangle.width()
            * (key[2] - 1)
        )
        left, right = self.regions[key]
        self.regions[key] = (
            (min(max(0.0, position), right - 1), right)
            if index == 0
            else (left, max(left + 1, min(key[2] - 1.0, position)))
        )
        self.changed.emit()
        self.plot.update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Place or drag boundaries using native graph coordinates."""
        if watched is self.plot and event.type() in (
            QEvent.Type.Hide,
            QEvent.Type.WindowDeactivate,
        ):
            if self.manual.active:
                self.manual.cancel()
        if (
            watched is not self.plot
            or not isinstance(event, QMouseEvent)
            or self.filtered
        ):
            return False
        if self.manual.active:
            self.manual.follow_pointer(event.globalPosition().toPoint())
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self.manual.drop(event.position())
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag = self._nearest_line(event)
                if self._drag is not None:
                    self.plot.setCursor(Qt.CursorShape.SizeHorCursor)
                    return True
        elif event.type() == QEvent.Type.MouseMove:
            if self._drag is not None:
                self._move_line(event)
                return True
            if self._nearest_line(event) is not None:
                self.plot.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.plot.unsetCursor()
        elif event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._drag:
                self._move_line(event)
                self._drag = None
                self.plot.unsetCursor()
                self.regions_changed.emit()
                return True
        return False
