# Leica Image Files Translated into Open File Formats (LIFTOFF) Windows installation history

This guide describes the earlier Leica Interrogator Windows package. It
indexes Leica LIF files without decoding every block, previews one selected FLIM
block at a time, displays pixel and ROI decays, and exports selected blocks as
TRI2-compatible ICS decay stacks or PicoQuant Generic T3 PTU event files.

The ZIP already includes a tested Windows x64 DLL. Follow the DLL build section
only when rebuilding from source or moving to a different MSVC toolset.

## 1. Extract The ZIP

Extract the complete ZIP to a normal writable folder, for example:

```text
C:\Users\YourName\Documents\Leica Interrogator
```

Do not run the application from inside the ZIP viewer.

## 2. Install 64-Bit Python

Install 64-bit Python 3.11 or newer from:

<https://www.python.org/downloads/windows/>

During installation, enable **Add Python to PATH** or install the Python launcher.
Restart any open Command Prompt or PowerShell windows after installation.

Verify Python by opening Command Prompt and running:

```bat
py -3 --version
```

## 3. Install The Python Packages

Double-click:

```text
install_packages.bat
```

The earlier installer created a private `.venv` environment inside the
extracted folder and installed pinned versions of these packages.

- NumPy
- Pillow
- PySide6

The application does not need a browser, web server, Java, Bio-Formats, PyTorch,
CUDA, or MATLAB.

For the maintained installation steps and dependency pins, see the
[project README](../../README.md#start-on-windows).

The included API v3 DLL and Python package must be kept together. API v3 adds
count-preserving line/frame repetition mapping; an older API v2 DLL is rejected
and the application falls back to Python rather than exporting partial planes.

## 4. Run With The Supplied DLL

Double-click:

```text
launch_leica_interrogator.bat
```

The launcher uses this folder's private `.venv`. The status bar should say
`Decoder: native` after selecting a compressed FLIM block. LMSRAW previews use
the included native bounded streaming decoder and report `lmsraw-native`.

## 5. Install MSVC Build Tools

This section is required only to rebuild `LeicaFlimDecoder.dll`.

Download the current stable **Build Tools for Visual Studio** from:

<https://visualstudio.microsoft.com/downloads/>

In Visual Studio Installer select the **Desktop development with C++** workload.
Confirm these components are selected:

1. Current stable MSVC x64/x86 C++ build tools.
2. Windows 10 or Windows 11 SDK.
3. C++ core desktop features.

The Visual Studio IDE, ATL, MFC, Clang, CMake, and Preview components are not
required. Close and reopen Command Prompt after installation.

## 6. Build The Native DLL

Double-click:

```text
build_dll.bat
```

The wrapper uses a temporary PowerShell execution-policy bypass, locates MSVC
with `vswhere.exe`, initializes the x64 developer environment, and compiles the
C++17 source with optimization enabled.

Successful output is written to:

```text
leica_flim_converter\native\LeicaFlimDecoder.dll
```

The command-line equivalent is:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_native_decoder.ps1
```

This does not change the machine-wide PowerShell execution policy.

## 7. Validate The Installation

Double-click:

```text
validate_installation.bat
```

The packaged validation checks the Python architecture and version, imports all
three Python dependencies and the GUI, confirms required local modules are
present, and loads the supplied API v3 native decoder with LMSRAW support. The
full development and corpus test suites were completed before packaging and are
summarized in `Version Updates.md`; they are intentionally omitted from V2.

The successful result begins with:

```text
PASS: Leica Interrogator V2 runtime and native decoder are ready
```

## 8. Use Leica Interrogator

1. Start `launch_leica_interrogator.bat`.
2. Click **Open LIF files** and select one or more files.
3. Select a FLIM detector dataset to decode and preview it.
4. Move over a pixel or drag an ROI to inspect its decay.
5. Click **Export ICS**.
6. Check individual detector/T/Z rows, or check a bold LIF filename heading to
   select every exportable output from that file.
7. Choose a common output folder, or enable **Per-LIF folders** to create a
   stem-named folder beside each source LIF. Then choose bins, compression,
   dimension mode, and collision handling.
8. Click **Export**.

For event output, click **Export PTU**, select detector/T/Z rows individually or
by bold LIF filename heading, choose a common folder or **Per-LIF folders**, and
click **Export PTU**. The application writes one event file per selected plane
plus a JSON sidecar. Photon microtimes and positions are preserved; the macrotime
raster is necessarily synthetic and is labelled as such.

The default **Split detector/T/Z planes** mode writes one `.ics` file and one
`.ics.json` sidecar for each selected detector/T/Z plane. Names preserve Leica
channel and detector identity and use one-based suffixes such as `_t001`, `_z001`,
or `_t001_z001`. **Integrate T/Z per detector** is an explicit alternative that
writes a separate summed file for each selected detector with an
`_all-frames-summed`, `_all-z-summed`, or `_all-planes-summed` suffix. Existing
files are never silently overwritten.

LMSRAW blocks may expose up to four detector routes as separate selectable rows.
The application preserves Leica's detector name and identifier in filenames and
JSON sidecars and never combines detector channels during T/Z integration.

## Troubleshooting

### PowerShell says scripts are disabled

Run `build_dll.bat`; it supplies a process-only execution-policy bypass.

### MSVC C++ Build Tools were not found

Open Visual Studio Installer, choose **Modify**, and add **Desktop development
with C++**. Then close and reopen the terminal.

### The GUI reports Python fallback

Confirm this file exists:

```text
leica_flim_converter\native\LeicaFlimDecoder.dll
```

Run `build_dll.bat`, then `validate_installation.bat`. On another Windows PC,
install the current Microsoft Visual C++ x64 Redistributable if Windows reports
a missing C++ runtime.

### The application does not start

Run `install_packages.bat` again. If needed, open Command Prompt in the extracted
folder and run:

```bat
.venv\Scripts\python.exe -m leica_flim_converter
```

The visible error message will identify the missing package or startup problem.
