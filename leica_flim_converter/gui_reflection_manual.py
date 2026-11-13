"""Two-click reflection placement with a persistent pointer prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QPushButton

from .gui_models import connect_signal

if TYPE_CHECKING:
    from .gui_reflection import GraphKey, ReflectionMarkers


class ManualReflectionPlacement:
    """Preview one boundary and commit an interval after two clicks."""

    def __init__(self, markers: ReflectionMarkers) -> None:
        self.markers = markers
        self.active = False
        self.pending: tuple[GraphKey, float] | None = None
        self.button = QPushButton(
            "Manually-detect reflection peak", markers.plot
        )
        self.button.setObjectName("manuallyDetectReflectionPeakButton")
        self.button.setCheckable(True)
        self.button.setToolTip(
            "Click two positions on a graph to place reflection boundaries "
            "in either order. Press Escape or click this button again "
            "to cancel. Markers only affect the display."
        )
        self.prompt = QLabel(markers.plot)
        self.prompt.setObjectName("manualReflectionPrompt")
        self.prompt.setWindowFlags(
            Qt.WindowType.ToolTip
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.prompt.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.prompt.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.prompt.setStyleSheet(
            "QLabel { background: #fffbd6; color: #111111; "
            "border: 1px solid #868686; padding: 6px 8px; }"
        )
        self.prompt.hide()
        self.timer = QTimer(markers)
        self.timer.setInterval(25)
        self.escape = QShortcut(QKeySequence("Esc"), markers.plot)
        self.escape.setEnabled(False)
        connect_signal(self.button.clicked, self.toggle)
        connect_signal(self.timer.timeout, self.follow_pointer)
        connect_signal(self.escape.activated, self.cancel)

    def toggle(self) -> None:
        """Start placement or cancel when clicked again."""
        if self.button.isChecked():
            self.start()
        else:
            self.cancel()

    def start(self) -> None:
        """Show the first prompt immediately beside the pointer."""
        if self.markers.filtered:
            return
        self.markers.sync_context()
        self.active = True
        self.pending = None
        self.button.setChecked(True)
        self.markers.clear_button.setEnabled(True)
        self.markers.status.setText("Press Esc to cancel.")
        self.markers.plot.setCursor(Qt.CursorShape.CrossCursor)
        self.prompt.setText("Please drop first boundary")
        self.follow_pointer()
        self.prompt.show()
        self.timer.start()
        self.escape.setEnabled(True)
        self.markers.changed.emit()
        self.markers.plot.update()

    def cancel(self) -> None:
        """Restore completed intervals and discard the preview."""
        self.active = False
        self.pending = None
        self.button.setChecked(False)
        self.prompt.hide()
        self.timer.stop()
        self.escape.setEnabled(False)
        self.markers.plot.unsetCursor()
        self.markers.clear_button.setEnabled(bool(self.markers.regions))
        self.markers.status.setText(
            "Drag black lines to adjust." if self.markers.regions else ""
        )
        self.markers.changed.emit()
        self.markers.plot.update()

    def drop(self, point: QPointF) -> None:
        """Accept two distinct positions on the same image's graphs."""
        graph = self.markers.graph_at(point)
        if graph is None:
            return
        key, rectangle = graph
        position = (
            (point.x() - rectangle.left()) / rectangle.width() * (key[2] - 1)
        )
        position = min(key[2] - 1.0, max(0.0, position))
        if self.pending is None:
            self.pending = (key, position)
            self.prompt.setText("Please drop second boundary")
            self.follow_pointer()
            self.markers.plot.update()
            return
        previous_key, first = self.pending
        if key != previous_key or abs(position - first) < 1:
            return
        left, right = sorted((first, position))
        self.markers.regions[key] = (left, right)
        self.cancel()
        self.markers.regions_changed.emit()

    def follow_pointer(self, position: QPoint | None = None) -> None:
        """Keep the prompt beside the pointer and within its screen."""
        if not self.active:
            return
        anchor = QCursor.pos() if position is None else position
        self.prompt.adjustSize()
        target = anchor + QPoint(16, 18)
        screen = QGuiApplication.screenAt(anchor)
        if screen is not None:
            available = screen.availableGeometry()
            if target.x() + self.prompt.width() > available.right():
                target.setX(anchor.x() - self.prompt.width() - 16)
            if target.y() + self.prompt.height() > available.bottom():
                target.setY(anchor.y() - self.prompt.height() - 18)
            target.setX(max(available.left(), target.x()))
            target.setY(max(available.top(), target.y()))
        self.prompt.move(target)
