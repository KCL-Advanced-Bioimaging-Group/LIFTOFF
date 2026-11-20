# ICS rebinning beats investigation — 17 November 2026

Historical investigation of the previous laser-period-scaled export. On
19 November 2026, numeric export was changed at the user's request to trim
the first 128 native bins and sum exact integer groups. See the current
`USER_GUIDE.md` and `developer/SCIENTIFIC_SEMANTICS.md` for that contract.
The beat reproduction and validation counts below refer to the earlier code.
Later on 19 November, the numeric window was generalized to a power-of-two
count derived from the selected repetition rate, with an explicit actual-rate
fallback and rate-dependent default. The recorded clock width stays fixed.

## Finding

The current numeric ICS export can introduce deterministic spikes or "beats"
into a smooth native decay. This was reproduced with a synthetic flat input
and a synthetic 3 ns exponential, encoded as LMSRAW and passed through the
actual decoder, ICS exporter and independent ICS reader. An acquisition defect
is therefore not required to produce this effect.

No arithmetic, count-accounting, cache, native/Python parity or ICS payload
error was found in the tested cases. The cause is the existing whole-arrival
histogram assignment when the requested output grid and native arrival clock
are not commensurate. This is a limitation of the binning method, and can be
undesirable for fitting a smooth decay even though every photon is assigned
according to the documented physical boundaries.

The user's particular affected export was not identified. These results
establish a software mechanism and its predicted signature; they do not prove
that every observed beat has that cause or rule out instrument effects.

## What the exporter actually does

`timing.time_grid` calculates an output width `delta = 1 / frequency / bins`
from the unrounded recorded laser frequency. `TimeGrid.indices` assigns a
native arrival `k` at time `k * clock` using half-open boundaries
`[j * delta, (j + 1) * delta)`. Its shared lookup supplies the native workers;
the Python workers apply the same boundaries. Arrivals outside the window are
excluded and counted. `ics.write_ics` writes that grid's width and extent in
seconds, with 17 significant digits.

This is re-histogramming of quantized photon times. There is no fractional
splitting of a native count, interpolation, or polyphase resampling filter.
The function named `ics_export.rebin_cube` is only an optional cache shortcut:
it combines bins when their physical boundaries align exactly. Otherwise the
exporter decodes the selected source again onto the requested physical grid.
It does not use the rounded native-bin count to set the calibrated output
window. The older mismatch described in `TIMEBASE_AUDIT_2026-10-16.md` was
superseded by `TIMING_IMPLEMENTATION_2026-10-16.md` and is not the cause found
here.

With `r = delta / clock`, output bin `j` receives
`ceil((j + 1) * r) - ceil(j * r)` native arrival values in exact arithmetic.
When `r` is just above one, most output bins receive one native value and
occasional output bins receive two. A flat native histogram consequently
develops exactly doubled bins, despite conserving its included photon count.

## Predictions for the supplied recorded clock

The supplied files record `clock = 9.696969697e-11 s` (96.9697 ps).

| Quantity | 78.02 MHz | 80 MHz |
| --- | --- | --- |
| Laser period | 12.8172263522 ns | 12.5 ns |
| Period in native increments | 132.177646757 | 128.90625 |
| Complete native bins | 133 | 129 |
| 128-bin output width | 100.134580877 ps | 97.65625 ps |
| Native increments per output bin | 1.03263786529 | 1.00708007812 |
| Native values in output bins | 123 bins with one; 5 with two | 127 bins with one; 1 with two |
| Doubled positions, zero based | 0, 30, 61, 91, 122 | 0 |

At 78.02 MHz, the interior spikes are 30–31 output bins apart, approximately
3.07 ns. At 80 MHz there is no repeating interior doubling pattern from this
particular mismatch. Shorter lifetimes can also make the later spikes harder
to see, and low counts can hide them in noise.

Changing the requested bin count changes the pattern. At 78.02 MHz, 64 output
bins contain either two or three native values, and 32 contain either four or
five. Increasing to 256 creates 123 structurally empty output bins alongside
133 occupied bins for a flat native input. At 80 MHz, 256 creates 127 empty
bins and 129 occupied bins. Finer grids cannot recover missing sub-bin timing.

## Checks and retained evidence

- **58 existing timing tests passed**, comprising 49 functional cases and
  nine supplied-file cases. The supplied-file cases cover 13 detector/tile
  samples across all nine LIF files, including both paneth sources and all
  four Navigator tiles. Each sample uses up to 64 indexed rows of plane zero;
  these are not full-acquisition validations. Native and 128-bin ICS exports
  were independently reconciled with exported PTU microtimes and their written
  calibration. The separate expensive full-Navigator-tile test was excluded.
- **67 additional checks passed**: 31 new rebinning regressions and 36 existing
  reflection-export/ICS-reader cases. The new regressions compare every pixel
  and bin for flat/exponential input, both recorded laser rates, native/128/256
  output, Python/native workers, one/four native threads, fresh/cached exports,
  and independent ICS readback. They verify unchanged caches, photon accounting
  and header precision. Exact rational arithmetic independently agrees with
  production assignments for all 256 LMSRAW arrival values, both recorded
  frequencies, and all eight supported numeric bin choices. A separate exact
  boundary test checks left-edge inclusion and window-end exclusion.
- A further independent sum of the native ICS counts using explicit physical
  inequalities reproduced all 128-bin counts for the 13 supplied samples.
- Ruff formatting/lint, Pylint and Pyrefly passed for the new test module.

Machine-local evidence is retained under `validation/resampling-audit/`:
`timing-tests.xml`, `regression-tests.xml`, `evidence.json`, the synthetic
`demonstration/` ICS files and decay CSVs, and `synthetic-beats.png`.
`build_evidence.py` reproduces the numerical comparison and figure from the
retained test exports. The figure overlays actual independently read synthetic
native and 128-bin ICS counts; it is not a measurement from a specimen.

Run the focused checks from the repository root with `QT_QPA_PLATFORM=offscreen`
and `LEICA_EXAMPLE_DATA_DIR` set to the example-data folder:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_timing.py tests/test_timing_real.py -k 'not full_navigator' -q
.venv/Scripts/python.exe -m pytest tests/test_ics_rebinning.py tests/test_reflection_exports.py tests/test_ics_inspection.py -q
```

## Practical interpretation

Compare native and numeric exports from the same dataset, detector, plane and
photon selection. A smooth native curve acquiring peaks at the predicted output
positions supports the binning explanation. A feature already present in native
data needs a separate acquisition/decoder investigation. Native timing is the
available way to avoid introducing this grid-mismatch pattern, subject to the
analysis package accepting 129/133 or other non-power-of-two bin counts and the
recorded increment. It still retains any effects present in the acquired data.

A future fractional-overlap or filtered resampling option could reduce these
patterns, but would introduce a model for the unrecorded timing within native
bins and change count/statistical semantics. Such a change needs explicit
provenance and validation for downstream lifetime fitting. It was not silently
introduced here. The scientific algorithm, defaults, native libraries and
standalone executables remain unchanged; this investigation adds regression
coverage and a user-guide explanation.
