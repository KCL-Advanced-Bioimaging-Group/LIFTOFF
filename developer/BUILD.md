# Building Leica Image Files Translated into Open File Formats (LIFTOFF)

The common build definition is `tools/build.py`; native targets are in the root
`CMakeLists.txt`. Both libraries use C++17 and `Threads::Threads`. The supplemental
filter uses portable `std::thread` workers and preserves its C ABI, selection
algorithm, partitioning, and synchronous fallback if a worker cannot be created.

Use 64-bit CPython 3.14 and a fresh environment on each target host:

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python tools/quality.py
```

Dependencies and development tools are pinned in `pyproject.toml`. The validated
Windows runtime is CPython 3.14.10, NumPy 2.5.3, Pillow 13.0.0, PySide6 6.11.1,
and defusedxml 0.7.1.
Use wheels matching the host architecture. Package discovery uses the installed
source project; no historical release directory needs to be on `PYTHONPATH`.

## Targets and prerequisites

| Host | Compiler and runtime prerequisites | Native filenames | Certification |
| --- | --- | --- | --- |
| Windows x86-64 | Visual Studio C++ Build Tools and Windows SDK; Microsoft VC++ x64 runtime | `LeicaFlimDecoder.dll`, `LeicaLmsrawFilter.dll` | Both libraries rebuilt; source/clean-environment execution validated. |
| Linux x86-64 | GCC or Clang with C++17, Ninja; matching CPython/PySide6 wheels; Qt platform-plugin system libraries | `libLeicaFlimDecoder.so`, `libLeicaLmsrawFilter.so` | Build configuration tested; compilation/runtime deferred. |
| macOS arm64 | Xcode command-line tools/Clang, Ninja; arm64 CPython and all dependency wheels | `libLeicaFlimDecoder.dylib`, `libLeicaLmsrawFilter.dylib` | Build configuration tested; compilation/runtime/signing deferred. |
| macOS x86-64 | Xcode command-line tools/Clang, Ninja; x86-64 CPython and all dependency wheels | Same dylib names | Build configuration tested; compilation/runtime/signing deferred. |

Choose an OS version supported by the pinned CPython/PySide6 wheels. For Linux
deployments, test Qt's xcb/Wayland plugins and required libraries on the minimum
supported distribution, and build there to avoid a newer glibc dependency. See
[Qt Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html) and
[Qt macOS guidance](https://doc.qt.io/qt-6/macos.html); those live pages may describe
a newer Qt version than the pinned runtime, so confirm compatibility for 6.11.1.

The tested Windows native command is:

```powershell
python -m tools.build --native-only --generator "Visual Studio 16 2019"
```

Visual Studio 2022 can use its corresponding CMake generator. Linux and macOS:

```sh
python -m tools.build --native-only --generator Ninja
python validate_installation.py
python -m leica_flim_converter
```

CMake builds under `build/native` and installs both libraries into
`leica_flim_converter/native`. The native header declares the decoder API and portable export visibility.
The ctypes bindings use the same C ABI on all hosts. Resource discovery
selects the platform filename and the source or frozen bundle location. Logs
use LOCALAPPDATA on Windows, Library/Application Support on macOS, and
XDG_DATA_HOME (or `.local/share`) on Linux. Optional explicit library/log
overrides are documented in `platform_paths.py`.

## PyInstaller releases

Commit reviewed code and run tests first. Omit `--native-only` to rebuild both
native libraries, refresh Git/native provenance, and create a release:

```sh
python -m tools.build --generator Ninja
```

On Windows use the Visual Studio generator shown above. Build each release on
its corresponding OS: [PyInstaller does not cross-compile between operating
systems](https://pyinstaller.org/en/stable/usage.html#supporting-multiple-platforms).
Use separate native macOS arm64 and x86-64 environments. The tool rejects
unsupported host/architecture combinations and passes the matching macOS target
architecture to PyInstaller.

The maintained Python configuration declares a windowed onedir application,
explicitly includes exactly the two host-native libraries and provenance JSON,
and uses standard PyInstaller hooks for PySide6/Qt, NumPy, and Pillow. The
Windows packaging environment restricts PATH to Windows and the build's Python
runtime directories. This prevents unrelated tools' DLLs, including incompatible
ICU libraries with the same filename as Windows' ICU library, from entering Qt's
dependency collection. Compiler and Git steps retain the normal build environment.
Generated `.spec` files are under `build/specs`; releases are under `dist/<target>`.
The release name is `LIFTOFF_App_<application version>`. Windows
executable properties are supplied by `tools/windows_version.txt`; update that
resource together with `version.py` and `pyproject.toml` for a new version.
Keep the generated executable and `_internal` directory together. Copy
[the release README](../tools/TOOLS_README.md) as `README.md` and the
[user guide](../USER_GUIDE.md) as `USER_GUIDE.md` beside the executable. Include dependency license notices
and capture a file-checksum manifest before distributing the whole directory.
The entry point is the normal `launch_LIFTOFF.py`. There are no custom
historical startup-patch hooks. Check Qt plugin collection and native-library
loading in the actual generated bundle on a clean target machine before release.
An opt-in diagnostic command exercises the actual executable without an external
Python installation:

```powershell
.\LIFTOFF_App_3.2.2.exe --verify-release C:\path\to\evidence
```

Add repeated `--verify-lif C:\path\to\sample.lif` arguments to check native
decoding of the first plane of each indexed detector dataset. Small fixtures also
exercise PTU/ICS round trips and recorded-pair comparison at the final T/Z plane.
Run from another working directory with source paths and library overrides removed
from the environment. This complements, rather than replaces, scientific reference
tests and independent testing on other Windows machines.

## macOS signing and notarization (future release)

Obtain the appropriate Developer ID Application identity and signing credentials.
On the matching macOS host:

```sh
python -m tools.build --generator Ninja \
  --codesign-identity "Developer ID Application: Your Name (TEAMID)"
```

If required, provide a reviewed entitlements plist using `--entitlements path`.
PyInstaller applies the signing identity to the collected native code and app.
See its [macOS signing notes](https://pyinstaller.org/en/stable/feature-notes.html).
Do not sign only the top-level executable and leave nested libraries unsigned.

After running the scientific and GUI checks against the signed app, create a
ZIP with `ditto -c -k --keepParent <app> <zip>`. Submit with
`xcrun notarytool submit <zip> --keychain-profile <profile> --wait`, inspect the
result, and on acceptance run `xcrun stapler staple <app>`. Verify with
`codesign --verify --deep --strict <app>` and
`spctl --assess --type execute --verbose <app>`, then regenerate the distributable
ZIP after stapling. Follow [Apple's notarization documentation](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
for credential setup and current requirements. Signing credentials never belong
in this source tree. These steps are documented only; no signing or notarization
has been performed in this Windows restoration.


The timing consistency update uses LeicaFlimDecoder **API 6 / 3.3.1** and
LeicaLmsrawFilter **API 2 / 1.2.0**. Both accept an explicit native-arrival to
output-bin lookup and count excluded arrivals. Rebuild/install both source
libraries together with `python -m tools.build --native-only`. This command
does not build standalone application executables. Restart a running source
application before testing a new library pair.
