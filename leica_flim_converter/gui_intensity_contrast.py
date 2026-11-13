"""Horizontal brightness histograms with independent display levels."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QPushButton, QWidget

from .gui_helpers import _compose_channel_images_2
from .gui_intensity_levels import IntensityDistribution, render_intensity
from .gui_models import connect_signal

_PLOT_LEFT_MARGIN = 28
_PLOT_RIGHT_MARGIN = 10


class IntensityContrast(QWidget):
    """Adjust display levels without touching photon data."""

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self.hide()
        self.canvas = canvas
        self.setFixedHeight(140)
        self.setMouseTracking(True)
        self.intensities: list[np.ndarray] = []
        self.panels: list[dict] | None = None
        self.frequencies = np.zeros(256, dtype=np.int64)
        self.levels = [(0.0, 99.8)]
        self.groups: list[list[int]] = []
        self.distributions: list[IntensityDistribution] = []
        self.active_index = 0
        self.dragging: int | None = None
        self.generation = 0
        self.log_scale_button = QPushButton("Log scale", self)
        self.log_scale_button.setObjectName("intensityLogScaleButton")
        self.log_scale_button.setCheckable(True)
        self.log_scale_button.setToolTip(
            "Use logarithmic pixel frequency for the intensity histograms. "
            "Uncheck for linear frequency. Contrast settings are unchanged."
        )
        connect_signal(
            self.log_scale_button.toggled, lambda _checked: self.update()
        )
        self.setToolTip(
            "Drag the boundaries to adjust contrast; right-click to reset "
            "to P0-P99.8. Viewing only: photon counts and exports are "
            "unchanged."
        )

    def set_intensities(self, intensities, panels=None, *, reset=True) -> None:
        """Compute percentiles directly from original intensities."""
        self.intensities = [np.asarray(values) for values in intensities]
        self.panels = panels
        groups = {}
        for index in range(len(self.intensities)):
            dataset = panels[index]["dataset"] if panels else None
            key = (
                dataset.pair_key
                if dataset is not None and dataset.mosaic is not None
                else str(index)
            )
            groups.setdefault(key, []).append(index)
        self.groups = list(groups.values())
        self.distributions = [
            IntensityDistribution([self.intensities[index] for index in group])
            for group in self.groups
        ]
        self.frequencies = (
            np.concatenate([item.counts for item in self.distributions])
            if self.distributions
            else np.array([], dtype=np.int64)
        )
        if reset or len(self.levels) != len(self.groups):
            self.levels = [(0.0, 99.8) for _group in self.groups]
            self.active_index = 0
        if reset:
            self.generation += 1
        self.dragging = None
        if self.intensities:
            self.render_image()
        self.update()

    @property
    def black_level(self) -> float:
        """Black level of the currently selected image."""
        return self.levels[self.active_index][0]

    @black_level.setter
    def black_level(self, value: float) -> None:
        self.levels[self.active_index] = (value, self.white_level)

    @property
    def white_level(self) -> float:
        """White level of the currently selected image."""
        return self.levels[self.active_index][1]

    @white_level.setter
    def white_level(self, value: float) -> None:
        self.levels[self.active_index] = (self.black_level, value)

    def plot_rect(self, index: int | None = None) -> QRectF:
        """Align each histogram beneath its image."""
        index = self.active_index if index is None else index
        count = max(1, len(self.groups))
        left, width = index * self.width() / count, self.width() / count
        base = self.canvas.image_rect
        if (
            self.panels
            and base.isValid()
            and self.canvas.width() == self.width()
        ):
            group = self.groups[index]
            start = min(self.panels[item]["composite_x"] for item in group)
            end = max(
                self.panels[item]["composite_x"]
                + self.intensities[item].shape[1]
                for item in group
            )
            composite = self.canvas.image
            if composite is not None:
                left = base.left() + start / composite.width() * base.width()
                width = (end - start) / composite.width() * base.width()
        return QRectF(
            left + _PLOT_LEFT_MARGIN,
            20,
            max(1, width - _PLOT_LEFT_MARGIN - _PLOT_RIGHT_MARGIN),
            54,
        )

    def render_image(self) -> None:
        """Resolve percentile limits against original intensities."""
        if not self.intensities:
            return
        rendered = []
        for index, source in enumerate(self.intensities):
            group = next(
                position
                for position, items in enumerate(self.groups)
                if index in items
            )
            distribution = self.distributions[group]
            low, high = (
                distribution.quantile(value) for value in self.levels[group]
            )
            rendered.append(render_intensity(source, low, high))
        if self.panels is None:
            self.canvas.image = rendered[0]
        else:
            panels = [
                {**panel, "image": image}
                for panel, image in zip(self.panels, rendered, strict=True)
            ]
            self.canvas.image = _compose_channel_images_2(panels)
        self.canvas.update()
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        """Draw a horizontal brightness curve for each image."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f4f4f4"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, frequencies in enumerate(self.distributions):
            self._draw_curve(painter, index, frequencies)
        painter.end()

    def _draw_curve(self, painter, index, distribution) -> None:
        rect = self.plot_rect(index)
        painter.setPen(QPen(QColor("#9aa6b2"), 1))
        painter.drawRect(rect)
        painter.setPen(QColor("#33424f"))
        painter.drawText(
            QRectF(rect.left(), 0, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            (
                "Pixels (log)   "
                if self.log_scale_button.isChecked()
                else "Pixels   "
            )
            + f"P{self.levels[index][0]:.2f} – P{self.levels[index][1]:.2f}",
        )
        low, high = distribution.axis_limits()
        self._draw_ticks(painter, rect, low, high)
        path = QPainterPath()
        ranks, counts = distribution.curve()
        logarithmic = self.log_scale_button.isChecked()
        values = (
            np.log10(counts, out=np.zeros(counts.size), where=counts > 0)
            if logarithmic
            else counts
        )
        connected = False
        for position, (value, frequency) in enumerate(
            zip(ranks, values, strict=True)
        ):
            if logarithmic and counts[position] == 0:
                connected = False
                continue
            point = QPointF(
                rect.left() + (value - low) / (high - low) * rect.width(),
                rect.bottom()
                - frequency / max(1, values.max()) * rect.height(),
            )
            if connected:
                path.lineTo(point)
            else:
                path.moveTo(point)
            connected = True
        painter.setPen(QPen(QColor("#1769aa"), 1.5))
        painter.drawPath(path)
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        for percentile in self.levels[index]:
            value = distribution.quantile(percentile)
            x = rect.left() + (value - low) / (high - low) * rect.width()
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        painter.drawText(
            QRectF(rect.left(), 93, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            "Intensity",
        )

    def _draw_ticks(
        self, painter: QPainter, rect: QRectF, low: float, high: float
    ) -> None:
        """Fit full tick labels within each histogram's span."""
        metrics = painter.fontMetrics()
        left = max(0, rect.left() - _PLOT_LEFT_MARGIN) + 2
        right = min(self.width(), rect.right() + _PLOT_RIGHT_MARGIN) - 2
        for intervals in (4, 2, 1):
            ticks = []
            previous_right = left
            for index in range(intervals + 1):
                fraction = index / intervals
                label = f"{low + fraction * (high - low):.3g}"
                width = metrics.horizontalAdvance(label) + 4
                centre = rect.left() + fraction * rect.width()
                x = min(max(left, centre - width / 2), right - width)
                if x < previous_right:
                    break
                ticks.append((QRectF(x, rect.bottom() + 2, width, 17), label))
                previous_right = x + width
            if len(ticks) == intervals + 1:
                for box, label in ticks:
                    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
                return

    def resizeEvent(self, event):  # noqa: N802
        """Keep the scale toggle below the intensity histograms."""
        super().resizeEvent(event)
        button = self.log_scale_button
        button.resize(button.sizeHint().width() + 12, 24)
        button.move(
            max(0, self.width() - button.width() - 10), self.height() - 28
        )

    def _select_graph(self, point) -> bool:
        for index in range(len(self.groups)):
            if self.plot_rect(index).adjusted(-8, -8, 8, 8).contains(point):
                self.active_index = index
                return True
        return False

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._select_graph(
            event.position()
        ):
            rect = self.plot_rect()
            distribution = self.distributions[self.active_index]
            low, high = distribution.axis_limits()
            value = low + (
                event.position().x() - rect.left()
            ) / rect.width() * (high - low)
            self.dragging = int(
                abs(value - distribution.quantile(self.white_level))
                < abs(value - distribution.quantile(self.black_level))
            )
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.dragging is not None:
            rect = self.plot_rect()
            distribution = self.distributions[self.active_index]
            low, high = distribution.axis_limits()
            intensity = low + (
                event.position().x() - rect.left()
            ) / rect.width() * (high - low)
            value = distribution.percentile(intensity)
            if self.dragging:
                self.white_level = max(
                    float(np.nextafter(self.black_level, np.inf)), value
                )
            else:
                self.black_level = min(
                    float(np.nextafter(self.white_level, -np.inf)), value
                )
            self.render_image()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouseMoveEvent(event)
            self.dragging = None
            self.unsetCursor()

    def contextMenuEvent(self, event):  # noqa: N802
        """Reset only the image whose histogram was right-clicked."""
        if self._select_graph(event.pos()):
            menu = QMenu(self)
            action = menu.addAction("Reset (P0 - P99.8)")
            connect_signal(action.triggered, self.reset_levels)
            menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            menu.popup(event.globalPos())

    def reset_levels(self) -> None:
        """Restore the default percentile boundaries for this image."""
        self.levels[self.active_index] = (0.0, 99.8)
        self.render_image()
