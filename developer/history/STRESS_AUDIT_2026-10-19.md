# Source-version stress audit — 19 October 2026

Status: complete. All final checks pass after the fixes and reruns below.

Follow-up correction: this audit classified `paneth_ctx555_5` as unresolved
without establishing whether its recorded planes were recoverable. The
[partial-stack investigation](PARTIAL_COMPRESSED_STACK_2026-10-19.md)
supersedes that classification: both channels now decode ten recorded
Z-planes from a declared twelve-plane stack, with full export validation.
The counts and unresolved-entry table below describe the earlier audit.

The audit uses the source checkout only. Supplied measurements and standalone
executables are unchanged. Evidence is under
`validation/stress-2026-10-19/`.

## Input coverage

The complete example directory contains nine LIF files, 100 PTUs, 61 ICS
files, 127 JSON metadata files, four empty vendor workspace logs and a notes
file. The LIF catalogue contains 121 recorded channel entries and 224 nominal
image planes. Of these, 114 entries containing 195 planes have sufficient row
information for reliable decoding. The other seven entries account for 29
nominal planes.

All nine sources were opened together in one workspace. Repeated import
preserved 121 unique entries, and both export dialogs correctly distinguished
available data from entries with unresolved row information. Every acquisition
was also exercised through the production preview workers, including all
available channels, first/last time and Z planes, hovering, ROIs, zoom and
clearing data. Screenshots were saved for a representative acquisition from
each source.

| Final check | Result |
| --- | ---: |
| Distinct maintained pytest cases, with final reruns replacing earlier results | 957 passed |
| Full valid-plane/photon-mode native decode and ICS round-trips | 585 passed |
| PTU round-trips within that matrix | 366 full streams and 219 compressed samples passed |
| Unavailable channel entries rejected consistently | 7 passed negative checks |
| Summed T/Z versus separate-plane comparisons | 21 passed |
| Supplied PTU, ICS and metadata/workspace file reads | 292 passed |
| Acquisition groups exercised in the viewer | 76, covering all 121 channel entries |
| Maintained Python files checked by all quality tools | 106 passed |

The pytest total comprises 267 synthetic/unit/GUI cases and 690 cases using
the supplied data. The first full run had 912 passes and three outdated GUI
count assertions; those were corrected and rerun successfully. The combined
result file retains the final result for each distinct case. These test and
audit counts overlap and should not be added together.

## Fixes from the audit

1. **Consistent export rejection for unresolved row layouts.** Compressed
   PTU export could proceed even when the viewer rejected the row layout.
   The PTU writer now applies the same guard before creating output. A batch
   still exports its valid entries and reports failures for unavailable ones.
2. **Earlier compressed descriptor diagnostics.** The two channels of
   `paneth_ctx555_7` have entirely zero-filled descriptor tables. Their
   container headers report image rows, but the tables cannot locate those
   rows. Catalogue validation now identifies this condition and also checks
   descriptor bounds, control flags, row counts and bit-length accounting.
   The entries retain their metadata and thumbnails with an explicit failure.
3. **Preflight cache validity.** Cached export readiness now includes the row
   model, repetition counts and layout status, so an earlier success cannot
   hide a changed or unresolved layout.
4. **Comparison-view photon accounting.** The arrival-window exclusion
   tooltip previously retained the last decoded panel's count. It now reports
   the sum across all displayed channels and tiles, also shown in the status
   line when nonzero.
5. **Partial timelapse ICS export.** `Series011` and `Series013` have validated
   per-plane indexes but incomplete final repetitions. Their previews and
   export preflight worked, while a separate status-string check still blocked
   split ICS export. That check now accepts validated partial acquisitions.
   All 52 time points in all three photon selections pass export round-trips.
   Original image dimensions and the actual captured row counts are retained;
   absent data remains empty and the metadata records the partial status.

The independent ICS inspection reader was extended to support the axis orders
used by the supplied LASX files. This expands validation coverage; it does not
add ICS import to the application viewer. Twelve independent nonsquare-array
tests cover all six spatial/time axis orders and both compression choices.

Three older GUI assertions in the timelapse and mixed-source tests expected
the displayed count to equal every PTU photon. After the earlier timing
changes, the display intentionally excludes arrivals outside its physical
time window. The tests now account for displayed plus excluded photons; the
timelapse test also checks the complete displayed histogram against the PTU
bins. All corrected cases pass.

## Scientific and interaction checks

- Full native decoding and ICS array round-trips for every valid plane in
  all three named photon selections. Native, 128-bin and 256-bin timing and
  gzip/uncompressed output are distributed across these cases.
- Full PTU round-trips for LMSRAW planes, including independently reading
  photon records, markers, overflows, chronological ordering and arrival
  histograms. Compressed PTU samples use 64 encoded rows from every plane;
  the separate historical-reference suite additionally exercises complete
  compressed PTU exports. Compressed PTU export through Python remains slow
  on large acquisitions.
- Exact equality between summed T/Z images and the sum of their separately
  decoded planes in every photon mode.
- Native/Python agreement and historical full-array fingerprints, including
  the existing 1-, 4- and 16-thread regressions.
- Selection and graph controls, single/comparison/mosaic previews, pixel
  coordinate mapping, ROI unions and retention, graph separation, time/Z
  navigation, import/removal/clearing, cancellation and closing during work.
- GUI export dialogs and workers producing all 64 tile/channel/time/Z outputs
  from a synthetic acquisition in each export format.
- Synthetic 3-by-2 mosaics with four channels, unequal repetition counts,
  two light sources and native clocks, three time points and four Z planes.
  Both frame and stack sequencing are checked, with every bin and pixel of
  288 planes compared independently in each photon mode.
- Malformed descriptor indexes, invalid batch entries, missing calibration,
  integer promotion/overflow, output collisions, and interrupted-write cleanup.

Temporary full-export payloads are removed after successful independent
verification. Count fingerprints, photon histograms and sidecars are retained.
The checked PTU streams contain 14,078,895,969 photon records in total across
the selections. This is the verification workload, not a unique-photon count.

## Supplied reference differences

All 100 supplied PTUs and 61 ICS payloads were read successfully. For the 60
LASX ICS files, 58 match the source decoder exactly at their native 128-bin
window. The remaining two match at every pixel except the final column:

| Acquisition / channel | Additional source/PTU photons in that column |
| --- | ---: |
| `HCC_mScr-pyr+mTFP-lact_LACT(pileup)` | 1,124 |
| `HCC_mScr-pyr+mTFP-lact_LACT+PYR1`, sequence 2 | 7 |

For these acquisitions, the source arrival distributions agree with the
supplied LASX PTUs. The difference is in the supplied ICS representation;
the decoder was not changed to discard those photons. The older Interrogator
ICS file was inspected separately and is not treated as a LASX reference.

## Entries with unavailable row information

| LIF / acquisition | Channels | Reason |
| --- | ---: | --- |
| `20251009…nadph.lif` / `paneth_ctx555_5` | 2 | 5,120 recorded rows; metadata expects 6,144 with in-row accumulation or 12,288 with explicit repeats |
| Same LIF / `paneth_ctx555_7` | 2 | Zero-filled compressed row descriptor tables |
| `Autofluorescence.lif` / `Series006` | 2 | 166,023 rows; neither declared repetition model matches |
| `PL109 R72C CC CCCP NH4Cl.lif` / `Series005` | 1 | 51,200 rows versus 30,000 expected from the image metadata |

These entries are rejected with a diagnostic. Recovering them would require
further acquisition-specific investigation.

## Python quality

The previously used tools are retained: Ruff formatting, Ruff linting, Pylint
and Pyrefly. All 106 maintained Python files, including the application,
forensic utilities, build/audit tools and tests, pass. Pylint reports 10.00/10
and Pyrefly reports no diagnostics. Formatting uses 79-character code lines
and 72-character documentation lines. Generated environments, caches and
build output are excluded.

## Reproduction and evidence

Use the source environment and set `LEICA_EXAMPLE_DATA_DIR` to the supplied
example directory. Run `python -m tools.quality` for all quality checks and
`python -m pytest` for the maintained regressions, with a workspace-owned
`--basetemp` and `cache_dir` as in the saved logs.

`python -m tools.stress_audit --input <examples> --output <separate audit folder>`
supports `--phase exports`, `--phase references` and `--phase overviews`.
Use `--compressed-ptu-rows 64` to reproduce the bounded compressed PTU matrix;
omitting that option requests full compressed streams. Successful cases are
resumable. `--workers 8` runs independent export checks in separate processes;
that setting was used for the final matrix. JSONL logs preserve earlier
failures and subsequent corrections. Six earlier cases for the zero-filled
descriptor tables are superseded by their explicit negative checks in the
final catalogue and summary.

The final catalogue, export evidence, reference comparisons, JUnit reports,
quality output and screenshots are in the audit evidence directory. Synthetic
multichannel Navigator combinations are extensively tested; an actual
multichannel Navigator acquisition remains unavailable for direct validation.

The 302 supplied files retain their original names and sizes. Four leftover
audit payloads from interrupted or failing checks were removed after the
final successful run; the audit records their paths and sizes separately.
