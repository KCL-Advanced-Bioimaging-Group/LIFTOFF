"""Resource and writable locations for source and frozen
applications.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

from .version import APPLICATION_NAME


def resource_root() -> Path:
    """Find packaged resources without depending on the current
    directory.
    """
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def library_filename(stem: str) -> str:
    """Compute library filename."""
    system = platform.system()
    if system == "Windows":
        return f"{stem}.dll"
    if system == "Darwin":
        return f"lib{stem}.dylib"
    return f"lib{stem}.so"


def native_library_candidates(stem: str) -> list[Path]:
    """Compute native library candidates."""
    filename = library_filename(stem)
    root = resource_root()
    result = [
        Path(__file__).resolve().parent / "native" / filename,
        root / "leica_flim_converter" / "native" / filename,
        root / filename,
    ]
    variable = {
        "LeicaFlimDecoder": "LEICA_FLIM_DECODER_DLL",
        "LeicaLmsrawFilter": "LEICA_LMSRAW_FILTER_LIBRARY",
    }.get(stem)
    configured = os.environ.get(variable, "") if variable else ""
    if configured:
        result.insert(0, Path(configured).expanduser())
    return list(dict.fromkeys(result))


def application_data_dir() -> Path:
    """Compute application data dir."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")
        )
    return base / APPLICATION_NAME


def log_directory() -> Path:
    """Compute log directory."""
    configured = os.environ.get("LIFTOFF_LOG_DIR") or os.environ.get(
        "LEICA_INTERROGATOR_LOG_DIR"
    )
    path = (
        Path(configured).expanduser()
        if configured
        else application_data_dir() / "logs"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path
