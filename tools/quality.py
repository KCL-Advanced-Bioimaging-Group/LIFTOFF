"""Run every required quality tool on all maintained Python sources."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIRECTORIES = {
    ".git",
    ".venv",
    ".bootstrap",
    ".python",
    ".cache",
    ".agents",
    ".codex",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "validation",
    "validation_artifacts",
}


def maintained_files() -> list[str]:
    """Include application, utilities, build tools, and tests
    equally.
    """
    files = []
    for directory, subdirectories, filenames in ROOT.walk():
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in GENERATED_DIRECTORIES
        ]
        files.extend(
            str((directory / filename).relative_to(ROOT))
            for filename in filenames
            if filename.endswith(".py")
        )
    return sorted(files)


def main() -> int:
    """Return failure if formatting, linting, analysis, or typing
    fails.
    """
    files = maintained_files()
    environment = os.environ.copy()
    environment["PYLINTHOME"] = str(ROOT / ".cache" / "pylint")
    commands = [
        [sys.executable, "-m", "ruff", "format", "--check", *files],
        [sys.executable, "-m", "ruff", "check", *files],
        [sys.executable, "-m", "pylint", *files],
        [
            sys.executable,
            "-m",
            "pyrefly",
            "check",
            *files,
            "--min-severity",
            "warn",
            "--error",
            "unnecessary-type-conversion",
            "--error",
            "unreachable",
            "--python-interpreter-path",
            sys.executable,
        ],
    ]
    failed = False
    for command in commands:
        print("Running", " ".join(command[:5]), flush=True)
        result = subprocess.run(
            command, cwd=ROOT, env=environment, check=False
        )
        failed = failed or result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
