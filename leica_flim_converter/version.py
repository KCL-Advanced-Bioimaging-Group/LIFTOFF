"""Application version and source reconstruction provenance."""

import json
from importlib.resources import files

APPLICATION_NAME = "LIFTOFF"
APPLICATION_FULL_NAME = (
    f"Leica Image Files Translated into Open File Formats ({APPLICATION_NAME})"
)
APPLICATION_VERSION = "3.2.2"
VERSION = APPLICATION_VERSION
__version__ = APPLICATION_VERSION


def application_metadata() -> dict[str, object]:
    """Read packaged provenance without needing Git at runtime."""
    manifest = files("leica_flim_converter").joinpath("provenance.json")
    return {
        "name": APPLICATION_NAME,
        "version": APPLICATION_VERSION,
        "reconstruction": json.loads(manifest.read_text(encoding="utf-8")),
    }
