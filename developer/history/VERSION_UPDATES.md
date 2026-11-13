# Leica Image Files Translated into Open File Formats (LIFTOFF) version history

**Investigated 8 September 2026; corpus-wide stress test and fixes completed
10 September 2026.** The work covers slow preview decoding,
cancellation-related crashes, LMSRAW parsing and spatial orientation, ICS export
metadata, and distribution integrity. The latest real corpus consists of four
LIF files (13.38 GB total) containing 26 usable FLIM datasets.

## Findings and confidence

- **Confirmed performance bottleneck and improvement:** LMSRAW originally ran
  with one worker regardless of the selected thread count and repeatedly merged
  dense, mostly empty histograms. Series005 fell from about **90 to 17 seconds
  over the network**, and from **90 to 1.3 seconds on an extracted local block**,
  at 16 threads. Storage and caching affect these individual measurements.
- **Confirmed unsafe worker lifecycle; likely explanation for crashes:** the GUI
  could release a worker after its completion signal but before its thread had
  actually stopped. The fixed lifecycle publishes results after `finished` and
  `wait()`, defers close until workers retire, and prevents preview/export
  overlap. The defect was reproduced and is consistent with recorded Qt
  crashes, although no historical crash dump exists to prove attribution.
- **Confirmed LMSRAW marker bug:** all 15 raw datasets in the expanded corpus
  alternate low-nibble 4 and 8 pixel controls. Recognising only variant 4
  collapsed most photons from alternate rows onto X=0. Python, native DLL and
  PTU paths now accept both marker variants.
- **Confirmed spatial-orientation bug:** all 26 datasets require a 90-degree
  clockwise mapping to match linked Leica intensity. The correction is guarded,
  not unconditional: the winning same-shape transform must reach at least 0.95
  correlation, reduce absolute error by at least 90%, strictly improve the
  match, and decisively beat all alternatives before it is marked confirmed.
  Symmetric, missing, malformed or truncated references remain inferred.
- **Confirmed ICS metadata defects:** the decay axis was labelled `z-position`
  in metres with placeholder scales, while history described time in seconds.
  The fixed exporter writes `t` / `micro-time`, calibrated nanosecond spacing,
  consistent spatial scales, and explicit spatial transform/confidence evidence
  in each sidecar. Alignment evidence survives rebinning.
- **Confirmed GUI usability defects:** ROI hover previously reverted to a
  single-pixel curve, only one ROI could exist, sequential Open replaced the
  current file, and the block list lost its source filename. Multiple ROIs now
  persist until **Clear ROI**; hover shows the sole containing ROI or the pixel
  outside all ROIs. In an overlapping area, the curve is cleared and the user
  is asked to move to one unique ROI, so neither ROI has precedence. LIF imports
  append and deduplicate paths, preserve the current selection/cube, and group
  blocks beneath filename headings. The ICS and PTU selectors now repeat those
  bold, checkable filename groups, including partial-selection state. An optional
  per-LIF mode creates a sibling stem-named export folder for each selected
  source, while a folder failure for one source does not stop the others.
- **Validation:** 35/35 functional checks and 10/10 GUI interaction checks pass. All 26
  real datasets decoded without failures, and 78 full decodes at 1, 16 and 64
  threads produced identical per-dataset hashes, totals and overflow counts.
  The post-fix validation recorded 35/35 functional and 10/10 GUI checks passing.

## Image and excitation timebases

The supplied `Series001.ics` image and `451nm-HyD_X1_458-504nm_PROMPT.ics` excitation both contain **128 bins**, but their header time spans differ:

| File | Total time span (ns) | Time per bin (ps) |
|---|---:|---:|
| Excitation prompt | 12.4121 | 96.969531 |
| Series001 image | 12.817226 | 100.134581 |

Widths above are calculated from each header's time span divided by 128. The image's bins are approximately **3.26% wider**. This is separate from the incorrect axis labels and is unaffected by numbering bins 0–127 or 1–128. It could explain the reported timebase warning; the downstream software's exact comparison and the acquisition origin of the different spans remain unverified.

The metadata correction preserves the recorded time span and photon data; it
does not resample the decay axis or make its timebase match the prompt.
Regression checks confirm agreement between parameters, history, and sidecars
at every supported bin count, with preserved counts and the now-verified spatial
mapping. Interactive acceptance of the corrected header in TRI2 remains
untested.

## Output integrity and data-specific issues

The four-file corpus indexed identically in three successive scans: 26/26 FLIM
datasets were usable, with no catalog issues. Independent Python oracles exactly
matched native output for representative compressed and LMSRAW datasets. Four
simultaneous decodes matched their serial hashes, six cancellation cases passed,
and real compressed/raw ICS files round-tripped exactly. Twenty real GUI
cancel/close cycles retired cleanly, with maximum observed completion latency of
0.0269 seconds.

All 26 datasets decisively selected and confirmed `rotate_90_clockwise`. Minimum
correlation with linked Leica intensity after alignment was 0.999998598990184.
Ten of 11 compressed datasets then matched linked intensity pixel-for-pixel.

Two small scientific count discrepancies remain visible and deliberately
unnormalised:

| Scope | Event-stream difference from linked intensity | Interpretation |
|---|---:|---|
| 15 LMSRAW datasets combined | +182,749 (+0.01442%) | Individual differences +9,616 to +13,920; aligned residuals are non-negative |
| `WT_NADPH.lif / MemBlock_824` | -503 across 525 pixels | Only non-exact compressed dataset; correlation 0.999999986 |

No event was discarded or invented to force equality. A matching independent
Leica export is still needed to distinguish accepted-event filtering from a
remaining token-grammar difference. The GUI and ICS sidecars explicitly report
`eventStreamMinusIntensity`. The treatment of arrivals beyond the calculated
laser period—placing them in the final histogram bin—also remains preserved
rather than independently certified.

## Fixes delivered

- GUI results are published only after workers finish. Closing the window requests cancellation and waits for safe worker retirement; preview decoding is prevented from overlapping with export.
- Added a native parallel LMSRAW decoder with bounded batch reads, synchronized histogram updates, input validation, and overflow checks. The thread setting now applies to this format; a bounded Python fallback remains available.
- Added marker-4/marker-8 LMSRAW pixel handling to Python, native DLL and PTU
  export, with route/repetition/thread regression coverage.
- Added linked-intensity spatial alignment using all eight dihedral mappings and
  strict shape, correlation, improvement and uniqueness thresholds. Selected
  plane reads are direct; integrated movie references are streamed one plane at
  a time to remain memory-bounded.
- Added safeguards against integer overflow or truncation during Python accumulation, rebinning, and ICS writing; preserved intensity-comparison metadata through rebinning.
- Corrected ICS cancellation reporting and added persistent Python/Qt diagnostic logs, updated build/launch scripts, and regression coverage.
- Corrected ICS decay-axis names, units, and bin spacing, plus spatial parameter scales, so the main header agrees with history and sidecar calibration.
- Added sidecar transform, correlation, absolute residual and confirmation
  fields; ambiguous axis order is labelled inferred/defaulted.
- Corrected the packaged validator's obsolete test import and added marker-8 PTU,
  guarded alignment, ambiguity and truncated-reference tests. The v3.1.0 native
  DLL was rebuilt.
- Launch and installation validation now prefer the fixed app's own `.venv`,
  reject stale environments, and provide a specific repair instruction.
- Added persistent multi-ROI hover resolution and all-ROI clearing. A unique ROI
  shows its full decay, overlap hover clears the curve and displays an ambiguity
  message without giving any ROI precedence, and non-ROI hover shows the pixel.
  Sequential LIF scans now append without clearing existing data, survive
  failed/cancelled additions, suppress duplicate paths, and rebuild the list as
  filename groups while retaining the selected decoded block.

The fixed application was originally isolated in **Fixing Leica Interrogator**.
The original installation and source LIF files were not replaced. This V2
package retains the required runtime subset while deliberately excluding the
investigation logs, test corpus, test suite, benchmarks, and supporting reports.

The earlier shared virtual environment points to a Python installation that no
longer exists and is intentionally not carried into V2. Install a current
64-bit Python and run `install_packages.bat` once to create V2's private `.venv`
before launching. Re-export images to obtain corrected metadata; existing ICS
files and the prompt were not modified. The separate image/prompt timebase
difference still needs resolution if analysis requires matching spacing.
