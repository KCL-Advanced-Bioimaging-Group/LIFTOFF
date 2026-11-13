# Leica Interrogator 2.4 source parity and acceptance

The maintained source reproduces the accepted 2.4 scientific results and desktop
presentation. It uses normal Python declarations and rebuilt native libraries,
with no runtime dependence on historical patch modules or executables. Application
version remains 2.4.0; source/native identity is recorded in the packaged Git
provenance manifest. This report describes the Windows validation, including its
practical limits. Actual Linux/macOS builds and runtime certification are deferred.

Implementation commit: `60bdc410b8c3e01445fea6781475d7890793ff7f`. The delivery evidence/manifest commit
follows that revision without changing maintained application code. Packaged
provenance reports unmodified code and hashes both supplied Windows libraries.
Acceptance comprises **683 passing checks**, plus **53 post-rebuild checks**,
with no failures or skipped real-data inputs. The machine-readable record is
`validation/acceptance.json`.

## Feature checklist

| Accepted behavior | Maintained implementation | Validation evidence |
| --- | --- | --- |
| Detector grouping, emission filters, calibration, channel identities and plane ranges | `dataset`, `catalog`, `catalog_metadata`, `catalog_index` | All five catalogues and every metadata field in `test_reference_science`; 37 detector datasets. |
| All / First / Single photons consistently across preview, ICS and PTU | `event_flags`, `photon_selection`, `raw_selection`, native API 4 | Exact native-period arrays across all valid planes at 1/4/16 threads; selectors across Python/native boundaries; full PTU/ICS comparisons. |
| Native-period previews and independent ICS binning | `decay`, `histogram_core`, `native_decoder`, `ics_export` | 129/132 native-bin cases, 128/256 exported bins, selection-aware cache tests and indexed 129-to-128 comparisons. |
| Spatial alignment, uint32 overflow protection and partial indexes | `histogram_core`, `raw_container`, `catalog_metadata` | Full spatial hashes/alignment metadata; promotion/overflow tests; partial-repeat exports; invalid Series006 fails. |
| Native decoder 3.2/API 4 and supplemental filter 1.1/API 1 | C++17 `native/*`, CMake, typed ctypes adapters | Successful Windows rebuild, installed version/API check, scientific parity at representative worker counts. |
| Side-by-side images/graphs, synchronized planes, explicit failures | workspace channels/preview/layout, plot | Full two-channel real-data screenshot parity; T/Z arrow/selector tests; failure preflight. |
| Grouped imports, repeated loading and data removal | workspace source lifecycle | Observable import/deduplication/removal tests and clean-window state. |
| Zoom/pan and stable ROI activation/numbering/persistence | canvas and workspace ROI components | Real Qt clicks/drags, filter/channel transitions, active-delete protection, retained numbering and coordinate tests. |
| Retention prompts, mirrored outlines, inactive deletion | workspace ROIs and canvas | Yes/No retention tests, mirrored-outline evidence, right-click deletion. |
| Orange combined ROI curves; overlap counted once | shared ROI union and graph presentation | Explicit 14-pixel union totals over all time bins and orange color check. |
| Compact export tables, expansion, filenames/counts/sizes, Ready/Failed tooltips | shared export table, ICS/PTU dialogs and helpers | Matching reference dialog screenshots/observable cells; nine-plane expansion; missing-source and Series006 preflight. |
| Vector PTU writing, native microtimes, routes, markers and overflow | `ptu`, `ptu_export`, `export_inspection` | Full accepted record hashes and independent LAS X comparisons in all modes; actual partial-index line/frame counts. |
| ICS axes, integer size, calibration, gzip/plain and JSON sidecars | `ics`, `ics_export`, independent reader | Full golden 128/256 arrays; non-square 16/32-bit round trips; physical units and provenance assertions. |
| Safe cancellation and closing during work | bounded readers/writers, workers, workspace close | Decode/export cancellation cleanup and actual QThread indexing cancel/close lifecycle tests. |
| Maintained entry points, public formats and callbacks | package API, launcher, ordinary GUI wrappers | Installed clean runtime launch from an unrelated working directory; normal event loop and clean exit. |
| Portable discovery/build support and PEP 8 quality | platform paths, build/quality tools, typed models | Four-host configuration tests; Ruff/Pylint/Pyrefly gate; Windows native build and clean startup. |

## Scientific and format evidence

`validation/reference-science-threads.xml` records **590 passing tests**: five
catalogue comparisons plus 195 plane/selection cases repeated at 1, 4 and 16
threads. Those cases include 189 valid combinations and six explicit Series006
failure combinations. Thus 567 successful full-array comparisons and 18 expected
failures agree with the frozen application. The datasets come from all five
available LIF files: PL109, X03, Sample2, HCConly and Autofluorescence. A separate
four-thread scientific run also passed all 200 catalogue/plane tests.

`validation/reference-exports.xml` records **nine passing complete-export cases**:
PL109, X03 and Sample2, each in all three selections. Each case compares the full
PTU record-payload SHA-256, photon count, every occupied microtime bin, routes,
markers, overflow records/wraps and macrotime monotonicity against frozen 2.4.
It independently parses LAS X companions and compares every photon microtime.
The 18 ICS outputs (128 and 256 bins for each case) match full-array hashes,
shape, photon totals, headers and calibration. Synthetic round trips additionally
cover non-square dimensions, both integer widths and both compression modes.

`validation/indexed-exports.xml` records **24 passing cases** covering validated
inferred-line-order and partial-repeat acquisitions in Autofluorescence, including two complete later planes
and six partial detector streams, in every selection. It compares native golden
arrays, independently rebinned ICS counts, PTU microtime totals, routes, actual
markers, monotonicity, header version and indexed-row provenance. These are source
regressions for corrected partial/inferred export paths, rather than a claim that
the historical application successfully exported every such case.

`validation/functional.xml` records **60 passing tests** covering photon-state
edges, malformed sources, codec bounds, integer promotion/overflow, export cleanup/collision/provenance, ROI union,
retention, mirrors, zoom/pan, T/Z navigation, grouped imports/removal, table
expansion, preflight, portability and Qt worker cancellation/close during
indexing and a real large native compressed decode, plus ICS cancellation after writing begins. Test counts
and timings are available directly in these JUnit files.

## Appearance and startup

The retained screenshots compare the isolated frozen reference and maintained
source at the same window size, font initialization, Qt environment and data.
`validation/screenshots/source` and `reference` include the HCConly two-channel
workspace, ICS dialog and PTU dialog, plus observable fields and table-cell JSON.
Both export dialogs are pixel-identical to the reference; the workspace differs
only in the measured decode-time characters. Images were visually reviewed for
layout, colors, channel headers, graph legends, axis calibration, controls
and compact rows. Pixel-comparison details are in
`validation/screenshots/comparison.json`; variable decode timing is not an
appearance requirement.

The clean runtime-only environment is independent of development tools. The
installed source launches through its normal entry point with Python isolated
mode from the unrelated 2.4 release working directory. Both DLLs load from this
source project, the visible window is titled Leica Interrogator 2.4.0, Open LIF
is enabled, and closing exits normally. Evidence is in `validation/clean-startup`.

## Performance

Both implementations ran sequentially on the same Windows machine and Python/
NumPy/Qt environment. For each of five representative files, all selections at
1/4/16 threads were measured after one warm-up with three timed full native-period
previews; output hashing and garbage collection were outside the timed interval.
All 45 cases have identical photon totals and complete array hashes. Raw timings
are in `benchmark-reference.json` and `benchmark-source.json`; paired results
and aggregate ratios are in `benchmark-comparison.json`.

The geometric mean source/reference latency ratio is **0.999** across all cases:
1.029 at one thread, 1.012 at four threads and 0.956 at 16 threads. This indicates
comparable overall performance, with an average improvement at the default
16-thread setting in this sample. Per-case ratios span 0.535 to 1.303; compressed
PL109 one-thread measurements are 15-19% slower. These are measured observations,
not guaranteed speedups: Windows scheduling, thermal/load state and filesystem
caches vary, and lightweight checks overlapped parts of the measurement period.
No change to photon semantics was made to optimize a timing number. Preserve
these results as the baseline for future performance work.

## Quality, portability and retained limits

The final quality log is `validation/quality.log`. The acceptance command covers
every maintained Python file. Required result: Ruff formatting/lint clean,
Pylint 10.00/10 without actionable messages, and Pyrefly zero diagnostics including
warnings. Pins and narrowly justified exceptions are documented in QUALITY.md.
All 59 maintained Python files pass. The successful clean native rebuild log
is `validation/native-build.log`; `validation/postbuild.xml` records 53 passing
boundary/format and representative exact-array tests against the newly rebuilt
libraries, covering all five samples and all three selections.

Windows source/native validation is complete. Build definitions and platform
discovery are checked for Windows x86-64, Linux x86-64, macOS arm64 and macOS
x86-64. No new PyInstaller distribution was requested or produced; packaged
bundle certification and Linux/macOS compilation, signing/notarization/runtime
testing are future release steps.

Series006 remains unresolved and fails explicitly. PTU macrotime remains a
documented synthetic raster clock, while native microtimes are preserved.
Incomplete acquisitions retain only indexed photons, with unverified spatial
alignment disclosed. Historical optional experimental CLI modules absent from
the 2.0 baseline are not newly invented. These limitations are preserved and
described in the scientific/reconstruction guides.

Two restoration reliability corrections are explicit: validated inferred-line
indexes now pass ICS's export guard, and partial PTU exports use actual indexed
rows rather than asserting missing nominal repetitions. Both paths have new
scientific regressions. CreatorSW_Version now consistently reports 2.4.0 and
sidecars include Git reconstruction identity. No accepted complete PTU record
payload or complete histogram result changed.
