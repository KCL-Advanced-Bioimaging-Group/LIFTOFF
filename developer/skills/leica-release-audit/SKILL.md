---
name: leica-release-audit
description: Audit LIFTOFF release readiness with recorded quality, scientific, native-code, failure-recovery, dependency, GUI, and packaging evidence. Use when asked to run a pre-release audit, check release blockers, prepare a release candidate, update or rebuild the standalone executable, or release a new version to collaborators. Support audit-only and build-and-verify requests; never treat missing external validation as a pass.
---

# LIFTOFF release audit

Operate from the source root identified by `pyproject.toml`,
`leica_flim_converter/`, `native/`, and `tools/build.py`. Resolve resource
paths relative to this skill. Read [acceptance.md](references/acceptance.md)
before auditing. Use [report-template.md](assets/report-template.md) for
the final report.

## Establish scope

- **Audit only:** Execute available checks, investigate findings, implement
  appropriate fixes within the requested scope, and report readiness. Do not
  bump versions or rebuild/distribute the application.
- **Build and verify:** Complete source acceptance, update the requested
  version consistently, rebuild both native libraries and the standalone
  bundle, and validate the exact candidate. Build after source gates pass,
  or when explicitly requested as a diagnostic build. Label diagnostic
  builds unaccepted; never replace an accepted delivery with one.
- **Distribute:** Distribute only when requested and required gates pass.
  Invoking/creating this skill alone does not authorize contacting people.
  Prepare the candidate and report while external checks remain blocked.
  Do not repeatedly ask for approval already given.

Audit the current version when none is supplied. For an authorized new
release, derive and explain a suitable version from the changes and existing
convention; clarify only a material ambiguity. Do not silently reuse an
accepted release identifier.

## Inspect and plan

Read current instructions and maintained sources; do not reuse old test
totals, hashes, native API numbers or platform claims as fresh evidence:

- `README.md`, `pyproject.toml`, `developer/PYTHON_CODE_QUALITY.md`,
  `developer/BUILD.md`;
- `developer/SCIENTIFIC_SEMANTICS.md`, `developer/history/PARITY_REPORT.md`,
  and `RELEASE_NOTES.md`;
- `tools/quality.py`, `tools/build.py`, `tools/provenance.py`;
- `leica_flim_converter/release_check.py`, relevant tests/fixture manifests.

Inspect Git status/diff, Python/native changes, dependencies, available
data/tools, compiler generators, target systems, downstream readers and
existing evidence. Preserve unrelated work. Do not stage/commit unrelated
edits or upload acquisitions/binaries to external services without permission.

Create a fresh evidence directory under
`validation_artifacts/release-readiness/<version>/<UTC timestamp>/`, outside the input
data directory. Maintain every acceptance gate with status, commands, exit
codes, dated artifacts, scope and limitations. Use `PASS`, `FAIL`, `BLOCKED`,
`NOT_RUN` or technically justified `NOT_APPLICABLE`. Treat required missing
tools/data/environments and unreviewed skips/xfails as blockers. Separate
expected damaged-input rejection from successful decoding.

## Execute source acceptance

Select the project interpreter: `.venv/Scripts/python.exe` on Windows or
`.venv/bin/python` on POSIX. Confirm the required Python version. Preview:

```powershell
.venv\Scripts\python.exe developer/skills/leica-release-audit/scripts/audit_source.py --plan
```

Collect automated evidence with an explicit corpus and new output directory:

```powershell
.venv\Scripts\python.exe developer/skills/leica-release-audit/scripts/audit_source.py --data C:\data\LeicaExamples --output validation_artifacts/release-readiness/<version>/<UTC>/source
```

The runner records source identity/hashes, version consistency, dependency
inventory, quality checks, `pip check`, full pytest/JUnit outcomes, optional
branch coverage and advisory audit. Missing coverage/advisory tools produce
blocked gates. It never installs tools, changes application code, builds or
declares complete release readiness. Exit codes: 0 passed automated source
gates; 1 failed; 2 blocked. Inspect every log and skipped/xfail reason.

Supply isolated audit tooling as needed, recording exact tool versions and
environment. Check official documentation before adding tools. Preserve
validated runtime pins; do not install arbitrary latest dependencies into
the development environment or automatically apply dependency-audit fixes.

Complete all scientific, downstream-reader, test-effectiveness, native,
fault-injection, performance and GUI gates in the acceptance reference. The
runner alone does not supply those judgments. Reuse existing tests and
stress tools; add focused checks for demonstrated gaps. An oracle calling
the implementation under test or sharing its parser is not independent.
Correct actionable failures and rerun affected checks plus required regressions.

## Rebuild and verify when requested

1. Update `leica_flim_converter/version.py`, `pyproject.toml`,
   `tools/windows_version.txt`, README and release notes. Verify runtime,
   executable properties and PTU creator versions. Keep native API/library
   versions separate. Freeze reviewed source identity, recording unavoidable
   generated DLL/provenance changes with hashes and explanations.
2. Inspect the available compiler generator and cached configuration, then
   rebuild both libraries with the existing host build tool. Validate the
   scientific/native checks against the pair to be packaged.
3. Run `python -m tools.build --generator <actual-generator>` on the target
   OS. Do not assume a Visual Studio version. This also rebuilds native code
   and refreshes provenance; compare against the tested pair and revalidate
   differences. Preserve the previous accepted release.
4. Prepare the new candidate under `dist/<target>/` with executable,
   `_internal`, release README, applicable notices and provenance. Audit
   native dependencies, architecture, import symbols and Qt plugins; reject
   foreign PATH libraries.
5. Run the actual executable with `--verify-release <new-evidence-dir>` and
   repeated `--verify-lif <fixture>`. Add `--expect-unreadable` and
   `--verify-gui-acquisition` with names from current inputs. Inspect
   `result.json`: require `passed`, `frozen`, correct version/native pair,
   nonempty intended decoding checks and all required cases. A startup-only
   pass or zero exit code alone is insufficient.
6. Test the copied candidate from another working directory under a standard
   account with source/Python/Qt/library overrides removed. Exercise normal
   visible startup and complete GUI workflows. Headless/offscreen tests do
   not establish visible desktop or clean-machine acceptance.
7. Complete independent supported-machine/clean-VM, downstream-reader and
   authorized pilot checks. If unavailable, retain the candidate, mark
   distribution blocked, and continue all independent work. Never invent a
   pass or request an approval that cannot supply missing evidence.
8. Apply signing when credentials and scope permit, preserving credentials.
   Record unsigned status when signing is not a requirement. Signing does
   not establish scientific validity.
9. After payload changes, create and verify a checksum manifest:

   ```powershell
   .venv\Scripts\python.exe developer/skills/leica-release-audit/scripts/bundle_manifest.py create <candidate-folder>
   .venv\Scripts\python.exe developer/skills/leica-release-audit/scripts/bundle_manifest.py verify <candidate-folder>
   ```

   Hash the final archive separately. Retain build/test/source evidence for
   that exact artifact; test execution-affecting signing/packaging changes.
   Reverify payload and archive hashes after copying to the delivery location.

## Report and finish

Complete the report with source/version identity, corpus/platforms, gate
evidence, fixes, skips, limitations, scientific changes, candidate/archive
hashes and rollback. Invalidate evidence when its source, native pair,
configuration, corpus or candidate changes.

Choose **NOT READY** for any required failed/blocked/not-run gate. Use
**SOURCE READY; DISTRIBUTION BLOCKED** only after complete source acceptance
when outstanding items concern packaged/external validation. Use **READY
FOR DISTRIBUTION** only when every required gate passes for the exact
artifact. Never silently downgrade a required gate to a warning.

Present the report and authorized candidate, explain blockers and state
whether rebuilding/distribution occurred. Do not imply that creating this
skill ran a release audit or updated the executable.
