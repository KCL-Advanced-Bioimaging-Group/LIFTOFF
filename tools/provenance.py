"""Record Git source identity and rebuilt native hashes for
packaging.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import platform
import subprocess
from pathlib import Path

from leica_flim_converter.platform_paths import library_filename

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "leica_flim_converter" / "provenance.json"


def git_output(arguments: list[str]) -> str:
    """Read source identity through Git without shell interpolation."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    """Refresh a portable manifest after building on the target host."""
    provenance = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        provenance["sourceCommit"] = git_output(["rev-parse", "HEAD"])
        changed = git_output(
            [
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "*.py",
                "*.cpp",
                "*.h",
                "CMakeLists.txt",
                "pyproject.toml",
                "*.cmake",
                "*.bat",
                "*.ps1",
                "requirements*.txt",
            ]
        )
        provenance["sourceModified"] = bool(changed)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit("Git source provenance could not be read") from error
    provenance["targetSystem"] = platform.system()
    provenance["targetArchitecture"] = platform.machine()
    directory = ROOT / "leica_flim_converter" / "native"
    provenance["nativeLibraries"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            directory / library_filename(stem)
            for stem in ("LeicaFlimDecoder", "LeicaLmsrawFilter")
        )
    }
    for key, stem, symbol in (
        ("nativeDecoder", "LeicaFlimDecoder", "leica_decoder"),
        ("nativeFilter", "LeicaLmsrawFilter", "leica_lmsraw_filter"),
    ):
        library = ctypes.CDLL(str(directory / library_filename(stem)))
        api = getattr(library, symbol + "_api_version")
        api.restype = ctypes.c_uint32
        version = getattr(library, symbol + "_version")
        version.restype = ctypes.c_char_p
        provenance[key + "Version"] = version().decode("ascii")
        provenance[key + "Api"] = int(api())
    MANIFEST.write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print("Recorded source provenance:", provenance["sourceCommit"])


if __name__ == "__main__":
    main()
