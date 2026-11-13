# Leica Image Files Translated into Open File Formats (LIFTOFF) 3.2.2

LIFTOFF opens Leica LIF photon data for inspection and exports calibrated
ICS histograms and PTU event files. The maintained source builds on the
original 2.0 source and the validated 2.4 reference behavior.

Normal startup uses ordinary Python modules and two maintained native libraries.
It does not require historical executables, PyInstaller archives, startup patch
installers, project chats, or example data. The supplied Windows x86-64 libraries
were rebuilt from the included C++17 source. Standalone Windows builds from
this tree use the name `LIFTOFF_App_<version>` and bundle their runtime
dependencies in `_internal`.

## Start on Windows

With the development environment installed in `.venv`, double-click
`launch_LIFTOFF.bat`, or run:

```powershell
.venv\Scripts\python.exe -m leica_flim_converter
```

On a fresh Windows machine, install 64-bit CPython 3.14.10 or later in 3.14, run
`install_packages.bat`, then launch. That helper installs the pinned development
environment as well as the runtime. For a runtime-only installation:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe validate_installation.py
```

The included DLLs require the Microsoft Visual C++ x64 runtime. A C++ compiler
is only required for rebuilding them. The accepted dataset workflows and controls
are described in [the user guide](USER_GUIDE.md).

## Runtime dependencies

The installer uses the pinned versions in [pyproject.toml](pyproject.toml).

```text
numpy==2.5.3
Pillow==13.0.0
PySide6==6.11.1
defusedxml==0.7.1
```

## Maintain and validate

```powershell
.venv\Scripts\python.exe tools/quality.py
.venv\Scripts\python.exe -m pytest -m "not real_data"
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m tools.build --native-only --generator "Visual Studio 16 2019"
```

The single quality command checks every maintained Python file with pinned Ruff,
Pylint, and Pyrefly. The full test suite also uses optional external LIF/LAS X
data. Set `LEICA_EXAMPLE_DATA_DIR` to a directory containing those files and their
companion PTUs. The supplied local release folders are the test discovery fallback;
they are not application dependencies. Missing real-data inputs are explicitly
reported as skipped tests. A release acceptance run must have those inputs present.

The source uses version 3.2.2. Its packaged provenance identifies the Git
source revision, reference executable, and rebuilt native libraries. Commit future
code changes, rebuild from this tree, run the regressions, and refresh provenance
using `python -m tools.provenance` before packaging. An uncommitted source tree
is explicitly recorded as modified.

## Documentation

- [User guide](USER_GUIDE.md)
- [Release notes](RELEASE_NOTES.md)
- [Developer guides](developer/DEVELOPER_README.md) for builds, Python code quality,
  and scientific and export contracts
- [Project history](developer/history/HISTORY_README.md) for reconstruction, provenance,
  and prior investigations

## Contributing

Open pull requests against `main`. Include the reason for the change and the
checks you ran. For changes to decoding or export, follow the
[scientific and export contracts](developer/SCIENTIFIC_SEMANTICS.md) and report
the relevant regression results.

## Licence and citation

Copyright (C) 2026 King's College London

This program is free software: you can redistribute it
and/or modify it under the terms of the GNU General
Public License as published by the Free Software
Foundation, version 3 of the License.

This program is distributed WITHOUT ANY WARRANTY.
See the [GNU General Public License](LICENSE) for details.

Use [CITATION.cff](CITATION.cff) to cite LIFTOFF. See [AUTHORS.md](AUTHORS.md)
for the author list.

Build support is defined for all four targets. Windows source execution and native
rebuilding are validated. Linux/macOS compilation, runtime certification, signing,
and notarization remain explicitly deferred. The unresolved Series006 acquisition
remains a visible failure rather than producing an unverified result.
