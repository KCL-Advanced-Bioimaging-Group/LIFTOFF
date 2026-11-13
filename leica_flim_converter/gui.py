"""Public desktop entry points and compatibility imports."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .gui_canvas import ImageCanvas
from .gui_controls import EventFlagSelector
from .gui_exports import IcsExportDialog, PtuExportDialog
from .gui_plot import HistogramPlot
from .gui_workers import (
    DecodeWorker,
    IcsExportWorker,
    PtuExportWorker,
    ResultWorker,
    ScanWorker,
)
from .gui_workspace import MainWindow
from .version import APPLICATION_NAME, APPLICATION_VERSION


def main() -> None:
    """Run this module through its supported entry point."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(APPLICATION_VERSION)
    font = QApplication.font()
    font.setFamily("Arial")
    QApplication.setFont(font)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


__all__ = [
    "DecodeWorker",
    "EventFlagSelector",
    "HistogramPlot",
    "IcsExportDialog",
    "IcsExportWorker",
    "ImageCanvas",
    "MainWindow",
    "PtuExportDialog",
    "PtuExportWorker",
    "ResultWorker",
    "ScanWorker",
]
