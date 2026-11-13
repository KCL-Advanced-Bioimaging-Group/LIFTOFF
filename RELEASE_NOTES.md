# LIFTOFF release notes

The `validation/` paths in older entries refer to the historical evidence
preserved in the local archive. See [Project history](developer/history/HISTORY_README.md).

## 3.2.2

The maintained source was renamed to Leica Image Files Translated into
Open File Formats (LIFTOFF). The source launcher is now
`launch_LIFTOFF.bat`. Future standalone builds use `LIFTOFF_App_<version>`.
This entry records a source update.

## 3.2.1 (Windows release candidate)

Prepared on 10 November 2026 from the maintained source project.

- Validate compressed expected-row counts before descriptor allocations or
  job reservation in the native C API. Decoder version is 3.3.1 / API 6;
  the filter remains 1.2.0 / API 2. Accepted photon semantics are unchanged.
- Reject XML DTD/entity declarations in complete LIF metadata and use
  defusedxml for parsed fragments. Preserve tolerant historical Leica header
  scanning, namespaces, ordinary character escapes and literal CDATA.
  XML metadata is limited to 32 Mi characters.
- Update the Windows runtime to CPython 3.14.10 with Expat 2.9.0, Pillow to
  13.0.0, build setuptools to 84.1.0, and add defusedxml 0.7.1. NumPy 2.5.3
  and PySide6 6.11.1 remain pinned.
- Synchronize rendering before the reflection-export GUI test clicks its
  auto-detection button; retain the original scientific assertions.

The standalone folder is `Leica_Interrogator_App_3.2.1`, containing its
same-named executable and `_internal` runtime. Preserve the previous 3.2.0
and 3.1.0 folders; do not merge their files into this release.

Validation evidence is recorded under
`validation/release-readiness/3.2.1/20261110/`. The final report records actual
outcomes and package hashes. This candidate is unsigned. Second-PC/clean-VM
and actual collaborator PTU/ICS software acceptance remain deferred; local
validation does not substitute for those checks.

## 3.2.0 (Windows release candidate)

Prepared on 10 November 2026 from the maintained source tree, incorporating
the current image contrast, logarithmic histogram controls, reflection
selection/filter/export workflows and expanded acquisition metadata reports.
Application and Windows executable versions are 3.2.0. Native library/API
versions are maintained separately and recorded in packaged provenance.

The complete application folder is `Leica_Interrogator_App_3.2.0`, containing
`Leica_Interrogator_App_3.2.0.exe` and its `_internal` runtime. Preserve the
previous 3.1.0 folder for rollback. Do not mix files from different versions.

Evidence and remaining audit limitations are recorded under
`validation/release-320/`. This build is unsigned; independent clean-machine
and collaborator-software acceptance remains pending. Building a candidate
does not declare all release-readiness gates passed.

## 3.1.0 (Windows release)

Built and delivered on 19 October 2026 using the same self-contained
PyInstaller folder layout and dependency checks as release 3.0.0.

Delivery folder:
`Leica_Interrogator_App_3.1.0`.

Start `Leica_Interrogator_App_3.1.0.exe`. Keep `_internal` beside it;
copy the entire folder when moving the application. The folder also
contains `README.md`, upstream licence notices and `RELEASE_MANIFEST.json`.
There are 257 checksummed payload files, totalling 163,416,854 bytes
(approximately 155.8 MiB), plus the manifest itself.

### Included changes

- Independent WLL/MP excitation sources, recorded detector pairs and timing.
- Whole-nanometre optical labels with exact source metadata retained in exports.
- Navigator mosaic decoding and matrix viewers, combined graphs by default,
  optional separate tile graphs and correct all-pixel/hover behaviour.
- Pixel hover across channel comparisons and validated multichannel mosaics.
- Shared calibrated arrival bins for the viewer and ICS; explicit PTU timeline
  provenance and native arrival values.
- Evidence-based recovery of recorded planes from incomplete compressed stacks,
  including both channels of `paneth_ctx555_5` at Z=1 through Z=10.
- Rejection of incomplete photon payloads, including the independently verified
  missing stream suffix and row index in `paneth_ctx555_7`.

The application, Windows file/product properties and exported PTU creator version
are **3.1.0**. Native library versions remain separate: decoder 3.3.0/API 6 and
filter 1.2.0/API 2. Both were rebuilt/checked from the maintained C++ source.
Python 3.14.6, NumPy 2.5.3, Pillow 12.3.0, PySide6/Qt 6.11.1 and required
Microsoft C/C++ runtimes are bundled.

### Release verification

- **301 general regression tests passed**. All 110 maintained Python files
  pass Ruff formatting/linting, Pylint (10.00/10) and Pyrefly (zero diagnostics).
- The actual frozen executable passed **107 native decoding checks** across
  **92 distinct channel datasets**, including first/last available planes.
  Inputs included No 2, HCC timelapses, the real Navigator mosaic, the supplied
  mixed-source file and three synthetic sequence/T/Z/mosaic fixtures.
- **20 synthetic PTU/ICS round trips** passed in the executable. The packaged
  PTUs identify creator version 3.1.0.
- **Five production viewer checks** passed: mixed T/Z pairs, an interrupted
  compressed T/Z stack, a four-channel mosaic, real `R1 (4)` and both real
  channels of `paneth_ctx555_5` at Z=10. Tile graph separation was exercised.
- Both channels of the known damaged `paneth_ctx555_7` were explicitly checked
  for rejection; these are recorded separately from successful decodes.
- The executable's 100 PE binaries are x64. The DLL audit found no missing
  dependencies or missing bundled import symbols, and no foreign ICU library.
- The copied executable launched from the requested delivery folder under a
  standard, non-administrator token. Python/Qt/source overrides were removed,
  PATH contained only Windows directories, and dependencies resolved inside
  the delivered bundle. Verification logs used a designated writable directory.
- A normal launch with no verification arguments created a visible
  **Leica Interrogator 3.1.0** window and closed normally with exit code zero.
- Every delivered payload matches its manifest checksum; native library hashes
  match the packaged provenance.

The existing source scientific audits and complete partial-stack export checks
remain applicable. The release check was extended for mosaics, native physical
time grids, recorded-plane coverage and explicitly named unreadable cases.
No source/example paths are runtime dependencies.

### Provenance and evidence

The manifest records the actual source file hashes, packaging-spec hash,
dependency versions and modified Git source identity. The build used a restricted
Windows PATH during dependency collection, as established for 3.0.0.

Evidence is retained under `validation/release-310/`: functional XML/log,
quality and packaging logs, frozen decoding/export reports and screenshots,
delivered dependency and checksum audits, and normal-startup results.

This is an unsigned x64 Windows release with the same runtime compatibility
baseline as 3.0.0. Independent testing of 3.1.0 on another PC or a clean Windows
VM has not been performed. The supplied measurements and previous application
releases were not modified.

## 3.0.0 (Windows release)

Built and delivered on 14 October 2026 from the maintained source tree.

The portable release is at
`Leica_Interrogator_App_3.0.0`.
Start `Leica_Interrogator_App_3.0.0.exe`; keep `_internal` alongside it.
README, upstream license notices and a checksum manifest are included.
The release contains 257 checksummed files, approximately 156 MiB.

The application, Windows file/product properties and PTU export version are
3.0.0. Python 3.14.6, NumPy 2.5.3, Pillow 12.3.0, PySide6/Qt 6.11.1, both
maintained native libraries and required Microsoft C/C++ runtimes are bundled.
Native decoder version 3.2.0/API 4 and filter version 1.1.0/API 1 are separate
from the application version. Git provenance explicitly records modified source;
the manifest also hashes the actual maintained source files used for packaging.

### Verification

- All 92 functional tests passed; Ruff, Pylint and Pyrefly passed.
- The actual frozen executable decoded 16 detector datasets: both No 2 images,
  the HCC acquisitions including both mixed excitations and first timelapse planes,
  and four pairs in a mixed sequence/T/Z fixture. All indexed thumbnails were
  present, including Series013.
- All four supplied mixed-excitation LAS X PTUs match the frozen application's
  photon counts and every displayed arrival-histogram bin.
- Bundled PTU and ICS round trips passed for all four synthetic recorded pairs.
  The packaged PTUs identify version 3.0.0.
- Production GUI workers compared all four fixture pairs at t002_z002, giving
  32, 16, 4 and 8 photons. Aligned excitation/emission controls were retained.
- Default GUI launch created the expected 3.0.0 window and accepted normal close.
- The copied executable launched successfully from the requested final folder.
  Python/source/library overrides were removed, PATH contained only Windows,
  and dependency/native-library paths resolved within the delivered bundle.
- Every delivered file matches its manifest checksum. The final DLL audit found
  no unresolved dependencies or missing symbols among bundled libraries.

The initial build collected an incompatible Poppler ICU library from the ambient
PATH. The Windows build environment now restricts PATH during PyInstaller
collection, so Qt resolves the Windows ICU dependency correctly. The final release
contains neither that foreign ICU library nor the temporary startup tracing hook.

Evidence is retained under `validation/release-300-*`, including packaged
startup/screenshots, decoding results, four PTU comparisons, DLL auditing,
functional tests and quality logs. The earlier full scientific reference and
timelapse validations remain in the source validation directory. Packaging
verification does not claim independent certification on another Windows machine.

### Portability verification

Verified on 14 October 2026, following a colleague's Windows access error.

The application is self-contained within its supported target. It cannot be
certified for every Windows PC, Windows version, CPU or organisational policy.

#### Supported target and observed requirements

- All 100 EXE/DLL/PYD binaries are AMD64, requiring an x64 execution environment.
- Qt 6.11 targets Windows 10 version 1809 or later, and Windows 11. Python 3.14
  also requires Windows 10 or later.
- The exact NumPy 2.5.3 binary reports CPU baseline `X86_V2`. This includes SSE,
  SSE2, SSE3, SSSE3, SSE4.1, SSE4.2, POPCNT, CX16 and LAHF. Older processors and
  VMs masking those features are unsupported. AVX/AVX2 are not baseline requirements.
- Python, PySide6/Qt, NumPy, Pillow, native decoder/filter DLLs and C/C++ runtimes
  are bundled. Static import inspection found no external Visual C++ runtime DLLs.
  Remaining external DLL imports are Windows components, including Windows ICU.
- The complete application folder must be copied, and input/export/log locations
  must be accessible to the user's account. Available RAM limits data size.
- The executable is unsigned. Local execution policy may require IT approval.

Sources: [Qt 6.11](https://doc.qt.io/qt-6.11/supported-platforms.html),
[Python 3.14](https://docs.python.org/3.14/using/windows.html#supported-windows-versions),
[NumPy CPU options](https://numpy.org/doc/2.4/reference/simd/build-options.html).

#### Standard-user execution

The delivered executable's embedded manifest requests
`requestedExecutionLevel level="asInvoker" uiAccess="false"`.
It does not request elevation. The delivered executable passed its frozen-runtime
startup check with an explicitly verified non-administrator, medium-integrity token,
Windows-only PATH and source/library environment overrides removed.
Evidence: `validation/release-300-standard-user-check/` and
`validation/release-300-portability-summary.json`.

The user reported that a colleague's normal launch produced Windows' generic
device/path/file access error, and running as administrator resolved it. This
establishes user-reported startup on a second PC under an elevated token. It is
consistent with a permissions or application-control difference between tokens;
the colleague's exact ACLs, policies, Windows version and data-decoding behavior
have not been inspected. Elevation success does not identify one exact cause.

For normal launch on that PC, extract/copy the complete folder into an accessible
user-owned location and check Read and execute permissions. If access is still
denied, IT should inspect the relevant policy/event logs. Changing the application's
manifest to require administrator rights would not resolve the underlying access
policy and is unnecessary for its operation.
[Microsoft manifest documentation](https://learn.microsoft.com/en-us/windows/win32/sbscs/application-manifests).

#### Verification limits

No existing Windows Sandbox, Hyper-V service or supported third-party VM executable
was discovered on the build computer. No virtualisation feature was installed or
enabled. No clean Windows VM or independent Windows 10 execution test was performed.
Windows on ARM, S mode and Windows Server are not certified by this release.

Executable SHA-256:
`f16e8e4eb380d10e7a6cd6338a3d7511b08c1be3699f6afdd941a6ed0c0ef3bf`.
This verification updates the requirements documentation; the executable is unchanged.
