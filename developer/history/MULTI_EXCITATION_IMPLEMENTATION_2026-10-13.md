# Sequence-aware decoding and Choice B

Implemented in the source tree, now `LIFTOFF_Source`. The installed release folders
and supplied LIF/PTU/ICS data are unchanged.

## GUI

An acquisition retains one entry in the left-hand list. The follow-up UI
refinement replaces the dropdowns with an expandable **Excitation | Emission**
table. Excitation checkboxes enable their recorded emission choices; inactive
emissions are grey and cannot be clicked. Each emission checkbox is independent,
so arbitrary recorded pairs can be compared across sequences. Collapsing a
setting retains its selections. Re-enabling a setting remembers its chosen
emissions. The first sequence and all its emissions are selected initially,
including for one-excitation acquisitions.

The alignment refinement on 14 October places each excitation and its first
emission on the same row. Only additional emissions use expandable child
rows. Both checkbox columns share a vertical centre even when emission text
wraps. Disabled first-emission cells reject mouse and keyboard interaction
without disabling the excitation checkbox beside them.
The refinement passed all 92 functional tests and three real-data GUI checks;
native mouse/keyboard checks cover the shared row. Quality tools are clean.
Results are in `validation/aligned-pair-table-*`, with a compact preview at
`validation/screenshots/aligned-excitation-emission-table.png`.

Each selected recorded pair has its own image and decay, labelled only with
excitation/source and emission/detector. Sequence/repetition details remain in
metadata and exports. Each decay retains its own time calibration. No
unrecorded excitation/emission combinations are created. The T/Z selector
continues to represent T/Z planes independently of sequences, and retains the
selected plane when changing pair choices. An empty selection clears the
previous image and graph.

Active ROIs can be retained using the existing confirmation interaction.
Their values are recomputed from each pair's own cube after selection, plane
or event-selection changes. Metadata can scroll when panel height is
insufficient, and table labels wrap to keep detector names visible.

## Data model and decoder

`DatasetInfo` preserves the acquisition/memory block, flat display-channel
index, original `SequenceItemIndex`, and sequence-local detector route as
separate identities. Multiple sequences may reuse route zero. The four-route
PulseVersion2 limit applies within each sequence, rather than to the number
of display channels across the acquisition.

For multi-sequence LMSRAW data, `catalog_sequences.py` validates the
FrameOffsets version, entry count, monotonic cumulative row ends and final
row count against the linked LineOffsets table. Declared C/T/Z order and
SequentialFrame/SequentialStack mode identify each sequence's T/Z intervals.
Sequences do not increase T/Z plane counts. Per-sequence line/frame repetition
counts determine how the owned rows map to image Y. The global line table
remains available to the bounded reader; decoding reads only owned intervals.

Clock period, pulse frequency and spatial calibration follow detector,
sequence and explicitly shared RawData scope. Dead time belongs to the
selected sequence and detector, with no fallback to a different detector.
Malformed indexes and unsupported storage orders produce explicit failures.
SequentialLine storage has not been validated and is declined rather than
being interpreted as frame/stack storage.

`linked_intensity.py` resolves intensity planes using channel offsets and
declared T/Z byte strides, including interleaved C/T/Z planes. It validates
dimensions, bounds and non-overlapping plane identities. Missing or ambiguous
references remain unavailable; they cannot supply another pair's thumbnail,
photon total or orientation reference. Existing half-float thumbnail handling
continues to treat previews separately from exact photon references.

Series013 has 32 photon timepoints but only 31 declared F32 intensity planes.
The thumbnail now uses those available, bounded preview planes. It does not
turn that partial preview into an exact photon count or orientation reference.
The existing decoder continues to handle its partial final photon frame.

## Caches and exports

Multi-sequence dataset keys include sequence, local route and display-channel
identities. Cubes record their dataset key and selected plane. ROI snapshots
retain the source pair key; comparison panels hold separate cubes. Export
preflight and displayed-count state also use the sequence-aware keys.

ICS cache reuse checks pair identity, event selection and overview/plane
identity. Rebinning preserves provenance. Multi-sequence ICS/PTU filenames
include `seqNN_Ex_<wavelength>`, followed by emission/detector and any T/Z
suffix. Export selection rows identify excitation and emission together.
JSON sidecars retain the original acquisition, sequence, display channel,
local detector route, calibration and indexed row ranges. Single-excitation
keys and proposed filenames retain their existing form.

## Optical metadata correction

The enabled 1040 nm sequence in both LACT+PYR acquisitions records
**570–650 nm / HyD NDD 2**. The earlier 600–610 nm label came from an inactive
detector setting in the other sequence. Scoping optical settings to the
enabled sequence corrects that label; the 840 nm pair remains
470–560 nm / HyD NDD 1.

## Validation

The four supplied PTUs are checked through the production catalogue and
readers, without the investigation's temporary sequence overrides. An
independent PTU inspector and Python event-vector reader compare every native
arrival bin. Native decoded cubes also match the reference photon totals and
displayed decay after the established native-period overflow handling.

| Acquisition | Sequence | All Photons |
| --- | ---: | ---: |
| LACT+PYR1 | 1 | 7,058,116 |
| LACT+PYR1 | 2 | 1,679,644 |
| LACT+PYR2 | 1 | 15,994,608 |
| LACT+PYR2 | 2 | 108,134,341 |

The native/Python synthetic regressions cover sequential frame and stack
storage, both T/Z axis orders, unequal line/frame repetitions, reused detector
routes, different clocks/dead times/calibrations, six display channels over
two hardware routes, non-contiguous intensity planes, malformed frame indexes,
ambiguous intensity references and foreign/plane cube cache rejection.
All/First/Single-event selections are checked. Split PTU/ICS exports cover all
16 pair/T/Z combinations, with independently inspected PTU counts and sidecar
identity checks.

GUI regressions use real workers to check scoped emission menus, excitation
switches, T/Z preservation, comparisons, mirrored ROIs and photon-filter
changes. Both supplied mixed acquisitions open and switch successfully.
Saved screenshots show the selected 1040 nm settings and the LACT+PYR1
comparison.

- Functional regressions: **88 passed**.
- No 2 and all 20 Series011 PTUs, including GUI navigation: **24 passed**.
- Supplied mixed-acquisition GUI checks: **2 passed**.
- Full retained scientific reference checks and four supplied PTUs:
  **594 passed** (585 histogram comparisons at 1/4/16 threads,
  five catalogues and four sequence PTUs).
- Final integration recheck of supplied PTUs, GUI workflows and retained
  catalogue metadata: **12 passed**.
- Ruff format/lint, Pylint and Pyrefly: clean.

Machine-readable results and logs are in `validation/sequence-*.xml` and
`validation/sequence-*.log`; screenshots are in `validation/screenshots/`.
The table/thumbnail follow-up results are recorded in `validation/pair-table-*`
and `validation/pair-selector-quality.log`.

Follow-up validation: **92 functional tests passed**, **17 integration checks
passed** (including all four supplied PTUs, retained catalogue metadata,
No 2/Series011 GUI checks and Series013), and the final table/GUI recheck had
**7 passes**. All four quality tools are clean. Checkbox tests use native
mouse interactions, and the source GUI was visually checked with both the
comparison view and Series013's visible thumbnail. Screenshots are
`pair-table-LACT+PYR1-comparison.png` and
`pair-table-Series013-thumbnail.png` in `validation/screenshots/`.
The original investigation's ICS comparison remains recorded separately:
three companion intensity images matched exactly within the exported bin
extent, while LACT+PYR1 sequence 2 had a seven-count converter discrepancy.
Its full PTU arrival histogram matches exactly. No supplied reference data
were edited to remove that discrepancy.
