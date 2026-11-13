# Release acceptance checks

## Gate matrix

Read every gate. Scale depth to changes/risks. Reuse evidence only when the
source/native identity and relevant behaviour match; never carry old totals.

| Gate | Required acceptance evidence |
| --- | --- |
| Source identity | Reviewed snapshot, intended changes tracked, revision and hashes, no unexplained modifications; unrelated work preserved. |
| Versions | Agreement across Python metadata, runtime, executable properties, filenames, docs and export creators; native versions separate. |
| Python quality | Current `tools/quality.py` passes without actionable diagnostics or broadened suppressions/exclusions. |
| Regression corpus | Full suite with required real data, no unreviewed skips/xfails; expected damaged-input rejections separately verified. |
| Scientific correctness | Independent references and known-answer fixtures establish complete spatial/time arrays, calibration and photon accounting. |
| Downstream compatibility | Representative PTU/ICS checked by independent readers and intended collaborator software; record versions. |
| Test effectiveness | Critical branch coverage reviewed and meaningful deliberate defects detected; unexplained critical gaps resolved. |
| Native safety | Both rebuilt libraries, compiler/static analysis, ABI checks, instrumented memory-safety runs and bounded malformed-input fuzzing. |
| Fault recovery | Controlled I/O/resource failures and cancellation preserve originals/existing outputs, clean incomplete artifacts and leave the app usable. |
| Performance | Large-data and repeated-operation/soak measurements against recorded baseline; no unexplained accumulating resources or degradation. |
| GUI acceptance | Complete selection/ROI/preview/filter/export/reopen workflows; no stale state or worker races; useful errors/diagnostics. |
| Dependencies | Direct/transitive inventory, Python and native/Qt advisory review, compatible pins, required notices, no accidental private payloads. |
| Build provenance | Interpreter, packages, compiler/packager inventory; fresh-environment build; tested native hashes match packaged provenance. |
| Frozen candidate | Real executable verifies required fixtures/exports, version and dependencies; normal GUI, standard-account and foreign-CWD checks. |
| Independent machine | Supported target verified on second PC/clean VM without development Python/tools, using realistic permissions and paths. |
| Delivery and rollback | Payload/archive checksums, complete folder/notices, notes/limitations, pilot evidence, preserved prior release and rollback procedure. |

## Scientific matrix

Derive the supported matrix from current contracts/tests. Include LMSRAW and
compressed sources; All/First/Single photons; individual/summed T/Z planes;
first/last available planes; routes and sequential/mixed excitation;
Navigator/multichannel mosaics; complete/partial stacks; native/rebinned
timing; ROIs; reflection preview and export exclusions.

Use current `tests/fixtures` hashes and Leica/LAS X/PTU evidence. Independently
justify intentional differences from the previous release. Compare complete
arrays/orientation as well as sums. Require exact integer-count agreement;
state floating tolerances and physical units. Reconcile selected photons with
exported, reflection-excluded and outside-window counts using current
precedence rules. Check laser period, clock, endpoints, overflow, raster
markers, scan timing and empty logical scan lines. Preserve raw inputs.

Check provenance, detector/sequence associations, wavelength labels versus
source precision, dimensions, stage/T/Z indexing and missing metadata. Use
positive/negative controls. Prove that preview-only changes do not alter
exports and opt-in export filters capture immutable correct bounds/coverage.

Read relevant `test_reference_science.py`, `test_reference_exports.py`,
`test_timing*.py`, `test_compressed*.py`, `test_multichannel_mosaic*.py`,
`test_sequences.py`, `test_sequence_ptus.py`, `test_reflection*.py`,
`test_export_metadata.py` and `test_safety.py`; discover renamed/new tests.
Unresolved/damaged acquisitions must fail visibly. A previous app establishes
regression behaviour, but is not automatically a scientific oracle.

Inspect `tools/stress_audit.py --help`, then use the maintained CLI:

```powershell
.venv\Scripts\python.exe -m tools.stress_audit --input <data-root> --output <new-output> --phase references
.venv\Scripts\python.exe -m tools.stress_audit --input <data-root> --output <new-output> --phase exports
.venv\Scripts\python.exe -m tools.stress_audit --input <data-root> --output <new-output> --phase overviews
```

Inspect counts: an empty scan is not a pass. Resumable logs can skip completed
cases, so use fresh outputs for a new snapshot. Keep outputs outside inputs.
Record sampling, limits, workers and unexamined planes. Bound resource use.

## Test strength and recovery

Review critical branch coverage without letting a global percentage hide an
untested critical path. Target mutations to endpoints, units, event flags,
routes, overflow and filter accounting. Introduce deliberate defects only in
a disposable copy/worktree and require associated tests to detect them.

Use generative/property checks for justified selection relationships,
sum-of-planes consistency, batching/thread determinism, boundary bins, record
limits, malformed lengths and partial data. State assumptions; bound runtime,
memory and seeds. Do not mistake generative volume for independent truth.

Exercise pre/mid-decode and mid-write cancellation, denied permissions, low
disk space, existing destinations, unavailable paths, partial writes,
unsupported data and memory pressure. Inject faults instead of filling real
disks or exhausting the workstation. Check atomic publication/cleanup of
payloads and companions, protected existing outputs, handles and UI state.

## Native and dependency checks

Inspect CMake, both implementations/headers and ctypes boundaries. Check
widths/signedness, shapes/contiguity, lifetimes, bounds, integer overflow,
cancellation and partitions. Use an instrumented test build with
AddressSanitizer and applicable undefined-behaviour checks on a supported
toolchain. Keep instrumented libraries out of releases. Record unsupported
checks as blocked external jobs. Review compiler/static-analysis findings.

Run `pip check` and current advisory auditing, recording tool/database time,
versions, unresolved/skipped packages and findings. Review bundled Qt,
imaging/native libraries and runtimes separately; Python advisories do not
cover every shared library. Preserve an inventory/SBOM and required notices.
Assess applicability rather than automatically upgrading scientific pins.
Use primary documentation/advisories. Check private data, credentials,
unnecessary debug payloads and source paths in distribution. Never upload
the bundle externally without permission. Record signing/policy requirements.

## Environment, GUI and rollout

Record actual OS build, architecture and minimum supported environment.
Test display scaling, spaces/non-ASCII paths, read-only install locations,
writable user logs, and network paths if used. Sanitizing PATH on the build
PC does not replace independent-machine acceptance.

Exercise GUI changes visibly: selection changes during work, new-file load,
close/cancel, keyboard use, progress, ROI/pixel/channel/plane switching and
export settings. Track memory/handles and responsiveness during repeated
operations. Compare performance on matching corpus/hardware/options and
investigate material regressions; do not invent a universal threshold.

Pilot on representative collaborator data, preserving originals. Contact
people only when explicitly authorized. Record the exact candidate hash and
actual observations. Keep the prior version separately; demonstrate switching
back preserves data access. Document scientific changes/incompatibilities.
