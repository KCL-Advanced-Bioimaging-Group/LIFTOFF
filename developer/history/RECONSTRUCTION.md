# Reconstruction and provenance

The original 2.0 source was copied into this independent authoritative project,
then committed as baseline `3fcb503`. The source project has local Git history;
no remote publication was requested. Original 2.0 / 2.2 / 2.3 / 2.4 release
folders and example data were retained unchanged.

Restoration compared original modules with the later embedded application and
startup changes, reports, retained patch implementation, native source evidence,
project transcripts and validation results. Missing intermediate implementation
was materialized as maintained functions/classes. The native decoder 3.2/API 4
was rebuilt and its supplemental filter's Windows threading replaced with
portable C++17 workers. Ordinary modules now own the final behavior directly.

The actual validated 2.4 executable is
`LeicaInterrogator/LeicaInterrogator-v2.4.0.exe`, SHA-256
`9127d8c772c01f7f72c8905d4814f9f466f32faa11780d8b46c199ec1e1d0cab`.
Some historical reports describe an earlier packaging hash; this manifest names
the actual supplied final executable. Original reference file hashes are retained
in [reference_hashes.json](reference_hashes.json).

Investigation tooling extracted the reference archive and loaded its own
application/decoder modules in isolation. It cleared similarly named source
modules before reference loading, so comparisons did not mix restored source and
frozen implementation. An early mixed-loader result was discarded and is not
acceptance evidence. Full golden scientific/export evidence was then captured
from the isolated reference and committed as portable JSON test fixtures.

The maintained regression suite consumes those fixtures directly. It has no
dependency on an executable, archive reader, patch module, or project transcript.
Only the optional real input data remains external. Archive tooling stays in the
separate investigation workspace and is not a startup/build dependency.

`gui.py` preserves established imports and callbacks while delegating to normal
GUI components. Numeric suffixes in some compatibility helper names are retained
to preserve recovered interfaces; they do not indicate runtime installers.
`lif_flim_forensics.py` and `patent_guided_deflate_attack.py` are ordinary parser/
codec modules needed by the source application. Unused historical experiments
whose optional modules were already absent from 2.0 were saved as text in the
[original investigation programs](HISTORY_README.md#original-investigation-programs).
The normal entry points and supported exports are fully maintained and tested.

The reconstruction was delivered as version 2.4.0. The final
[parity and acceptance report](PARITY_REPORT.md) records the features,
scientific comparisons, performance and retained limitations. See the
[build guide](../BUILD.md) for current build and packaging steps.

The packaged manifest `leica_flim_converter/provenance.json`
records the implementation Git revision, dirty-code flag, baseline, reference
hash and native versions/hashes. Runtime reads the packaged manifest and never
requires Git. A final evidence/manifest commit can follow the implementation
commit without changing code; the manifest anchors the implementation revision
and avoids a self-referential Git hash.

Future releases must be built from reviewed committed source. Run quality and
regressions, rebuild host-native libraries, refresh provenance, and package with
the maintained build script. The old executable may remain a comparison artifact,
but it is never an editing surface or future build input.
