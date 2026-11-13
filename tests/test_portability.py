"""Verify portable discovery and host-specific build configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from leica_flim_converter import platform_paths
from tools.build import pyinstaller_arguments


@pytest.mark.parametrize(
    ("system", "machine", "target", "suffix"),
    [
        ("Windows", "AMD64", "Windows_x86_64", ".dll"),
        ("Linux", "x86_64", "Linux_x86_64", ".so"),
        ("Darwin", "arm64", "macOS_arm64", ".dylib"),
        ("Darwin", "x86_64", "macOS_x86_64", ".dylib"),
    ],
)
def test_host_build_inputs(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    target: str,
    suffix: str,
) -> None:
    """Each future build bundles the corresponding C ABI libraries."""
    monkeypatch.setattr(platform_paths.platform, "system", lambda: system)
    monkeypatch.setattr(platform_paths.platform, "machine", lambda: machine)
    arguments = pyinstaller_arguments(target)
    libraries = [
        arguments[index + 1]
        for index, value in enumerate(arguments)
        if value == "--add-binary"
    ]
    assert len(libraries) == 2
    assert all(
        suffix + ":leica_flim_converter/native" in path for path in libraries
    )
    name = arguments[arguments.index("--name") + 1]
    assert name.startswith("LIFTOFF_App_")
    assert Path(arguments[-1]).name == "launch_LIFTOFF.py"
    assert Path(arguments[-1]).is_file()
    assert "--runtime-hook" not in arguments
    assert "--add-data" in arguments
    if system == "Darwin":
        assert (
            arguments[arguments.index("--target-architecture") + 1] == machine
        )
        assert "--osx-bundle-identifier" in arguments


def test_frozen_resource_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Frozen lookup uses the bundle resource root, independently of
    cwd.
    """
    monkeypatch.setattr(
        platform_paths.sys, "_MEIPASS", str(tmp_path), raising=False
    )
    assert platform_paths.resource_root() == tmp_path
    filename = platform_paths.library_filename("LeicaFlimDecoder")
    assert tmp_path / "leica_flim_converter/native" / filename in (
        platform_paths.native_library_candidates("LeicaFlimDecoder")
    )


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_log_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    system: str,
) -> None:
    """Platform data paths remain writable and explicitly
    overridable.
    """
    monkeypatch.setattr(platform_paths.platform, "system", lambda: system)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("LIFTOFF_LOG_DIR", raising=False)
    monkeypatch.delenv("LEICA_INTERROGATOR_LOG_DIR", raising=False)
    path = platform_paths.application_data_dir()
    assert path.name == "LIFTOFF"
    if system == "Windows":
        assert path.parent == tmp_path / "local"
    elif system == "Linux":
        assert path.parent == tmp_path / "xdg"
    else:
        assert path.parent == Path.home() / "Library/Application Support"
    legacy_logs = tmp_path / "legacy-logs"
    monkeypatch.setenv("LEICA_INTERROGATOR_LOG_DIR", str(legacy_logs))
    assert platform_paths.log_directory() == legacy_logs
    monkeypatch.setenv("LIFTOFF_LOG_DIR", str(tmp_path / "logs"))
    assert platform_paths.log_directory() == tmp_path / "logs"
    assert (tmp_path / "logs").is_dir()
