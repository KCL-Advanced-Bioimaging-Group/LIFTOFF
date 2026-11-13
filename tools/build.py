"""Build native libraries and optional PyInstaller releases on the
host.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

from leica_flim_converter.platform_paths import library_filename
from leica_flim_converter.version import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
)

ROOT = Path(__file__).resolve().parent.parent
RELEASE_NAME = f"{APPLICATION_NAME}_App_{APPLICATION_VERSION}"
TARGETS = {
    ("Windows", "AMD64"): "Windows_x86_64",
    ("Windows", "x86_64"): "Windows_x86_64",
    ("Linux", "x86_64"): "Linux_x86_64",
    ("Darwin", "arm64"): "macOS_arm64",
    ("Darwin", "x86_64"): "macOS_x86_64",
}


def run(
    arguments: list[str], *, environment: dict[str, str] | None = None
) -> None:
    """Run a build tool without platform-specific shell
    interpolation.
    """
    subprocess.run(arguments, cwd=ROOT, env=environment, check=True)


def packaging_environment() -> dict[str, str]:
    """Prevent unrelated PATH libraries from replacing Windows DLLs."""
    environment = os.environ.copy()
    if platform.system() == "Windows":
        windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
        environment["PATH"] = os.pathsep.join(
            str(path)
            for path in (
                windows / "System32",
                windows,
                Path(sys.executable).parent,
                Path(sys.base_prefix),
            )
        )
    return environment


def build_native(generator: str | None) -> None:
    """Configure, rebuild, and install both C++17 shared libraries."""
    directory = ROOT / "build" / "native"
    configure = [
        sys.executable,
        "-m",
        "cmake",
        "-S",
        str(ROOT),
        "-B",
        str(directory),
    ]
    if generator:
        configure.extend(["-G", generator])
        if generator.startswith("Visual Studio"):
            configure.extend(["-A", "x64"])
    if not generator or not generator.startswith("Visual Studio"):
        configure.append("-DCMAKE_BUILD_TYPE=Release")
    run(configure)
    run(
        [
            sys.executable,
            "-m",
            "cmake",
            "--build",
            str(directory),
            "--config",
            "Release",
            "--parallel",
        ]
    )
    run(
        [
            sys.executable,
            "-m",
            "cmake",
            "--install",
            str(directory),
            "--config",
            "Release",
            "--prefix",
            str(ROOT),
        ]
    )


def pyinstaller_arguments(
    target: str,
    identity: str | None = None,
    entitlements: Path | None = None,
) -> list[str]:
    """Declare a source-based onedir release with bundled native
    code.
    """
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--windowed",
        "--onedir",
        "--name",
        RELEASE_NAME,
        "--distpath",
        str(ROOT / "dist" / target),
        "--workpath",
        str(ROOT / "build" / "pyinstaller" / target),
        "--specpath",
        str(ROOT / "build" / "specs"),
    ]
    for filename in ("provenance.json", "kcl_logo.png"):
        data = ROOT / "leica_flim_converter" / filename
        arguments.extend(["--add-data", f"{data}:leica_flim_converter"])
    if target.startswith("Windows"):
        arguments.extend(
            ["--version-file", str(ROOT / "tools" / "windows_version.txt")]
        )
    for stem in ("LeicaFlimDecoder", "LeicaLmsrawFilter"):
        native = (
            ROOT / "leica_flim_converter" / "native" / library_filename(stem)
        )
        arguments.extend(
            ["--add-binary", (f"{native}:leica_flim_converter/native")]
        )
    if target.startswith("macOS"):
        arguments.extend(
            [
                "--osx-bundle-identifier",
                "org.liftoff.desktop",
                "--target-architecture",
                platform.machine(),
            ]
        )
    if identity:
        arguments.extend(["--codesign-identity", identity])
    if entitlements:
        arguments.extend(
            ["--osx-entitlements-file", str(entitlements.resolve())]
        )
    arguments.append(str(ROOT / "launch_LIFTOFF.py"))
    return arguments


def main() -> None:
    """Require the target host, then build native or frozen
    artifacts.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--generator")
    parser.add_argument("--codesign-identity")
    parser.add_argument("--entitlements", type=Path)
    args = parser.parse_args()
    target = TARGETS.get((platform.system(), platform.machine()))
    if target is None:
        raise SystemExit("Unsupported operating system or architecture")
    if (args.codesign_identity or args.entitlements) and not target.startswith(
        "macOS"
    ):
        parser.error("Signing options require a macOS host")
    if args.entitlements and not args.entitlements.is_file():
        parser.error("The entitlements file does not exist")
    build_native(args.generator)
    run([sys.executable, "-m", "tools.provenance"])
    if not args.native_only:
        run(
            pyinstaller_arguments(
                target, args.codesign_identity, args.entitlements
            ),
            environment=packaging_environment(),
        )


if __name__ == "__main__":
    main()
