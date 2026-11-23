"""Keep top-level windows within their screen's usable desktop."""

from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QMetaObject,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QGuiApplication, QScreen, QWindow
from PySide6.QtWidgets import QWidget

from .gui_models import connect_signal

_SPECIAL_WINDOW_STATES = (
    Qt.WindowState.WindowMinimized
    | Qt.WindowState.WindowMaximized
    | Qt.WindowState.WindowFullScreen
)


class ScreenFit(QObject):
    """Fit a window on show and when its screen or work area changes."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self._widget = widget
        self._window: QWindow | None = None
        self._work_area_connection: QMetaObject.Connection | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        connect_signal(self._timer.timeout, self._fit_frame)
        widget.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Fit on show, then recheck the native window frame."""
        if event.type() == QEvent.Type.Show:
            window = self._widget.windowHandle()
            if window is not None and window is not self._window:
                self._window = window
                window.screenChanged.connect(self._screen_changed)
                self._screen_changed(window.screen())
            self._fit()
            self._queue_fit()
        elif event.type() == QEvent.Type.WindowStateChange:
            self._queue_fit()
        return super().eventFilter(watched, event)

    def _screen_changed(self, screen: QScreen | None) -> None:
        if self._work_area_connection is not None:
            QObject.disconnect(self._work_area_connection)
        self._work_area_connection = None
        if screen is not None:
            self._work_area_connection = (
                screen.availableGeometryChanged.connect(self._queue_fit)
            )
        self._queue_fit()

    def _queue_fit(self) -> None:
        self._timer.start(0)

    def _fit_frame(self) -> None:
        self._fit(position=True)

    def _fit(self, *, position: bool = False) -> None:
        widget = self._widget
        window = self._window
        if (
            window is None
            or not widget.isVisible()
            or widget.windowState() & _SPECIAL_WINDOW_STATES
        ):
            return
        screen = window.screen()
        if screen is None or (area := screen.availableGeometry()).isEmpty():
            return
        margins = window.frameMargins()
        available = QSize(
            max(1, area.width() - margins.left() - margins.right()),
            max(1, area.height() - margins.top() - margins.bottom()),
        )
        fitted = widget.size().boundedTo(available)
        if fitted != widget.size():
            widget.resize(fitted)
        if position and not QGuiApplication.platformName().startswith(
            "wayland"
        ):
            frame = widget.frameGeometry()
            last_x = area.x() + max(0, area.width() - frame.width())
            last_y = area.y() + max(0, area.height() - frame.height())
            origin = QPoint(
                min(max(frame.x(), area.x()), last_x),
                min(max(frame.y(), area.y()), last_y),
            )
            if origin != frame.topLeft():
                widget.move(origin)
