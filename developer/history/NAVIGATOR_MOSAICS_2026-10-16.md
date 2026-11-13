# LAS X Navigator mosaics: investigation and source implementation

Investigated on 16 October 2026 using
`HCC1954 mS3-mitoPyr-ShadowR.lif`, acquisition **R1 (4)**, from the supplied
example-data directory. Changes are confined to the source version of Leica
Interrogator. No standalone executable was rebuilt or modified.

## Why the acquisition failed

The photon data are LMSRAW PulseVersion2 in `MemBlock_532`. LAS X records
four **stage positions**, identified by an `S` dimension of size 4. The existing
interpretation accounted for time and depth but omitted this stage dimension.
It therefore expected one tile's rows and could not reconcile the much larger
line index with the declared image dimensions.

The apparent four-frame stack is the four tile planes. Each plane contains
120 repeated frame scans of its own position. The complete interpretation is:

| Field | Recorded value |
|---|---|
| Tile resolution | 1024 × 1024 pixels |
| Stage positions, S | 4 |
| Time points, T | 1 |
| Depth planes, Z | 1 |
| Frame repetitions per tile | 120 |
| Line repetitions | 1 |
| Encoded rows per tile | 122,880 |
| Encoded rows in the acquisition | 491,520 |
| Detector | HyD X 3 |
| Excitation / emission labels | 561 nm (WLL) / 580–700 nm |

Thus `4 × 120 × 1024 = 491,520` rows, rather than the 122,880 rows expected
when the stage dimension was omitted. The four cumulative `FrameOffsets`
entries are 122,880; 245,760; 368,640; and 491,520. They bound the four tile
planes, including all repeated scans within each plane.

## Recovering the matrix and pixel orientation

The acquisition's `TileScanInfo` attachment supplies `FieldX`, `FieldY` and
`PosX/Y/Z` for each tile. The photon element also records `StagePositions` in
storage order. Matching these coordinates connects each photon plane with its
recorded matrix cell, without assuming that attachment order is storage order.

For this example, the storage and display orders differ:

| Storage plane, zero based | Display row, column, one based | Stage X, Y (metres) |
|---|---|---|
| 0 | 1, 1 | 0.0618671298, 0.0466582286 |
| 1 | 1, 2 | 0.0624309423, 0.0466582286 |
| 2 | 2, 2 | 0.0624309423, 0.0472220411 |
| 3 | 2, 1 | 0.0618671298, 0.0472220411 |

The viewer therefore places storage planes as `[0, 1]` above `[3, 2]`.
TileScanInfo flip and swap flags affect matrix placement. They are handled
separately from each tile's pixel orientation.

The linked intensity block, `MemBlock_533`, contains four float32 planes. Its
`DimensionDescription` with `DimID=10` confirms the four stage positions and
the 4,194,304-byte plane stride. Each photon tile is compared with its own
intensity reference. All four comparisons confirm a clockwise quarter-turn,
consistent with the raw `SwapImageXY` and `InvertImageY` flags. Correlations
range from 0.999632 to 0.999853.

The original per-tile pixel size is retained. The stage spacing is smaller
than the tile field of view, so the acquisition includes overlap. The viewer
shows separate tile images with labelled cells and small gaps; it does not
blend overlap, resample pixels or claim a continuous stitched calibration.

## Application behavior

- The catalogue retains S independently of T and Z, and validates tile geometry
  against stage positions and frame/line indexes.
- Selecting R1 (4) decodes all four tiles and shows a **2 × 2 matrix**, with
  each tile retaining its original 1024 × 1024 photon histogram array.
- The default photon-arrival graph pools the entire mosaic. The checkable
  **Separate graphs by tile** button beside **Combine all ROIs** restores
  individual tile graphs immediately, without decoding again. Each selected
  detector/excitation pair keeps its own graph and timing calibration.
  Pixel inspection and ROIs use each tile's counts. Regions crossing cell
  boundaries use the intersected pixels in each tile. Combining ROIs counts
  shared pixels once. Comparing detectors mirrors regions only between
  matching spatial tiles.
- Acquisitions with additional time or depth dimensions keep a T/Z selector.
  The matrix remains a matrix when T/Z or the photon selection changes.
  Multiple selected detector/excitation pairs have separate matrices.
- Overview intensity images also keep tiles in separate cells; only T/Z
  planes belonging to the same position are summed.
- Native preview arrays are narrowed from uint32 to uint16 only when every
  value fits exactly. This reduces this example's four native-bin cubes from
  about 2.2 GB to about 1.1 GB without losing counts.

Incomplete or ambiguous grids, unmatched/duplicated stage positions, invalid
orientation flags and inconsistent frame indexes remain explicit failures.
The app does not guess a square grid from an arbitrary four-plane stack.
This implementation targets rectangular Navigator grids with validated
metadata; incomplete or irregular mosaics are not inferred into rectangles.

## Exports and provenance

Split ICS and PTU exports keep each tile separate, with filename suffixes such
as `tile_r01_c01` and `tile_r02_c02`, followed by T/Z identifiers where needed.
ICS files retain each tile's original spatial dimensions and calibration.
The JSON sidecars of both formats contain the same `mosaic` object: grid size,
tile identity, source fields, flip/swap flags and recorded stage coordinates.
The original photon row ranges and repetition information are retained.

The ICS integration option is unavailable for mosaic acquisitions, with a
message explaining that split export keeps different positions separate.
Direct export/decoding calls also reject summing a whole mosaic into one
tile-sized cube. This avoids superimposing unrelated spatial locations.

## Verification and limits

The full acquisition was decoded through the production viewer workers and
all four full-resolution tile cubes were exported to ICS and independently
read back. Decoded All Photons totals, in display order, are:

| Cell | Selected photons | Linked intensity total |
|---|---:|---:|
| Row 1, column 1 | 9,167,961 | 9,264,569 |
| Row 1, column 2 | 16,303,227 | 16,793,578 |
| Row 2, column 1 | 12,144,951 | 12,293,001 |
| Row 2, column 2 | 10,354,944 | 10,420,569 |
| Total | 47,971,083 | 48,771,717 |

Exported counts match the decoded cubes. A separate vectorized audit of the
entire indexed photon payload also reproduces all four native decoder totals
exactly. Before the existing photon-validity filter, the in-image stream
contains 48,793,429 records. The All Photons rule retains first-flag photons
and subsequent photons meeting the detector dead-time threshold: 13 native
bins, derived from the recorded 1.3 ns dead time and native clock. It removes
822,346 records in this acquisition. This selection rule was preserved.

LAS X's stored intensity total is separately 21,712 below that unfiltered
in-image stream. Its exact counting rule has not been established here. The
difference between intensity and selected photons is retained rather than
normalized away. No companion LAS X PTU was supplied for this mosaic, so
these checks do not establish LAS X PTU equivalence for this acquisition.
Full audit counts are in `validation/mosaic-unfiltered-audit.json`.

Native and Python decoding agree for every pixel and bin in sampled rows from
each real tile in all three photon selections. Synthetic fixtures additionally
check every pixel/bin for 2 × 2, 3 × 2 and 1 × 3 grids with independent T/Z and
two detector channels. Tests cover all eight grid flip/swap combinations,
malformed metadata, overlapping frame ranges, ROI retention, same-position
detector comparisons, split-export recovery after integration is declined,
and independent ICS/PTU counts and arrival bins in all selections.

Validation records are in `validation/mosaic-functional.xml`,
`validation/mosaic-integration.xml` and `validation/mosaic-quality.log`.
The final runs passed 153 functional tests and 15 real-data integration checks;
formatting, lint, Pylint and type checks all passed without diagnostics.
The viewer capture is `validation/screenshots/mosaic-R1-4.png`.
The alternative graph view is
`validation/screenshots/mosaic-R1-4-separate-graphs.png`. Graph-toggle
regressions are recorded in `validation/mosaic-graphs-gui.xml`; they check
pooled arrival bins, actual one/four-graph rendering, ROI unions and independent
detector comparisons. Presentation pooling does not superimpose images or
change export behavior.

The subsequent hover correction restores the all-pixel view when the cursor
enters the outer canvas margin or leaves the canvas. Previously, the margin
sent no end-of-hover notification and the leave handler required a single
histogram cube, which mosaics do not use. Both paths now use an explicit
hover-end signal. In separate mode, tiles not under pixel inspection retain
their own all-pixel curves. Combined mode still inspects only the hovered
pixel, then returns to the full mosaic on hover end. Active ROI curves are
preserved. Canvas-event regressions cover margins, headings, leave events,
both graph modes and all three photon selections, including the supplied
R1 (4) acquisition in Single-event mode. Records are in
`validation/mosaic-hover-gui.xml`, `validation/mosaic-hover-functional.xml`
and `validation/mosaic-hover-quality.log`.

Restart the source application before opening the example to load these
changes. This work does not update an already running process or the separate
standalone distributions.
