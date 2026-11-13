# Multiple excitation/emission review

This is an investigation and design recommendation. No application source or
GUI implementation was changed during this review. Temporary analysis scripts
in `.cache` supplied sequence-specific parameters to the existing decoder;
their results are retained in
`validation/multi-excitation-investigation.json`.

## Recommendation

Keep one data entry per acquisition. Add an excitation/scan-setting selector
and scope the existing emission-channel selector to the selected setting.
Provide an **All recorded pairs** comparison view, with one image and decay
panel for each acquired excitation/emission combination. Show excitation,
laser source, emission band, detector, and repetition counts on each panel.

The internal hierarchy should be:

```text
Acquisition
  Excitation / scan sequence
    Detector / emission channel
      Timepoint and Z plane
```

The original acquisition remains easy to find, related images stay together,
and existing side-by-side emission comparison and ROI interactions can be
extended to sequence-aware panels. Separate excitation entries are a valid
alternative presentation, but require the same underlying decoder repair.

## What these files contain

Both mixed acquisitions use two wavelength settings of MP2, acquired as
separate Leica sequence items. The channel metadata explicitly references
`SequenceItemIndex` and the detector index within that sequence.

| Acquisition | Sequence | Excitation | Emission / detector | Line repeats | Indexed row range |
| --- | --- | --- | --- | ---: | --- |
| LACT+PYR1 | 1 | 1040 nm (MP2) | 600–610 nm / HyD NDD 2 | 16 | 0–8191 |
| LACT+PYR1 | 2 | 840 nm (MP2) | 470–560 nm / HyD NDD 1 | 1 | 8192–8703 |
| LACT+PYR2 | 1 | 1040 nm (MP2) | 600–610 nm / HyD NDD 2 | 16 | 0–16383 |
| LACT+PYR2 | 2 | 840 nm (MP2) | 470–560 nm / HyD NDD 1 | 16 | 16384–32767 |

LACT+PYR1 is 512 × 512 and declares `SequentialFrame`; LACT+PYR2 is
1024 × 1024 and declares `SequentialStack`. Their linked FrameOffsets tables
contain cumulative row ends `(8192, 8704)` and `(16384, 32768)` respectively.
Those ends agree with the two sequences' declared repetition counts.

The two emission channels displayed for these samples represent two recorded
pairs. The file does not record all four combinations of its two excitation
settings and two detectors. An excitation selector must therefore offer only
the emission channels actually recorded under that setting.

## Why the current model fails

1. **Sequence-specific repetition counts are collapsed.**
   `catalog_metadata._block_layout` takes the last FrameRepetitions and
   LineRepetitions values in the block. `_resolve_repetition_model` then
   expects `height × T × Z × frame repeats × line repeats`, with no sequence
   axis. LACT+PYR2 consequently expects 16,384 rows instead of 32,768.
   LACT+PYR1 collapses the two repeat counts to 1 and expects only 512 rows
   instead of `512 × 16 + 512 × 1 = 8704`.

2. **Valid sequence boundaries are rejected.**
   `_parse_frame_row_starts` accepts a FrameOffsets count only when it equals
   `T × Z`. These acquisitions have one T/Z plane and two sequence entries,
   so their valid two-entry tables are discarded.

3. **Logical channel number is used as a detector route.**
   The catalogue now recognises the correct detector names and excitation
   labels, but does not retain sequence index and sequence-local detector
   route as separate decoding fields. Both sequence items in these samples
   use local detector route zero. The photon parser selects routes using the
   displayed channel index, so the second displayed channel requests route
   one and receives zero photons. Simply suppressing the row-count error
   would not repair this.

4. **Other sequence-specific metadata needs the same scope.**
   Dead-time lookup currently matches the flat channel index and falls back
   to the first detector. Both supplied detectors have the same dead time,
   so this does not alter these validation results, but that lookup must be
   corrected for acquisitions with different detector dead times. Timing,
   repetition counts, intensity references, cache identities and exports
   also need explicit sequence/detector identities.

The current successful multi-emission examples have one sequence containing
two detectors with routes zero and one. Their rows are shared between the
detectors, so one row-layout model and a route selection are sufficient.
Examples verified include HCConly Series005/Series008 and the resolved
Autofluorescence acquisitions. This is a distinction in storage organisation,
not an inability of the low-level photon decoder to read the mixed samples.

The reader's current four-channel limit is also applied to the total flat
channel count. A sequence-aware model should apply route limits to each
sequence, allowing several sequences to reuse the same detector routes.

## Validation of the diagnosis

The isolated probes used the existing native decoder with each sequence's
validated row range, its own line-repeat count and local detector route zero.
All four **All Photons** totals match the supplied LAS X/SymPhoTime PTUs:

| Acquisition | Sequence 1 photons | Sequence 2 photons |
| --- | ---: | ---: |
| LACT+PYR1 | 7,058,116 | 1,679,644 |
| LACT+PYR2 | 15,994,608 | 108,134,341 |

An independent pass through the Python vector-selection path also matches
every native arrival bin in all four PTUs, not just the totals. Using the
incorrect flat route one gives zero events for both second sequences.
First Photon and Single-event modes also produce nonzero sequence-specific
results after route correction; corresponding reference PTUs for those
modes were not supplied, so their complete validation remains future work.

Spatial comparison with the companion 128-bin ICS files confirms the expected
line-repeat mapping and identity orientation. Three intensity images agree
pixel-for-pixel within the ICS time-bin extent. LACT+PYR1 sequence 2 differs
by seven photon counts across its image, with correlation 0.99999994; its
complete PTU arrival distribution agrees exactly. The small ICS conversion
discrepancy remains recorded rather than being silently corrected.

This establishes a validated repair strategy for the supplied sequential
frame/stack examples. Multi-sequence timelapses, Z stacks and other sequential
orders still need dedicated tests before general support is claimed.

## GUI choices

| Choice | Presentation | Benefit | Tradeoff |
| --- | --- | --- | --- |
| A: Separate entries | One left-hand entry per excitation sequence; emission selection works as today | Straightforward navigation and close to LAS X's separate sequence exports | More list entries; pairing and cross-excitation comparisons are less obvious |
| B: One grouped entry, recommended | One acquisition entry; excitation and emission selectors; All recorded pairs view | Keeps related data together and scales to several detectors under each excitation | Selectors must be linked and panel titles must identify both excitation and emission |
| C: Expandable acquisition | A parent acquisition entry expands into selectable excitation children; parent can show all pairs | Combines explicit sequence navigation with acquisition grouping | Adds a tree/list interaction and another navigation state |

For choice B, selecting 1040 nm in LACT+PYR2 would offer HyD NDD 2 / 600–610 nm;
selecting 840 nm would offer HyD NDD 1 / 470–560 nm. Comparing all recorded pairs
would show those two images and their histograms side by side. It should not
create empty 1040 nm/HyD NDD 1 or 840 nm/HyD NDD 2 channels.

Open the selected excitation first and make cross-excitation comparison an
explicit choice. Decode/cache selected panels on demand: two 1024 × 1024,
129-bin uint32 cubes already occupy approximately 1 GiB. Keeping one
acquisition entry need not mean eagerly decoding every recorded pair.

Keep decay curves and photon populations separate between excitation settings
unless the user explicitly requests combination. Preserve T/Z controls and
coordinate-based ROI comparison, while retaining each panel's acquisition
timing and repetition metadata. LACT+PYR1's 16-versus-1 repeat counts make that
metadata particularly relevant to intensity comparisons.

Group by explicit scan-sequence identity, not wavelength alone: settings can
reuse wavelengths or detectors with different acquisition parameters. If a
single setting contains simultaneous illumination without separable
excitation identifiers, present its combined illumination as one setting.

## Implementation scope after choosing a GUI

- Retain acquisition, sequence, display-channel and local detector-route
  identities separately.
- Resolve row ranges using the FrameOffsets/LineOffsets tables and declared
  sequence order, alongside the existing T/Z/repetition mapping.
- Scope calibration, dead time and intensity references to each sequence and
  detector.
- Include sequence identity in cube/ROI cache keys and export identities.
- Validate all four supplied PTUs and the retained single-excitation samples;
  add mixed-sequence T/Z coverage rather than treating sequences as timepoints.
- Implement the chosen GUI presentation over the same sequence-aware data
  model, keeping existing one-excitation workflows familiar.
