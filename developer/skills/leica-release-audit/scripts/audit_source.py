"""Collect source-check evidence without building a release."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SOURCE_DIRS = (
    "leica_flim_converter",
    "native",
    "tests",
    "tools",
    "developer",
    ".agents/skills/leica-release-audit",
)
EXCLUDED = {"__pycache__", ".cache", ".pytest_cache", ".ruff_cache"}


@dataclass
class Gate:
    """A bounded claim, never a complete release-acceptance decision."""

    name: str
    status: str
    detail: str
    evidence: str = ""


def source_hashes(root: Path) -> dict[str, str]:
    """Hash maintained sources, fixtures, docs and native binaries."""
    files = [path for path in root.iterdir() if path.is_file()]
    for directory in SOURCE_DIRS:
        path = root / directory
        if path.exists():
            files.extend(item for item in path.rglob("*") if item.is_file())
    result = {}
    for path in sorted(files):
        relative = path.relative_to(root)
        if EXCLUDED.intersection(relative.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Source link needs review: {relative}")
        with path.open("rb") as stream:
            result[relative.as_posix()] = hashlib.file_digest(
                stream, "sha256"
            ).hexdigest()
    return result


def version_gate(root: Path) -> Gate:
    """Compare version fields without importing the application."""
    project = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    version = project["project"]["version"]
    module = ast.parse(
        (root / "leica_flim_converter/version.py").read_text("utf-8")
    )
    versions = [
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(item, ast.Name) and item.id == "APPLICATION_VERSION"
            for item in node.targets
        )
        and isinstance(node.value, ast.Constant)
    ]
    resource = (root / "tools/windows_version.txt").read_text("utf-8")
    strings = re.findall(
        r"StringStruct\(['\"](?:FileVersion|ProductVersion)['\"],\s*"
        r"['\"]([^'\"]+)['\"]\)",
        resource,
    )
    tuples = re.findall(r"(?:filevers|prodvers)=\(([^)]+)\)", resource)
    numeric = tuple(int(item) for item in version.split(".")) + (0,)
    valid = (
        versions == [version]
        and strings == [version, version]
        and len(tuples) == 2
        and all(
            tuple(int(item.strip()) for item in value.split(",")) == numeric
            for value in tuples
        )
        and f"LIFTOFF_App_{version}.exe" in resource
        and (
            "# Leica Image Files Translated into Open File Formats "
            f"(LIFTOFF) {version}"
        )
        in (root / "README.md").read_text("utf-8")
    )
    return Gate(
        "versions",
        "PASS" if valid else "FAIL",
        f"Expected application/Windows/README version {version}",
    )


def junit_gate(path: Path) -> Gate:
    """Reject empty, failed or incomplete regression evidence."""
    if not path.is_file():
        return Gate("regression-outcomes", "FAIL", "JUnit report is missing")
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
    except ET.ParseError as error:
        return Gate("regression-outcomes", "FAIL", f"Invalid JUnit: {error}")
    failed = [
        case
        for case in cases
        if case.find("failure") is not None or case.find("error") is not None
    ]
    skipped = [case for case in cases if case.find("skipped") is not None]
    status = (
        "FAIL" if failed or not cases else "BLOCKED" if skipped else "PASS"
    )
    summary = (
        f"{len(cases)} cases; {len(failed)} failed; {len(skipped)} skipped"
    )
    if skipped:
        summary += "; review every skip/xfail in JUnit"
    return Gate("regression-outcomes", status, summary, str(path))


def advisory_gate(path: Path) -> Gate:
    """Keep skipped dependencies and advisory findings visible."""
    if not path.is_file():
        return Gate("advisory-outcomes", "FAIL", "Advisory JSON is missing")
    try:
        report = json.loads(path.read_text("utf-8"))
    except ValueError as error:
        return Gate("advisory-outcomes", "FAIL", str(error), str(path))
    dependencies = (
        report.get("dependencies") if isinstance(report, dict) else []
    )
    if not isinstance(dependencies, list) or not dependencies:
        return Gate(
            "advisory-outcomes", "FAIL", "No audited dependencies", str(path)
        )
    if any(not isinstance(item, dict) for item in dependencies):
        return Gate(
            "advisory-outcomes",
            "FAIL",
            "Invalid dependency records",
            str(path),
        )
    skipped = [
        item
        for item in dependencies
        if item.get("skip_reason") or not isinstance(item.get("vulns"), list)
    ]
    vulnerable = [item for item in dependencies if item.get("vulns")]
    status = "FAIL" if vulnerable else "BLOCKED" if skipped else "PASS"
    return Gate(
        "advisory-outcomes",
        status,
        f"{len(dependencies)} dependencies; {len(vulnerable)} with "
        f"findings; {len(skipped)} skipped/unresolved",
        str(path),
    )


def run_command(
    name: str,
    arguments: list[str],
    root: Path,
    output: Path,
    environment: dict[str, str],
    timeout: int,
) -> Gate:
    """Record commands, exit codes, duration and combined output."""
    logfile = output / f"{name}.log"
    print(f"Running {name}; log: {logfile}", flush=True)
    started = time.monotonic()
    with logfile.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(arguments) + "\n")
        stream.flush()
        try:
            completed = subprocess.run(
                arguments,
                cwd=root,
                env=environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            stream.write(f"\n{type(error).__name__}: {error}\n")
            return Gate(name, "FAIL", str(error), str(logfile))
        detail = (
            f"exit={completed.returncode}; "
            f"seconds={time.monotonic() - started:.2f}"
        )
        stream.write("\n" + detail + "\n")
    return Gate(
        name,
        "PASS" if completed.returncode == 0 else "FAIL",
        detail,
        str(logfile),
    )


def git_gate(root: Path, output: Path) -> Gate:
    """Record dirty/untracked files without altering the index."""
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        status = subprocess.run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *SOURCE_DIRS,
                "*.py",
                "*.toml",
                "*.txt",
                "*.md",
                "*.bat",
                "*.ps1",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return Gate("source-identity", "BLOCKED", str(error))
    path = output / "git.txt"
    path.write_text(
        revision.stdout + status.stdout + revision.stderr + status.stderr,
        encoding="utf-8",
    )
    if (
        revision.returncode
        or status.returncode
        or toplevel.returncode
        or Path(toplevel.stdout.strip()).resolve() != root
    ):
        return Gate(
            "source-identity", "BLOCKED", "Git identity unavailable", str(path)
        )
    dirty = bool(status.stdout.strip())
    return Gate(
        "source-identity",
        "BLOCKED" if dirty else "PASS",
        "Review and freeze modified/untracked source"
        if dirty
        else revision.stdout.strip(),
        str(path),
    )


def exit_status(gates: list[Gate]) -> int:
    """Give failures priority over unavailable evidence."""
    if any(gate.status == "FAIL" for gate in gates):
        return 1
    return 2 if any(gate.status != "PASS" for gate in gates) else 0


def write_summary(output: Path, gates: list[Gate]) -> None:
    """Persist incremental JSON and Markdown outcomes."""
    payload = {
        "scope": "automated source checks only",
        "releaseReady": False,
        "updatedUtc": datetime.now(UTC).isoformat(),
        "exitCode": exit_status(gates),
        "gates": [asdict(gate) for gate in gates],
    }
    (output / "automated.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Automated source evidence",
        "",
        "Complete the skill's acceptance report before release.",
        "",
    ]
    for gate in gates:
        lines.extend(
            [
                f"- **{gate.name}: {gate.status}** — {gate.detail}",
                f"  Evidence: {gate.evidence or 'see detail'}",
            ]
        )
    (output / "AUTOMATED.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run_audit(
    root: Path, output: Path, data: Path | None, timeout: int
) -> int:
    """Run core gates; require the skill to complete acceptance."""
    output.mkdir(parents=True, exist_ok=False)
    initial = source_hashes(root)
    (output / "source-hashes.json").write_text(
        json.dumps(initial, indent=2) + "\n", encoding="utf-8"
    )
    inventory = {
        "startedUtc": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "source": str(root),
        "data": str(data) if data else None,
        "dependencies": sorted(
            (dist.metadata.get("Name", "unknown"), dist.version)
            for dist in importlib.metadata.distributions()
        ),
    }
    (output / "environment.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    gates = [git_gate(root, output), version_gate(root)]
    has_data = data is not None and data.is_dir() and any(data.rglob("*.lif"))
    gates.append(
        Gate(
            "data-corpus",
            "PASS" if has_data else "BLOCKED",
            "Review corpus coverage separately"
            if has_data
            else "Supply --data with required LIF/companion files",
        )
    )
    write_summary(output, gates)
    environment = os.environ.copy()
    if os.name != "nt":
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    if data is not None:
        environment["LEICA_EXAMPLE_DATA_DIR"] = str(data)
    environment["COVERAGE_FILE"] = str(output / ".coverage")
    coverage = importlib.util.find_spec("coverage") is not None
    pytest = [
        "-m",
        "pytest",
        "-ra",
        "--strict-config",
        "--strict-markers",
        f"--basetemp={output / 'pytest'}",
        "-o",
        "xfail_strict=true",
        f"--junitxml={output / 'tests.xml'}",
    ]
    commands = [
        ("quality", [sys.executable, "tools/quality.py"]),
        (
            "regressions",
            [
                sys.executable,
                *(
                    [
                        "-m",
                        "coverage",
                        "run",
                        "--branch",
                        "--source=leica_flim_converter",
                    ]
                    if coverage
                    else []
                ),
                *pytest,
            ],
        ),
    ]
    if importlib.util.find_spec("pip") is not None:
        commands.insert(
            1,
            ("dependency-consistency", [sys.executable, "-m", "pip", "check"]),
        )
    else:
        gates.append(
            Gate(
                "dependency-consistency",
                "BLOCKED",
                "pip is unavailable; check the target environment "
                "using isolated tooling or uv pip check",
            )
        )
    for name, arguments in commands:
        gates.append(
            run_command(name, arguments, root, output, environment, timeout)
        )
        write_summary(output, gates)
    gates.append(junit_gate(output / "tests.xml"))
    if coverage:
        gates.append(
            run_command(
                "branch-coverage",
                [
                    sys.executable,
                    "-m",
                    "coverage",
                    "json",
                    "-o",
                    str(output / "coverage.json"),
                ],
                root,
                output,
                environment,
                timeout,
            )
        )
    else:
        gates.append(
            Gate(
                "branch-coverage",
                "BLOCKED",
                "coverage is not installed; critical review pending",
            )
        )
    if importlib.util.find_spec("pip_audit") is not None:
        gates.append(
            run_command(
                "python-advisories",
                [
                    sys.executable,
                    "-m",
                    "pip_audit",
                    "-f",
                    "json",
                    "-o",
                    str(output / "advisories.json"),
                ],
                root,
                output,
                environment,
                timeout,
            )
        )
        gates.append(advisory_gate(output / "advisories.json"))
    else:
        gates.append(
            Gate(
                "python-advisories",
                "BLOCKED",
                "pip-audit is not installed; native review pending",
            )
        )
    unchanged = initial == source_hashes(root)
    gates.append(
        Gate(
            "source-stability",
            "PASS" if unchanged else "FAIL",
            "Source hashes match"
            if unchanged
            else "Source changed during audit; evidence invalidated",
        )
    )
    write_summary(output, gates)
    print(
        f"Automated exit code {exit_status(gates)}. Full acceptance pending."
    )
    return exit_status(gates)


def main() -> int:
    """Require fresh evidence and refuse writes into inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[4]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(
            "Source/version snapshot; quality; pip check; full pytest/JUnit; "
            "branch coverage; Python advisories; source stability. "
            "No build or complete release acceptance."
        )
        return 0
    if args.output is None or args.timeout < 1:
        parser.error("Supply a new --output directory and positive --timeout")
    root, output = args.root.resolve(), args.output.resolve()
    data = args.data.resolve() if args.data else None
    if output.exists():
        parser.error("Output already exists; use a fresh directory")
    if data is not None and output.is_relative_to(data):
        parser.error("Audit output must be outside the input data directory")
    if not (root / "leica_flim_converter").is_dir():
        parser.error("The source root must contain leica_flim_converter")
    if output == root or any(
        output.is_relative_to(root / part) for part in SOURCE_DIRS
    ):
        parser.error("Keep generated evidence outside maintained source paths")
    return run_audit(root, output, data, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
