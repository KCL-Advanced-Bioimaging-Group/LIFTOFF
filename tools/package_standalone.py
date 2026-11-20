"""Archive a PyInstaller build and smoke-test its extracted copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from importlib.metadata import distribution
from pathlib import Path

from leica_flim_converter.version import APPLICATION_VERSION
from tools.build import RELEASE_NAME, ROOT, TARGETS

RUNTIME_DISTRIBUTIONS = (
    "defusedxml",
    "numpy",
    "Pillow",
    "PyInstaller",
    "PySide6",
    "PySide6-Addons",
    "PySide6-Essentials",
    "shiboken6",
)


def copy_notices(bundle: Path) -> None:
    """Preserve license files declared in the runtime wheels."""
    notices = bundle / "THIRD_PARTY_LICENSES"
    notices.mkdir()
    for name in RUNTIME_DISTRIBUTIONS:
        installed = distribution(name)
        for entry in installed.files or ():
            metadata_dir, *relative = entry.parts
            if not relative or not metadata_dir.endswith(".dist-info"):
                continue
            if relative[0] == "licenses" or entry.name.startswith("LICENSE"):
                destination = notices.joinpath(name, *relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(entry.locate(), destination)

    for directory in (
        Path(sys.base_prefix),
        Path(sysconfig.get_path("stdlib")),
    ):
        license_path = directory / "LICENSE.txt"
        if license_path.is_file():
            shutil.copyfile(license_path, notices / "CPython-LICENSE.txt")
            break


def smoke_environment(evidence: Path) -> dict[str, str]:
    """Use bundled resources and write diagnostics outside the app."""
    overrides = (
        "PYTHON",
        "QT_",
        "QML",
        "LD_",
        "DYLD_",
        "LEICA_",
        "_PYI_",
        "PYINSTALLER_",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(overrides)
    }
    environment["QT_QPA_PLATFORM"] = os.environ.get(
        "QT_QPA_PLATFORM", "offscreen"
    )
    environment["LIFTOFF_LOG_DIR"] = str(evidence)
    if platform.system() == "Windows":
        windows = Path(os.environ["SystemRoot"])
        environment["PATH"] = os.pathsep.join(
            map(str, (windows / "System32", windows))
        )
    return environment


def verify_bundle(bundle: Path, executable: Path, evidence: Path) -> None:
    """Check the frozen GUI and both bundled native libraries."""
    evidence.mkdir()
    try:
        subprocess.run(
            [str(bundle / executable), "--verify-release", str(evidence)],
            cwd=evidence,
            env=smoke_environment(evidence),
            check=True,
            timeout=120,
        )
        result_text = (evidence / "result.json").read_text(encoding="utf-8")
        report = json.loads(result_text)
        print(result_text)
        app = report["application"]
        decoder = report["native"]
        paths = (decoder.get("path", ""), report["filterLibrary"])
        if not (
            report["passed"]
            and report["frozen"]
            and app["version"] == APPLICATION_VERSION
            and decoder["available"]
            and all(
                Path(path).resolve().is_relative_to(bundle) for path in paths
            )
        ):
            raise SystemExit("The extracted application failed its smoke test")
        revision = os.environ.get("LIFTOFF_SOURCE_COMMIT")
        provenance = app["reconstruction"]
        if revision and (
            provenance["sourceCommit"] != revision
            or provenance["sourceModified"]
        ):
            raise SystemExit(
                "The bundle does not identify the clean CI checkout"
            )
    finally:
        for log in sorted(evidence.glob("*.log")):
            print(log.read_text(encoding="utf-8", errors="replace"))


def package(target: str) -> None:
    """Archive the full onedir build or macOS application bundle."""
    system = platform.system()
    source = ROOT / "dist" / target
    output = ROOT / "dist" / "archives"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="liftoff-") as directory:
        staging = Path(directory).resolve()
        bundle = staging / RELEASE_NAME
        if system == "Darwin":
            app = f"{RELEASE_NAME}.app"
            bundle.mkdir()
            shutil.copytree(source / app, bundle / app, symlinks=True)
            executable = Path(app, "Contents", "MacOS", RELEASE_NAME)
            launcher = app
        else:
            shutil.copytree(source / RELEASE_NAME, bundle, symlinks=True)
            launcher = (
                f"{RELEASE_NAME}.exe" if system == "Windows" else RELEASE_NAME
            )
            executable = Path(launcher)
        for filename in ("LICENSE", "USER_GUIDE.md"):
            shutil.copyfile(ROOT / filename, bundle / filename)
        copy_notices(bundle)
        (bundle / "README.txt").write_text(
            f"LIFTOFF {APPLICATION_VERSION} for {target}\n\n"
            f"Extract the entire archive and open {launcher}.\n"
            "Keep the extracted files together. See USER_GUIDE.md for help.\n",
            encoding="utf-8",
        )

        archive_format = "zip" if system == "Windows" else "gztar"
        archive = Path(
            shutil.make_archive(
                str(staging / f"{RELEASE_NAME}_{target}"),
                archive_format,
                root_dir=staging,
                base_dir=RELEASE_NAME,
            )
        )
        extracted = staging / "extracted"
        if archive_format == "zip":
            shutil.unpack_archive(archive, extracted)
        else:
            shutil.unpack_archive(archive, extracted, filter="data")
        verify_bundle(
            extracted / RELEASE_NAME, executable, staging / "evidence"
        )
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        shutil.move(archive, output / archive.name)
        (output / f"{archive.name}.sha256").write_text(
            f"{digest}  {archive.name}\n", encoding="ascii", newline="\n"
        )
        print(f"Archived and verified {archive.name} ({digest})")


def main() -> None:
    """Package only the build matching the current host and Python."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=sorted(set(TARGETS.values())))
    args = parser.parse_args()
    host = (platform.system(), platform.machine())
    if TARGETS.get(host) != args.target:
        parser.error(f"{args.target} does not match the build host {host}")
    package(args.target)


if __name__ == "__main__":
    main()
