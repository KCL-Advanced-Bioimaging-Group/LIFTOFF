# Timing consistency implementation

Implemented in the source application only. The original LIFs and standalone
application executables have not been changed. This supersedes the behavior
described in the earlier `TIMEBASE_AUDIT_2026-10-16.md`.

## Shared recorded timing

`AcquisitionTiming` retains arrival clock, laser frequency, pixel dwell, line
period and frame period, each with value, units, source scope and evidence
quality. Laser repetition period is calculated from the recorded frequency.
Detector settings take precedence over sequence settings, then acquisition
settings. Explicit invalid local calibration is unavailable; it cannot borrow a
different source's setting. Legacy single-sequence compressed acquisitions also
receive this metadata. Original timestamp-list XML is retained from the selected
acquisition, without assigning an unvalidated epoch or frame/tile association.

The catalogue audit covers all nine supplied files and all 121 entries. All
retain recorded dwell and timestamp metadata. None has sufficiently complete,
consistent pixel/line/frame information to reconstruct its complete raster.
Their automatic PTU timing quality therefore remains **Synthetic**, with a
specific reason and the recorded source fields preserved in every sidecar.

## Photon arrival histograms and ICS

Physical arrival time is the native integer arrival multiplied by the recorded
clock. One `TimeGrid` supplies both histogram boundaries and ICS calibration.
The fast C++ and Python paths use the same bin lookup and are compared at every
pixel and bin in tests.

- Previews and **Native timing** exports preserve the recorded increment.
  Complete bins spanning one laser period are allocated with
  `ceil(laser_period / clock)`. The final bin keeps its entire native width.
  Supplied examples use 133 bins at 78.02 MHz and 129 at 80 MHz.
- Explicit numeric choices, including 128 and 256, rebin one unrounded laser
  period. Assignment uses physical half-open bin boundaries. Finer output bins
  do not create new timing information.
- Selected arrivals outside the chosen window are excluded and counted, with
  no last-bin clipping. Sidecars reconcile selected, exported and excluded
  photons. The completion message reports exclusions and the preview exposes
  its excluded count. PTU keeps the original native arrivals, including these
  events, so independent cross-format checks can reproduce the ICS counts.
- Both ICS parameter scale and history extent now use **seconds**, with enough
  digits to preserve the calibration. Readers must respect the associated
  units. Optical labels and graph labels retain their concise display precision.
- Cache reuse requires the same recorded pair, plane, selection, clock, window
  and exactly aligned grouping boundaries. Historical cubes without a physical
  grid cannot supply calibrated exports.

The compatibility default remains **128 bins**. Native timing is available in
the dialog and as `IcsExportOptions(bins=None)`. Independent ICS reading checks
arbitrary native bin counts, payload orientation and calibration; adoption as a
downstream default is deferred until those counts are checked in the user's
analysis software. The historical low-level decoder contract remains available
for frozen regression evidence; the GUI and export paths request physical grids.

## PTU scan timelines

PTU native microtimes are preserved. The recorded clock supplies microtime
resolution and the unrounded laser period supplies global resolution; no
80 MHz or fabricated-clock fallback remains in calibrated exports.

**Recorded scan timing when complete** is the automatic mode. Reconstruction
requires consistent recorded pixel and line periods, plus a recorded frame
period when repetitions require it. Missing flyback information, accumulated
line repeats, partial scans or inadequate sync resolution prevent reconstruction.
Automatic mode then uses a labelled synthetic raster. **Require reconstructed
timing** fails explicitly instead. **Synthetic raster** retains the previous
three-sync-ticks-per-pixel convention and configurable synthetic spacing.

Reconstruction assigns photons to nominal pixel centres. Absolute pixel and
marker positions are rounded to sync ticks, avoiding cumulative rounding drift.
It cannot restore original individual photon hardware times. Each exported
plane/tile begins at zero; no elapsed-time relationship between files is invented.
Quality is visible in the export table, the PTU header comment/custom quality
tag, and the sidecar. Recorded scan fields, repetitions and tile identities are
retained even when output is synthetic.

## Validation and native libraries

The source libraries are LeicaFlimDecoder **API 6 / 3.3.0** and
LeicaLmsrawFilter **API 2 / 1.2.0**. Only the source libraries were rebuilt.
Descriptor-range selection avoids decoding unrelated compressed rows during
selected-plane PTU export.

Validation includes different clocks and laser frequencies, missing/invalid
calibration, both compressed and LMSRAW streams, detector/sequence isolation,
frame repetitions, T/Z planes, mosaics, all three photon selections, and
native/Python parity. The supplied-file checks independently re-histogram PTU
arrivals using ICS header boundaries across all nine LIFs, both sources in
`paneth_ctx555_1`, all four Navigator tiles, and one complete full-resolution tile.
That complete tile's Single-event export preserves 8,613,357 native PTU photons;
ICS contains 8,613,288, with the other 69 explicitly counted outside its window.

Evidence is retained in `validation/timing-model-catalogue.json`,
`timing-functional.xml`, `timing-real.xml`, `timing-integration.xml`,
`timing-reference.xml`, `timing-native-build.log`, and `timing-quality.log`.
Historical reference fixtures have not been rewritten. Native PTU record payload
checks remain in place; calibrated ICS expectations now derive independently
from the unmodified PTU arrivals instead of asserting the old clipping policy.

Completed checks: 207 functional tests; 10 supplied-file timing checks; 10
real-data integration/GUI checks; and the complete X03 Single-event reference
PTU/ICS comparison. All passed. The focused timing tests also independently
verify reconstructed line and frame marker positions. Formatting, linting,
static analysis and typing checks pass for all maintained Python files.
