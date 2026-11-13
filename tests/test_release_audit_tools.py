"""Test audit integrity, skipped tests and payload verification."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

audit_source = importlib.import_module(
    "developer.skills.leica-release-audit.scripts.audit_source"
)
bundle_manifest = importlib.import_module(
    "developer.skills.leica-release-audit.scripts.bundle_manifest"
)


@pytest.mark.parametrize(
    ("xml", "expected"),
    [
        ("<testsuites/>", "FAIL"),
        ("<invalid", "FAIL"),
        ("<testsuite><testcase><failure/></testcase></testsuite>", "FAIL"),
        ("<testsuite><testcase><error/></testcase></testsuite>", "FAIL"),
        ("<testsuite><testcase><skipped/></testcase></testsuite>", "BLOCKED"),
        ("<testsuite><testcase/></testsuite>", "PASS"),
    ],
)
def test_junit_outcomes(tmp_path: Path, xml: str, expected: str) -> None:
    """Reject invalid reports and preserve failure/skip semantics."""
    path = tmp_path / "tests.xml"
    path.write_text(xml, encoding="utf-8")
    assert audit_source.junit_gate(path).status == expected


def test_missing_junit_fails(tmp_path: Path) -> None:
    """Missing JUnit evidence must fail the regression gate."""
    assert audit_source.junit_gate(tmp_path / "missing.xml").status == "FAIL"


@pytest.mark.parametrize(
    ("dependencies", "status"),
    [
        ([], "FAIL"),
        ([{"name": "a", "vulns": []}], "PASS"),
        ([{"name": "a", "skip_reason": "not found"}], "BLOCKED"),
        ([{"name": "a", "vulns": [{"id": "example"}]}], "FAIL"),
    ],
)
def test_advisory_skips_and_findings(
    tmp_path: Path, dependencies: list, status: str
) -> None:
    """Do not hide advisory findings or unresolved dependency checks."""
    path = tmp_path / "advisories.json"
    path.write_text(
        json.dumps({"dependencies": dependencies}), encoding="utf-8"
    )
    assert audit_source.advisory_gate(path).status == status


def test_failed_command_preserves_evidence(tmp_path: Path) -> None:
    """Retain a failing check's output and actual exit code."""
    gate = audit_source.run_command(
        "probe",
        [sys.executable, "-c", "print('evidence'); exit(7)"],
        tmp_path,
        tmp_path,
        os.environ.copy(),
        10,
    )
    assert gate.status == "FAIL"
    assert "exit=7" in gate.detail
    assert "evidence" in Path(gate.evidence).read_text("utf-8")


def test_timeout_cannot_pass(tmp_path: Path) -> None:
    """A timed-out check must fail with diagnostic evidence."""
    gate = audit_source.run_command(
        "timeout",
        [sys.executable, "-c", "import time; time.sleep(5)"],
        tmp_path,
        tmp_path,
        os.environ.copy(),
        1,
    )
    assert gate.status == "FAIL"


def test_failure_priority() -> None:
    """Do not hide an observed failure behind missing evidence."""
    blocked = audit_source.Gate("missing", "BLOCKED", "No evidence")
    failed = audit_source.Gate("broken", "FAIL", "Incorrect counts")
    assert audit_source.exit_status([blocked]) == 2
    assert audit_source.exit_status([blocked, failed]) == 1


def test_source_hashes_detect_changes(tmp_path: Path) -> None:
    """Invalidate evidence for added, changed and removed inputs."""
    source = tmp_path / "app.py"
    source.write_text("original", encoding="utf-8")
    original = audit_source.source_hashes(tmp_path)
    source.write_text("changed", encoding="utf-8")
    assert original != audit_source.source_hashes(tmp_path)
    source.unlink()
    assert original != audit_source.source_hashes(tmp_path)
    source.write_text("original", encoding="utf-8")
    (tmp_path / "new.py").write_text("new", encoding="utf-8")
    assert original != audit_source.source_hashes(tmp_path)


def test_automation_is_not_release_acceptance(tmp_path: Path) -> None:
    """Leave full release acceptance pending after passed automation."""
    audit_source.write_summary(
        tmp_path, [audit_source.Gate("probe", "PASS", "Checked")]
    )
    report = json.loads((tmp_path / "automated.json").read_text("utf-8"))
    assert report["releaseReady"] is False
    assert report["exitCode"] == 0


@pytest.fixture(name="candidate")
def candidate_fixture(tmp_path: Path) -> Path:
    """Create a candidate with an executable, library and manifest."""
    (tmp_path / "app.exe").write_bytes(b"candidate")
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "native.dll").write_bytes(b"native")
    bundle_manifest.create_manifest(tmp_path)
    return tmp_path


def test_unchanged_payload_verifies(candidate: Path) -> None:
    """Include nested payloads and exclude only the manifest itself."""
    assert bundle_manifest.verify_manifest(candidate)
    manifest = json.loads(
        (candidate / bundle_manifest.MANIFEST_NAME).read_text("utf-8")
    )
    assert set(manifest["files"]) == {"app.exe", "_internal/native.dll"}


def test_same_size_modified_payload_fails(candidate: Path) -> None:
    """Detect content changes even when the file size is unchanged."""
    (candidate / "app.exe").write_bytes(b"modified!")
    assert not bundle_manifest.verify_manifest(candidate)


def test_missing_payload_fails(candidate: Path) -> None:
    """Reject a bundle with a missing nested dependency."""
    (candidate / "_internal/native.dll").unlink()
    assert not bundle_manifest.verify_manifest(candidate)


def test_extra_payload_fails(candidate: Path) -> None:
    """Reject extra files, including accidental private payloads."""
    (candidate / "unintended.txt").write_text("private", encoding="utf-8")
    assert not bundle_manifest.verify_manifest(candidate)


def test_manifest_overwrite_refused(candidate: Path) -> None:
    """Do not replace evidence belonging to an existing candidate."""
    with pytest.raises(FileExistsError):
        bundle_manifest.create_manifest(candidate)


def test_empty_payload_refused(tmp_path: Path) -> None:
    """An empty candidate must never acquire a valid manifest."""
    with pytest.raises(ValueError):
        bundle_manifest.create_manifest(tmp_path)


def test_non_object_manifest_fails(candidate: Path) -> None:
    """Reject syntactically valid JSON with an invalid schema."""
    (candidate / bundle_manifest.MANIFEST_NAME).write_text(
        "[]", encoding="utf-8"
    )
    assert not bundle_manifest.verify_manifest(candidate)


@pytest.mark.parametrize("scenario", ["pass", "test-failure", "bad-version"])
def test_source_audit_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """Execute child checks against disposable project fixtures."""
    for name in ("leica_flim_converter", "tools", "tests"):
        (tmp_path / name).mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="audit-fixture"\nversion="1.2.3"\n'
        '[tool.pytest.ini_options]\ntestpaths=["tests"]\n',
        encoding="utf-8",
    )
    runtime_version = "9.9.9" if scenario == "bad-version" else "1.2.3"
    (tmp_path / "leica_flim_converter/version.py").write_text(
        f'APPLICATION_VERSION = "{runtime_version}"\n', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "# Leica Image Files Translated into Open File Formats "
        "(LIFTOFF) 1.2.3\n",
        encoding="utf-8",
    )
    (tmp_path / "tools/windows_version.txt").write_text(
        "filevers=(1, 2, 3, 0)\nprodvers=(1, 2, 3, 0)\n"
        'StringStruct("FileVersion", "1.2.3")\n'
        'StringStruct("ProductVersion", "1.2.3")\n'
        "LIFTOFF_App_1.2.3.exe\n",
        encoding="utf-8",
    )
    (tmp_path / "tools/quality.py").write_text(
        'print("fixture quality check")\n', encoding="utf-8"
    )
    test_passes = scenario != "test-failure"
    (tmp_path / "tests/test_probe.py").write_text(
        f"def test_probe():\n    assert {test_passes}\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        audit_source.importlib.util, "find_spec", lambda _name: None
    )
    output = tmp_path / "evidence"
    expected_exit = 2 if scenario == "pass" else 1
    assert audit_source.run_audit(tmp_path, output, None, 30) == expected_exit
    report = json.loads((output / "automated.json").read_text("utf-8"))
    gates = {gate["name"]: gate["status"] for gate in report["gates"]}
    assert report["releaseReady"] is False
    assert gates["data-corpus"] == "BLOCKED"
    assert gates["dependency-consistency"] == "BLOCKED"
    assert gates["source-stability"] == "PASS"
    assert gates["versions"] == (
        "FAIL" if scenario == "bad-version" else "PASS"
    )
    assert gates["regression-outcomes"] == (
        "FAIL" if scenario == "test-failure" else "PASS"
    )
