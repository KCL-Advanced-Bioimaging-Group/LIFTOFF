# Channel hover and multichannel mosaic checks

Implemented in the source version on 19 October 2026. Standalone executables
and the supplied example LIF files were not changed.

## Changes

Side-by-side comparisons keep a histogram cube for each recorded channel and
leave the single-channel cube empty. The pixel-hover handler previously
stopped at that empty cube. It now reads the per-channel cubes and maps the
cursor to the corresponding image pixel. If channel image sizes differ, it
maps pixel centres by their relative position within the image.

For mosaics, matching channels show the pixel from the same spatial tile.
Other tiles retain their all-pixel curves when graphs are separated. The
combined view shows one pixel curve per selected excitation/emission pair.
Headers, gaps, margins and leaving the canvas restore the all-pixel data.
Activated ROIs continue to take priority over transient pixel inspection.

Two additional issues appeared during the synthetic mosaic checks:

- Retained ROIs could shift when channel selection changed the height of
  tile headings. Retention now maps image areas and annotation areas
  separately, preserving the selected pixels across those layout changes.
- An ROI spanning tiles was only partially mirrored into other channels.
  Every intersected tile piece is now mirrored to its matching tile in each
  other channel. ROI union histograms count overlapping pixels once.

These changes use channel identities and recorded tile geometry, without
special handling for `R1 (4)`, a particular grid size or a particular file.

## Synthetic acquisition model

`tests/multichannel_mosaic_fixture.py` writes actual binary LIF containers,
LMSRAW photon words, line/frame offset tables, linked float intensity planes
and XML metadata. The fixture combines Navigator tile geometry and snake
stage order with the sequential acquisition structures in the supplied
examples. Photon arrival values are invented, with spatial, tile, detector,
sequence, time and Z variation. Expected arrays are calculated directly from
those invented arrival cycles, independently of the application decoder.

The model includes:

- Two excitation sources: WLL at 555 nm and MP at 740 nm.
- Two detectors per source, with four distinct emission bands.
- Two independent native clocks: about 96.97 ps and 200 ps per bin.
- Two time points, two Z planes, independent stage positions, and unequal
  frame/line repetitions between sequences.
- Both sequential frame and sequential stack storage orders. Linked
  intensity storage remains channel-fast in both cases, testing its
  independence from photon row order.
- Both 2-by-2 and 3-by-2 grids; the existing mosaic suite additionally covers
  a 1-by-3 grid and orientation flags.

Reusable 96-by-64-pixel examples and expected photon-count manifests are in
`validation/multichannel-mosaic/README.md`.
Their pixels represent synthetic test patterns, not biological measurements.

## Verification

The following checks completed successfully:

| Check | Result |
| --- | --- |
| Wider suite excluding optional real-data cases | 234 passed |
| Final focused Qt viewer suite, including the added channel-control case | 14 passed |
| Actual `paneth_ctx555_1` channel hover and actual `R1 (4)` mosaic hover | 2 passed |
| Larger retained synthetic example | All 16 displayed tile/channel arrays matched the oracle; both graph views and hover rendered |
| Required formatting, lint and type checks | Passed; Pylint 10.00/10, no type diagnostics |

The focused viewer cases overlap with the wider suite; these counts should
not be added together. Logs and JUnit reports are under `validation/` with
the `multichannel-` prefix.

The scientific tests compare every pixel and arrival bin in every channel,
tile, time point and Z plane. They exercise both native and Python decoding,
all three photon selections, per-plane and summed-overview decoding, and
linked intensity ownership. Each export case writes 64 ICS files and 64 PTU
files, reads them independently, checks their tile identities and compares
the photon distributions against the expected data. ICS and PTU time axes
are checked against each other using the relevant sequence's native clock.

Qt tests send real mouse events through the production image coordinate
mapping. They cover both graph modes; all displayed channels and tiles;
headers, margins, leaving the canvas, zoom and pan; T/Z navigation; source
and emission checkboxes; deselecting and restoring channels; active ROI
priority; overlapping ROI unions; and ROI retention across heading changes
for single-tile, horizontal, vertical and whole-matrix regions.

A real multichannel Navigator acquisition was not available. These checks
validate the supported combinations of known storage structures; a new LasX
storage variant still needs validation against an actual acquisition.
