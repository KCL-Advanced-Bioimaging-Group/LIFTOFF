"""Validate runtime dependencies and both maintained native
libraries.
"""

import platform
import struct
import sys

import numpy
import PIL
import PySide6

from leica_flim_converter.native_decoder import (
    API_VERSION,
    native_decoder_info,
)
from leica_flim_converter.raw_selection import load_filter_library


def main() -> None:
    """Verify the runtime and the expected native decoder API."""
    if sys.version_info[:2] != (3, 14) or struct.calcsize("P") != 8:
        raise SystemExit("64-bit Python 3.14 is required")
    decoder = native_decoder_info()
    if not decoder.get("available"):
        raise SystemExit(f"Native decoder unavailable: {decoder}")
    if decoder.get("apiVersion") != API_VERSION or not decoder.get(
        "rawAvailable"
    ):
        raise SystemExit(f"Unexpected native capabilities: {decoder}")
    if load_filter_library() is None:
        raise SystemExit("Native LMSRAW selection filter is unavailable")
    print(f"Python: {platform.python_version()} (64-bit)")
    print(f"NumPy: {numpy.__version__}")
    print(f"Pillow: {PIL.__version__}")
    print(f"PySide6: {PySide6.__version__}")
    print(f"Decoder: {decoder['version']} (API {API_VERSION})")
    print("PASS: maintained source runtime and native libraries are ready")


if __name__ == "__main__":
    main()
