"""Portable desktop launch and persistent Python/Qt diagnostics."""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from types import TracebackType

from PySide6.QtCore import (
    QMessageLogContext,
    QtMsgType,
    qInstallMessageHandler,
)

from .gui import main as gui_main
from .native_decoder import native_decoder_info
from .platform_paths import log_directory
from .release_check import main as verify_release
from .version import APPLICATION_NAME, APPLICATION_VERSION


def main() -> None:
    """Launch source or frozen code with platform-local diagnostics."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_directory() / f"{stamp}-{os.getpid()}.log"
    original_hook = sys.excepthook
    fault_enabled = faulthandler.is_enabled()
    with path.open("a", encoding="utf-8", buffering=1) as stream:

        def exception_hook(
            kind: type[BaseException],
            value: BaseException,
            trace: TracebackType | None,
        ) -> None:
            """Compute exception hook."""
            traceback.print_exception(kind, value, trace, file=stream)
            stream.flush()

        def qt_message(
            kind: QtMsgType, _context: QMessageLogContext, message: str
        ) -> None:
            """Compute qt message."""
            print(datetime.now().isoformat(), kind, message, file=stream)
            if kind == QtMsgType.QtFatalMsg:
                faulthandler.dump_traceback(file=stream, all_threads=True)

        sys.excepthook = exception_hook
        previous_handler = qInstallMessageHandler(qt_message)
        if not fault_enabled:
            faulthandler.enable(stream, all_threads=True)
        try:
            with redirect_stdout(stream), redirect_stderr(stream):
                print(APPLICATION_NAME, APPLICATION_VERSION)
                print("Python", sys.version)
                print("Decoder", native_decoder_info())
                if "--verify-release" in sys.argv:
                    verify_release()
                    return
                gui_main()
        finally:
            qInstallMessageHandler(previous_handler)
            sys.excepthook = original_hook
            if not fault_enabled:
                faulthandler.disable()


if __name__ == "__main__":
    main()
