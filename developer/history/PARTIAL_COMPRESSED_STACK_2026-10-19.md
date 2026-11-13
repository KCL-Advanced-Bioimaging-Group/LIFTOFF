# Partial compressed WLL/MP stack — 19 October 2026

Status: fixed and validated in the source version.

## Cause and source evidence

`paneth_ctx555_5` in
`20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif` reserves
12 Z-planes, but contains photon rows for only the first 10. The previous
decoder required the row count to match the complete declared stack. It
therefore rejected otherwise usable data from both recorded channels.

The evidence for the recorded extent is independent of the entry's name:

| Source evidence | Finding |
| --- | --- |
| Raw and intensity dimensions | 512 × 512, T=1, Z=12 |
| Compressed container header | 5,120 rows |
| Descriptor table | 11,944 descriptors, 3,412 groups, 5,120 row payloads |
| Post-descriptor footer | First 64-bit value also equals 5,120 |
| Repetition metadata | Two line repetitions, one frame repetition |
| Linked intensity images | Ten populated planes followed by two entirely zero planes in both channels |
| Spatial verification | Every recovered plane matches its corresponding intensity image; correlation exceeds 0.99 for all 20 channel/plane images |

There are 512 encoded rows per recovered plane. The two line repetitions
are accumulated within these rows. Explicit line-repeat rows would allow
only five planes, which contradicts the ten populated intensity planes.
No additional compressed image stream exists in the reserved tail of this
memory block: after the 16-byte footer, all 405,675,306 remaining bytes
are zero. The acquisition metadata does not establish why recording ended
before the reserved extent was filled.

The WLL channel uses 555 nm excitation and HyD X 3 detection; the MP
channel uses 740 nm excitation and HyD NDD 2 detection. Their respective
78.02 MHz and 80 MHz pulse frequencies remain separate. Summed linked
intensity counts are 304,906,993 and 26,823,634. Those reference counts
are distinct from counts after photon selection and arrival-window
filtering.

## Implementation

The catalogue can recover a complete recorded prefix of a compressed
T/Z acquisition. Recovery requires a valid compressed row index,
validated intensity channel and T/Z byte strides, corroborating empty
trailing reference planes across all stored detector channels, and a
unique compatible repetition layout. Row deficits, ambiguous layouts,
nonfinite references and incomplete final planes remain rejected.

Logical plane strides now exclude interleaved detector channels. The
synthetic checks cover all six C/T/Z storage permutations, including
time-first and depth-first storage.

The original axis declarations and calibration remain intact. A separate
recorded-plane count restricts navigation and exports to available
planes. For this entry:

- Both channels decode; the overview sums Z=1 through Z=10.
- The depth selector offers those ten planes.
- The details panel says **10 of 12 planes recorded**.
- Split ICS and PTU exports produce ten outputs per channel, retaining
  the original Z indices.
- Both export sidecars include `planeCoverage`, identifying 12 declared
  planes, ten recorded planes and two absent trailing planes.
- No zero-filled photon images are invented for Z=11 or Z=12.

There are no filename-specific conditions in the implementation. Partial
stage matrices need independently validated tile availability and are
outside this recovery rule; existing complete mosaic support is retained.

## Validation

All final checks passed:

- **301 general regression tests**, including 34 new synthetic cases.
- **Three real-data tests**: all 20 recovered channel/plane images;
  both-channel navigation through every depth in all three selection
  modes, pixel hover, ROIs and both export dialogs; and every acquisition
  in the supplied mixed-source LIF through the existing viewer regression.
- **60 complete ICS/PTU round trips**: two channels × ten Z-planes ×
  three photon selections. No PTU row sampling was used. Native,
  128-bin and 256-bin time grids and both ICS compression options were
  exercised. Independent readers verified ICS arrays, PTU arrival
  histograms, photon accounting and timing metadata.
- **Six overview checks**: each channel and selection mode gives exactly
  the sum of its ten individual plane arrays and excluded-event counts.
- **110 maintained Python files** pass Ruff formatting and linting,
  Pylint (10.00/10) and Pyrefly (zero diagnostics).
- Re-indexing all nine supplied LIFs preserves the other 119 channel
  records. Only this acquisition's two records change from unresolved
  to recovered. The catalogue now has 116 resolved entries containing
  215 recorded planes. Five other entries remain unresolved for their
  previously documented, separate index/layout issues.

The full export checks inspected 763,887,005 emitted photons across the
three overlapping selections. This is a validation workload count, not
a count of unique source photons.

Evidence is in `validation/paneth-multiplane-2026-10-19/`:

- `container-evidence.json` and `plane-evidence.json`: source layout and
  per-plane spatial checks.
- `catalogue.json` and `catalogue-changes.json`: all-source comparison.
- `full-exports.jsonl` and `full-exports.summary.json`: 66 passing export
  and overview cases, with zero failures.
- `regression-tests.log`, `source-viewer-regression.log` and `quality.log`.
- `partial-stack-viewer.png`: verified two-channel view at Z=10.

Verified export payloads were removed after inspection; their sidecars,
hashes and scientific summaries remain. Supplied measurements, native
libraries and standalone executables were not modified.

## Correction to the earlier stress audit

The earlier audit classified this entry as unresolved and tested its
rejection. That did not establish whether its recorded planes could be
recovered. This investigation supersedes that classification. A dedicated
real-data regression now requires this entry to decode successfully, so
an unresolved result cannot silently count as a passing test for it.
