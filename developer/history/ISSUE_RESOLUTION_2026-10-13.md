# Source fixes: detector metadata and timelapse preview

Changes are confined to the source tree, now `LIFTOFF_Source`. Release folders and
the supplied LIF/PTU files were read for validation and were not modified.
The source application retains version 2.4.0; restart it to load these fixes.

## Causes and changes

The core decoder could already read both supplied acquisitions. The GUI
stopped before starting its decode worker: the channel summary formatted
`total_photons=None` as an integer. That optional count is derived from a
linked intensity preview, and these examples have 16-bit floating-point
previews that the preview reader did not recognise. Series011's
preview also contains only 19 planes, while its photon stream indexes 20
timepoints. Missing preview counts now display as unavailable, and decoding
continues directly from the photon stream. A decoding failure also clears
the failed channel's previous valid count and displays its actual error.

Compressed blocks containing `RawData` metadata were excluded from the
detector lookup. Both No 2 acquisitions identify **HyD S 2**, excitation
**488 nm**, detector identifier **2**, and emission **496–802 nm**. The
catalogue now reads these records for compressed blocks as well as LMSRAW.
Channel references are followed by sequence and detector index, so two
sequential channels can each use detector index zero without losing the
second channel's identity.

Excitation comes from the detector's positive wavelength, or from active
laser settings associated with that detector in the same acquisition.
Enabled sequential settings take precedence over saved configurations.
Unavailable excitation remains explicitly unavailable. The left-hand list
uses the requested order, for example:

`Channel 1 | Ex. 488 nm / Em. 496 - 802 nm (HyD S 2)`

Rows wrap and grow with their text, including when a thumbnail reduces the
available width. Tooltips also include excitation.

## Validation

- **24 real-data regressions:** both No 2 images open through real GUI
  workers; timepoint changes replace Series011's image; newly exported
  PTUs match the LAS X photon totals and every native arrival bin for all
  20 timepoints and No 2 Image002.
- **59 functional regressions:** metadata scoping, sequential references,
  requested labels, missing-count failure handling, GUI navigation,
  cancellation, photon selection, and export safeguards.
- **5 catalogue regressions:** all 37 datasets in the retained reference
  files, including calibration, dimensions, repetitions and row indexes.
- **21 complete reference-cube comparisons:** representative compressed
  and LMSRAW acquisitions, including first/last Z planes, at 1, 4 and 16
  threads. Every pixel/bin hash and recorded photon histogram agrees with
  retained scientific evidence.
- Ruff formatting/lint, Pylint, and Pyrefly pass with no diagnostics.

The supplied `No 2.ptu` corresponds to **Image002**: both contain
**25,351,913 photons**, with identical native arrival distributions.
Image001 decodes to 25,200,733 photons. Series011 t001 contains 3,322,662
photons and t020 contains 2,572,824 photons, matching their LAS X exports.
Its existing frame table describes 40,841 of 40,960 nominal repeated rows;
the final partial frame is decoded from its actual indexed range.

The same detector correction also recovers metadata for five compressed
PL109 blocks. Their corrected names/bands are recorded separately in
`tests/fixtures/catalogue_metadata_corrections.json`; the original scientific
reference hashes and photon counts remain unchanged.

The complete historical export/thread matrix was not repeated to completion;
the checks above cover the changed paths and supplied examples.

Evidence: `validation/problem-data.xml`,
`validation/issues-functional.xml`,
`validation/issues-reference-metadata.xml`,
`validation/issues-reference-cubes.xml`,
`validation/issues-problem-gui.xml`,
`validation/issues-quality.log`.

## Follow-up: missing thumbnails

The source catalogue now reads previews marked by Leica's `F16` attachment
as little-endian half floats, using the declared channel offsets and
dimension byte strides. It sums the available preview planes and generates
the thumbnail immediately during indexing. Both No 2 images now have visible
thumbnails before selection; Series011's partial intensity preview also
produces a thumbnail.

These previews supply display images only. Their lossy values and potentially
partial frame coverage are kept separate from exact photon counts and
spatial calibration. No 2 still decodes to 25,200,733 and 25,351,913 photons.

Follow-up validation: 69 functional tests, 5 reference catalogue tests and
3 real GUI tests pass, with no quality diagnostics. Ten of the functional
tests specifically cover F16 byte strides, interleaved channels and invalid
preview metadata. Evidence: `validation/float16-preview.xml`,
`validation/float16-functional.xml`,
`validation/float16-catalogue.xml`,
`validation/float16-quality.log`.

No 2 thumbnails restored (`validation/screenshots/float16-No2-thumbnails.png`)

## Follow-up: excitation source names

Excitation labels now include the source from the active detector's scan
settings. Each active `LaserLineSetting` is associated with its enclosing
`Aotf.LightSourceName`, then resolved to the matching `Laser.LaserName`.
The metadata identifies WLL for both No 2 images and MP2 for the supplied
HCC examples. Saved or disabled scan settings do not override the active
source. A source name is omitted when the metadata cannot establish it.

Example: `Ex. 488 nm (WLL) / Em. 496 - 802 nm (HyD S 2)`.

Validation: 71 functional tests, 3 real GUI tests and 5 reference catalogue
tests pass. Quality checks pass with no diagnostics. Evidence:
`validation/excitation-source-functional.xml`,
`validation/excitation-source-gui.xml`,
`validation/excitation-source-catalogue.xml`,
`validation/excitation-source-quality.log`.

Excitation source displayed (`validation/screenshots/excitation-source-No2.png`)

No 2 Image002 ready (`validation/screenshots/issues-fixed-Image002.png`)

Series011 t020 ready (`validation/screenshots/issues-fixed-Series011.png`)
