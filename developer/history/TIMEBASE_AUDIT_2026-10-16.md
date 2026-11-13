# LIF, ICS and PTU timing audit

Checked on 16 October 2026 against the current source implementation, all nine
example LIF files (121 catalogue entries), existing export headers, and fresh
full-resolution exports of tile row 1, column 1 of **R1 (4)** in
`HCC1954 mS3-mitoPyr-ShadowR.lif`. This audit does not change the application's
timing or export behavior.

## Photon-arrival timebase

Every catalogue entry in the supplied examples records
`ClockPeriod = 9.696969697e-11` seconds: **96.9697 ps**, or **0.0969697 ns**, per
native photon-arrival increment. The application displays this as **96.97
ps/bin** when previewing the native bins. Graph coordinates are bin indices;
multiply a native index by that clock period to obtain its delay in time.

This is the spacing of stored arrival values. It is distinct from pixel dwell
time, line time, frame interval, and total acquisition duration. The step size
alone does not establish calibrated instrument timing accuracy.

Two laser frequencies occur in these examples:

| Quantity | 78.02 MHz, including R1 (4) and paneth WLL | 80 MHz, including paneth MP |
|---|---:|---:|
| Native increment | 96.9697 ps | 96.9697 ps |
| Recorded laser repetition period | 12.817226 ns | 12.5 ns |
| Rounded native bins used by the decoder | 132 | 129 |
| Rounded native window, bins × clock | 12.8 ns | 12.509091 ns |
| Current ICS 128-bin step | 100.1346 ps | 97.65625 ps |
| Current ICS 256-bin step | 50.06729 ps | 48.828125 ps |

The mixed-source `paneth_ctx555_1` entry therefore has the same native arrival
increment for HyD X 3 and HyD NDD 2, but different laser repetition periods.
The source's detector/sequence calibration determines those periods; no single
laser frequency applies to every channel.

## ICS output

The current exporter chooses an output histogram grid spanning one recorded
laser repetition period:

`exported bin width = 1 / laser frequency / output bin count`

For R1 (4), fresh 128-bin and 256-bin exports respectively contain:

| Header field | 128 bins | 256 bins |
|---|---:|---:|
| Temporal `parameter scale` | 0.100134580877 | 0.0500672904383 |
| Temporal `parameter units` | ns | ns |
| Temporal `history extents` | 1.28172263522e-08 | 1.28172263522e-08 |
| Temporal `history units` | s | s |

These are two unit representations of the same output window: the scale is
nanoseconds per bin, while the history extent is the complete window in
seconds. Their units must be read with their corresponding values. The JSON
sidecar also records the native clock, laser period and exported bin width in
seconds. The existing four Single-event R1 tile ICS files have the same
128-bin calibration as the fresh export.

Selecting 256 output bins creates a finer output grid; the underlying native
photon timestamps retain their original 96.9697 ps quantization. This does not
add new timing information. The ICS `t` axis represents photon microtime.
Acquisition T/Z planes and mosaic tiles are exported separately and identified
by filenames and sidecars, rather than by a physical elapsed-time axis.

### Calibration consistency issue

Histogram assignment currently uses:

`native bins = round(laser period / native clock period)`

`output bin = floor(native arrival index × output bins / native bins)`

The ICS header instead uses the unrounded laser period. Therefore the data
mapping and axis calibration have slightly different time windows:

- At 78.02 MHz, the mapping uses 132 × clock = 12.8 ns, while the header
  describes 12.817226 ns. The header scale is **0.134581% larger**.
- At 80 MHz, the mapping uses 129 × clock = 12.509091 ns, while the header
  describes 12.5 ns. The header scale is **0.072674% smaller**.

This is a consistency issue between the mapping and its written calibration;
it is not evidence that the recorded LIF clock or laser frequency is wrong.
Exact native-clock preservation would require a documented common policy for
bin assignment and the exported axis. Changing that policy would also change
some existing export expectations, so the audit records the issue without
silently changing scientific output.

The 60 supplied reference ICS files in the `.sptw` folders identify their
writer as **MIC File Converter**. Their history field records 12.412121 ns
for 128 bins, corresponding to 128 native clock increments, or 96.9697 ps/bin.
Their `parameter scale` entries are generic values of 1, so their history and
parameter fields should not be treated as interchangeable calibrations. Their
window convention differs from the current Interrogator exports; they should
not all be assigned an assumed 100 ps/bin or an assumed 12.5 ns window.

## PTU output

The current PTU exporter retains native decoded arrival indices. Its headers
store temporal resolutions in **seconds**:

| PTU field | R1 (4) value | Meaning |
|---|---:|---|
| `MeasDesc_Resolution` | 9.696969697e-11 s | 96.9697 ps per native microtime increment |
| `MeasDesc_GlobalResolution` | 1.281722635221738e-08 s | 12.817226 ns per sync tick |
| `TTResult_SyncRate` | 78,020,000 Hz | Recorded laser frequency, rounded to integer Hz |

The supplied reference PTU headers for No 2, PL109, X03 and Sample2 agree with
their LIF calibrations: the same native microtime step and the corresponding
78.02 or 80 MHz sync rate. This header comparison does not establish whether
the reference PTUs contain original hardware macrotime.

For Interrogator exports, the longer-timescale PTU macrotime is explicitly a
**synthetic raster clock**. It is assigned during export to place photons in
pixels, lines and frames. It is not copied from original hardware sync times
and does not preserve true pixel dwell, flyback, frame interval or acquisition
duration. The output header comment and sidecar state this interpretation.

The default export setting assigns **three sync periods per pixel**. For
R1 (4), the fresh PTU records confirm:

| Quantity | Exported synthetic value |
|---|---:|
| Pixel spacing | 38.45168 ns |
| Line-start interval | 39.40015 µs |
| Frame-start interval | 40.34576 ms |
| Frame markers in one tile | 120 |
| Last record's synthetic time in that tile | approximately 4.84149 s |

By comparison, the original LIF's `RawData/PixelTime` records **1.4 µs per
pixel**. The default synthetic PTU pixel spacing is therefore not the real
acquisition pixel time. Real acquisition durations and count rates cannot be
recovered by treating the exported synthetic timestamps as measured elapsed
time. A pixel-tick setting changes synthetic raster spacing, not the photon
microtime resolution.

## Other timing limits and evidence

The LIF retains scan timing fields and timestamp lists in addition to the
photon clock. The current model/export path does not carry these through as
an original elapsed-time calibration. This audit does not assign units or
epochs to the timestamp-list values, or infer precise frame timing from them.

PTU preserves native arrivals that lie beyond the nominal laser period.
Preview/ICS histograms put those events in the last output bin. Comparisons
between formats must account for that existing histogram policy as well as
for the time-axis calibration and selected photon population.

All 121 inspected entries have a clock and laser rate. The code also contains
fallback calibration paths for missing values; those paths were not needed
for the inspected examples and should not be mistaken for recorded values.

Evidence files:

- `validation/timebase-audit.json`: all nine LIF catalogues and timing values.
- `validation/timebase-existing-ics-headers.json`: 65 existing ICS headers,
  comprising 60 MIC File Converter references and five Interrogator exports.
- `validation/timebase-ptu-headers.json`: supplied PTU calibration headers.
- `validation/timebase-fresh-exports.json`: actual newly written 128/256-bin
  ICS and PTU headers/sidecars for R1 (4), tile row 1, column 1.
- `validation/timebase-ptu-record-audit.json`: independently read line/frame
  marker intervals and synthetic duration from that complete PTU payload.

Implementation references: `catalog_metadata.py` and `catalog_sequences.py`
read source timing; `decay.py` chooses rounded native period bins;
`ics.py:write_ics` writes the ICS axis; `ptu_export.py:_dataset_ptu_header`
and `ptu.py:GenericT3Writer` write the PTU calibration and synthetic raster.
