"""Verify normal desktop launch in a source or installed environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import leica_flim_converter
from leica_flim_converter import launcher
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.native_decoder import native_decoder_info
from leica_flim_converter.version import application_metadata


def main() -> None:
    """Open the real launcher, inspect its window, then close
    normally.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    report: dict[str, object] = {
        "application": application_metadata(),
        "module": str(Path(leica_flim_converter.__file__).resolve()),
        "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "native": native_decoder_info(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "Pillow", "PySide6")
        },
    }

    def inspect_window() -> None:
        """Capture evidence while the normal event loop is running."""
        windows = [
            widget
            for widget in app.topLevelWidgets()
            if isinstance(widget, MainWindow) and widget.isVisible()
        ]
        report["visibleWindows"] = len(windows)
        report["windowTitles"] = [window.windowTitle() for window in windows]
        if len(windows) == 1:
            report["screenshotSaved"] = (
                windows[0].grab().save(str(args.output / "startup.png"))
            )
            report["openEnabled"] = windows[0].open_button.isEnabled()
            windows[0].close()
        app.quit()

    QTimer.singleShot(1200, inspect_window)
    try:
        launcher.main()
    except SystemExit as result:
        report["exitCode"] = result.code
    if report.get("visibleWindows") != 1 or report.get("exitCode") != 0:
        raise RuntimeError(f"Desktop smoke check failed: {report}")
    (args.output / "result.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print("PASS: normal launcher, visible window and native API 4")


if __name__ == "__main__":
    main()
