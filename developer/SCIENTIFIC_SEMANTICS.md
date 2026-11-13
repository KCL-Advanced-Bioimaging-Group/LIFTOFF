# Scientific and export contracts

## Optical metadata and wavelength precision

All light sources use the same emission lookup: the selected acquisition and
sequence, matched to the detector's `Channel` identifier in `MultiBand`.
`TargetWaveLengthBegin` / `TargetWaveLengthEnd` are the preferred complete pair.
If a complete pair is absent, `LeftWorld` / `RightWorld` are the legacy pair.
Endpoints from different pairs are never combined. Non-finite, non-positive,
reversed or conflicting bounds remain unavailable.

The enabled detector setting takes priority over saved settings. Older
single-sequence files can omit the band from that setting; only in that case,
the same detector's band is inherited from `LDM_Block_Sequential_Master`.
A malformed band is not replaced by an inherited band, and another sequence's
settings cannot supply a missing band. The source scope, setting name and XML
attribute names are retained with the values.

Excitation and emission wavelength labels use whole nanometres, rounded to
nearest with half values up. Lists, tooltips, selectors, comparison panels,
export selections and generated filename components share this policy.
These are nominal optical settings, following the LAS X display convention
observed in the supplied example; they do not assert a calibrated uncertainty
of 1 nm. Fractional storage digits cannot justify additional display precision.
Photon timing and spatial calibration retain their scientific precision.

Both PTU and ICS JSON sidecars contain the same `opticalMetadata` object.
It separates nominal labels/bounds from unrounded numeric source values.
Emission `sourceTextBoundsNm` also preserves the exact XML strings, including
digits that a binary floating-point conversion cannot retain. Existing
`sequence.emissionBand` and channel-name fields hold the nominal label.
The original LIF and photon data are never rounded or rewritten.

## Photon selection

`event_flags.py` defines the three supported selections. `photon_selection.py`
centralizes normalization, metadata, raw-channel extraction and selection for
both histograms and PTU output. Compressed marker masks are 7 / 3 / 1 for All /
First / Single Photons; LMSRAW selectors use 256 / 512 / 1024. Public masks and
callbacks remain compatible with the accepted application.

For LMSRAW First/Single selection, every photon in the requested detector route
updates predecessor state, including photons rejected by the selector. The
dead-time threshold is the integer floor of detector dead time / native clock
period with the established floating-point tolerance. The first photon is
handled explicitly. State crosses row/batch boundaries and resets at the plane
boundary. Single selection retains photons only when their cycle is completed
and contains exactly one qualifying photon; an unclosed terminal singleton is
not invented. Python and native implementations agree across the tested modes
and representative thread counts.

## Preview, binning and alignment

Recorded detector/sequence timing is resolved through `timing.py`, with units,
source scope and evidence quality. Previews retain the native arrival increment
and use `ceil(laser_period / clock)` complete native bins. This includes 133 bins
at 78.02 MHz and 129 at 80 MHz for the supplied 96.9697 ps clock. A native index
maps directly to its corresponding native bin. The final bin retains its full
clock width, so its upper edge can extend beyond the laser period.

ICS numeric choices explicitly rebin one unrounded recorded laser period.
Physical half-open boundaries `[i * step, (i + 1) * step)` determine assignment.
The same boundary lookup feeds native and Python decoders; arrivals outside the
window are excluded and counted, never clipped into the final bin. PTU preserves
those arrivals, allowing independent reconciliation of included/excluded counts.

A cached cube is reused only for matching dataset/plane, photon selection,
clock, window, and exactly aligned grouping boundaries. Legacy cubes without a
physical grid cannot be reused for calibrated exports. The optional uncalibrated
low-level decoder contract remains available for historical regression evidence;
the GUI and calibrated exports explicitly request the physical timing grid.

Histogram accumulation checks uint16 promotion and uint32 overflow before
publishing counts. Summaries and ROI accumulation use uint64. The spatial
alignment safeguard compares the eight square-image transforms with the linked
intensity reference, requires strong correlation and error reduction, and rejects
ambiguous improvements. A partial/incomplete reference does not force an
unverified orientation. Sidecars distinguish confirmed alignment from inferred
axis order; golden tests compare the entire spatial histogram array, not only
its sum.

Reflection intervals are initially visual annotations. Detection uses the sum over
all spatial pixels of each recorded channel, irrespective of the pixel or ROI
currently displayed, using a separate floating-point array. Mosaics pool all
tiles of that channel. The resulting interval, including manual adjustments,
is shared by the corresponding all-pixel, pixel, ROI and separate tile views.
Gaussian smoothing of `log10(counts)` uses sigma `max(1, native_bins / 256)`
bins, truncated at three smoothing sigmas. Central differences give the first
derivative and, by applying the same difference operator again, the second.
Zero-count bins are log-undefined: complete stencils touching zeros, gaps or
the array edges are excluded without adding pseudocounts. The initial main
peak and its derivative stencil are excluded from the search.

Neighbouring positive local maxima of the second derivative must each exceed
three propagated noise standard deviations. Unsupported curvature peaks are
not skipped to pair distant features. Between them, the first derivative
must have a positive maximum followed by a minimum. The positive maximum must
exceed zero by three standard deviations, and the two extrema must lie at least
three standard deviations above and below the local decay trend, respectively.
That trend is the chord slope between smoothed log counts at the candidate
shoulders. The boundaries are those second-derivative maxima. Select the
complete pattern with the strongest weakest feature in units of noise.
There are no relative-height or percentage-based boundary cutoffs.

Log-count variance uses the delta-method Poisson estimate
`1 / (ln(10)^2 * counts)`. A robust normalized second-difference estimate of
log counts inflates this variance for measured excess noise above the Poisson
floor. Centered MAD uses the standard Gaussian consistency factor, so a smooth
exponential decay is not mistaken for excess noise in the raw count curvature.
Only positive post-main-peak count triples enter that estimate. Uncertainties
are propagated using the complete convolution stencils; shared weights are
combined before squaring for derivative-minus-trend contrasts. This retains
the covariance introduced by smoothing, successive differences and trend
estimation, without constructing a dense covariance matrix.

The default three-standard-deviation threshold is a per-feature requirement,
not a calibrated overall false-positive probability across a searched curve.
The noise estimate assumes independent bins before processing, apart from the
estimated scalar variance inflation. Curvature shoulders depend on smoothing
and do not necessarily enclose every reflected photon. Black boundaries remain
manually adjustable in native bin coordinates. Neither smoothing nor these
intervals alone modify count arrays, cached cubes, event selections, timing
grids, or exports.

Manual placement uses the same native-bin coordinate mapping and shared
intervals as automatic detection. The first click is an unshaded single-line
preview; a second click on the same recorded channel commits the two sorted
positions, separated by at least one bin. Either click order is accepted.
Matching mosaic tile graphs share that channel's interval. Cancelling a
partial placement restores any previously committed boundaries. The pointer
prompt and manual state are cleared on completion, cancellation, loading a new
preview, or hiding the graph. Manual placement has no effect on photon data.

The optional **Filter reflection photons** preview filter excludes native bin
centres in the inclusive interval `[lower, upper]`, including fractional
boundary positions without rounding to the nearest bin. Retained bin counts
are summed per pixel in uint64 and rendered with the usual preview contrast.
The same interval is omitted from every corresponding graph, with a white gap
and no connecting curve. Each channel uses its own bounds; mosaic tiles share
their channel's bounds. Filtering is applied after the current event selection.
Decoded cubes, original histogram vectors, timing and exports remain intact.
Unchecking restores the exact prior image and the original curves. Boundaries
are locked while filtering and can be adjusted after unchecking. The workspace
remembers committed intervals and the preview toggle for each detector and T/Z
view while its source is loaded. Returning to that view restores its settings.

ICS and PTU exports provide an independent, initially unchecked reflection
exclusion option. They snapshot saved native-bin boundaries across the loaded
datasets. Individual T/Z previews cover that T/Z position across matching
mosaic tiles. A saved summed overview interval covers all planes of its
detector. For split outputs, a saved interval for the individual T/Z position
takes precedence over the overview interval. Filtering an integrated output
requires a single interval covering the full output. When the export option is
checked, each output with a matching interval uses it. Outputs without a
matching interval skip reflection filtering.

ICS first obtains calibrated native counts with the requested event selection,
retaining the usual spatial alignment. It excludes native bin centres in the
inclusive reflection interval before assigning retained arrivals to the chosen
physical output grid. Rebinning may therefore combine retained bins on either
side without deleting unrelated photons. Cached preview cubes remain intact;
already reflection-filtered caches are rejected. Native and output arrays are
included in the filtered export's peak-memory estimate.

PTU removes matching arrivals after event selection, before record encoding.
Empty logical lines still emit scan markers. Kept arrivals retain their native
microtimes and detector routes; raster timing is unchanged. JSON sidecars
record boundaries and excluded counts. ICS accounting separates exported,
reflection-excluded and outside-window photons, whose sum equals selected
photons before reflection filtering. Reflection exclusion takes precedence
where an excluded native arrival also lies outside a rebinned ICS window.

## Indexes and incomplete acquisitions

Navigator mosaics retain Leica's S (stage-position) dimension independently
of T and Z. TileScanInfo fields are matched to the raw stage positions;
frame offsets must bound the complete tile planes, including repetitions.
Each tile has its own intensity reference, orientation check and histogram
cube. The viewer arranges these in a recorded rectangular grid without
stitching or resampling. Overlap and stage coordinates remain explicit.

Overview images sum only T/Z at each position. Split ICS/PTU outputs name
each tile by row/column and retain the common `mosaic` provenance object in
their JSON sidecars. Whole-mosaic integration into a tile-sized cube is
rejected. Missing, ambiguous or inconsistent geometry/indexes are reported
as failures, with no inferred square layout. See
[the Navigator investigation](history/NAVIGATOR_MOSAICS_2026-10-16.md).

LIF indexing validates block extents, dimensional metadata, row tables, and
per-plane ranges. Raw readers do not treat nominal repetitions as permission to
read missing bytes. Explicit partial-repeat acquisitions use the retained index
and actual row count. In PTU output the logical line count is derived from those
indexed rows and line repetitions, including a final partial repeated line.
Missing frames/rows are never synthesized as photons. ICS keeps nominal image
dimensions, with counts from the indexed rows only.

Preflight now accepts validated `confirmed (line order inferred)` indexes, and
partial PTU output records `indexedEncodedRows`, `nominalEncodedRows`, and
`indexedFrameCount`. This corrects two reliability gaps encountered while
restoring the accepted partial-index support. The unresolved Autofluorescence
Series006 table cannot be reconciled with its dimensions; preview and both
export preflights continue to report Failed with a reason.

## ICS

Spatial dimension calibration follows Leica's centre-to-centre convention:
`Length / (NumberOfElements - 1)`, with explicit source-unit conversion.
An axis with one sample, missing/unsupported units, or a missing, non-positive
or non-finite spacing has no physical calibration. Explicit LMSRAW voxel sizes
retain their recorded increment. ICS writes an uncalibrated X/Y axis as scale
`1` with unit `pixel`, in both parameter and history fields. Mixed calibrated
and uncalibrated axes are supported independently. No metric value or NaN is
fabricated. The metric JSON value is `null`, with status `unavailable`.

Every batch ICS/PTU output embeds a versioned `acquisitionMetadata` summary:
source identity, acquisition/channel/detector names, excitation and emission,
dimensions, selected/integrated T/Z identity, available X/Y/Z calibration,
sequence, tile position, scan timing, photon selection and reflection filtering.
The matching JSON stores the same summary, plus detailed export provenance,
original spatial source strings and dimension records, and the original
acquisition XML element (including trailing settings). A truncated source
element can remain an XML fragment; it is preserved without repair. Unvalidated
timestamp lists remain in the detailed timing metadata, not the compact header.

ICS uses readable `history Leica_*` records and a complete ASCII-escaped JSON
summary in ordered `history LeicaMetadata_0000`, `0001`, ... records. Concatenate
their values in numeric order and parse JSON. Metadata history records use at
most 220 ASCII bytes per line, including the newline, for TRI2 3.0 compatibility.
Long names remain intact in the structured summary.
PTU stores the same summary in the `Leica_Acquisition` string tag, with readable
`Leica_*` scalar tags alongside it. Generic readers can retain these extension
fields without necessarily mapping them into their own acquisition models.

Defined ICS optical fields now include `sensor s_params Channels` (one),
`Description`, `DetectorModel` and, when there is one excitation wavelength,
`LambdaEx` in nominal whole nanometres with state `reported`. `LambdaEm` is
written only when the recorded emission bounds describe a single wavelength;
a finite-width emission band is never collapsed to its midpoint. Multiple
excitation wavelengths never create extra detector channels or an arbitrary
single excitation value. Conventional history fields carry `title`, `detector`
and `filterset emm name`. Control characters are removed from conventional
text fields; Unicode is escaped for the ASCII header, while full original
strings remain in structured metadata and reports. Long strings exceeding
the conventional field limits remain in the structured metadata.

PTU retains defined image, microtime, sync and scan-marker tags. Its standard
`File_Comment` now carries acquisition, detector, optical and T/Z identity,
per-axis calibration status, recorded laser rate/dwell, and the explicit
synthetic/reconstructed macrotime interpretation. No PicoQuant hardware or
wavelength tag with an unverified meaning is invented. Each format's JSON
summary includes `headerMappings`, describing the chosen conventional fields
and limitations. These are format-level encodings; testing in the actual
analysis packages is a separate, pending validation step.

Successful batch exports produce JSON, UTF-8-BOM CSV and self-contained HTML
companions. Reports are derived from the same sidecar object; they separate
native arrival timing, output histogram timing, recorded scan periods and
generated PTU raster spacing. They include photon accounting, filter settings,
plane identity, spatial/optical settings, source revision and original
calibration values. CSV source labels resembling formulas are escaped as text;
HTML escapes source values and uses no scripts or remote resources.
All companions are staged before publication. Report generation/publication
failure removes the current output bundle and temporaries, while completed
batch entries remain valid. Naming checks reserve the data and all companion
paths, including `.part` files, to preserve existing provenance and reports.

Encoding references: [libics field definitions](https://github.com/svi-opensource/libics/blob/master/libics_data.c),
[libics wavelength units](https://github.com/svi-opensource/libics/blob/master/libics.h),
[Bio-Formats ICS reader conventions](https://github.com/ome/bioformats/blob/develop/components/formats-bsd/src/loci/formats/in/ICSReader.java),
and [PicoQuant tag dictionary](https://github.com/PicoQuant/PicoQuant-Time-Tagged-File-Format-Demos/blob/master/doc/apx_tagdictionary.html).

ICS v2 headers retain integer size, little-endian representation, payload
compression, axes `bits,y,x,t`, pixel calibration in metres, and arrival-bin
calibration in seconds in both parameter and history fields. Native 16-/32-bit counts, gzip/uncompressed payloads,
non-square orientation and native and 128-/256-bin real exports are independently read back
in tests. Existing naming and plane suffixes are retained. JSON sidecars carry
source identity, detector/filter names, selection, calibration, integer width,
plane ranges, alignment decisions, decoder details and reconstruction provenance.

## PTU

The standard `ImgHdr_PixResol` scalar (micrometres) is emitted only when both
X and Y are calibrated and equal. Unequal or unknown spacings are represented
by the explicit per-axis metre/pixel units, scales and status in `Leica_*`
tags and the embedded/sidecar summary, rather than mislabelling Y with X's
scale. JSON now retains separate X/Y calibration and available Z spacing and
source origin. Physical Z positions are calculated only when both origin and
spacing are known, and only for a selected plane; integration has no single
physical Z position.

The vectorized writer emits Generic T3 records, native decoded Leica arrival
values, detector routes, frame/line markers and monotonic raster macrotime.
Stable pixel/arrival/channel ordering preserves accepted record payloads.
Overflow records are chunked within the record format's count limit and parsed
independently in regression tests. LAS X companion PTUs are independently parsed
as PicoHarp 300 or Generic T3 as appropriate; total photons and every microtime
bin agree for PL109, X03 and Sample2 in all three selections.

PTU macrotime has explicit **Synthetic** or **Reconstructed** quality in the
header, export table and sidecar. Automatic mode reconstructs a nominal raster
only with consistent recorded pixel/line periods, and a recorded frame period
when frame repetitions require it. Accumulated line repeats and incomplete scan
timing force a labelled synthetic raster; explicit reconstruction fails instead
of silently falling back. Absolute nominal pixel-centre and marker positions
are rounded to recorded sync ticks, avoiding cumulative rounding drift.

Neither mode restores the original individual photon hardware timestamps, which
are absent from the supported reduced streams. Each output plane/tile begins at
zero; no inter-file elapsed-time relationship is invented. Recorded dwell,
line/frame timing, repetition identities and original timestamp-list XML
remain in the sidecar even for synthetic output. Original image timestamps are
also decoded from Leica's hexadecimal FILETIME list (or older HighInteger /
LowInteger records), with UTC labels and integer 100 ns precision. Their recorded
span is not treated as a frame period or acquisition duration. Selected-plane
association requires matching detector identity, image dimensions, channel
strides and timestamp count; unsupported or ambiguous associations stay unknown.
These image timestamps do not change PTU raster timing or restore photon times.
The encoding follows the
[Bio-Formats LIF timestamp reader](https://github.com/ome/bioformats/blob/develop/components/formats-gpl/src/loci/formats/in/LIFReader.java)
and the [Microsoft FILETIME definition](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ns-minwinbase-filetime).
Missing/non-finite arrival-clock
or laser-frequency calibration fails calibrated exports instead of assuming an
80 MHz laser or a fabricated arrival clock. Native PTU microtimes are retained,
including arrivals excluded by an ICS time window. Explicit synthetic mode keeps
the accepted photon/marker record payload contract.

The embedded acquisition summary and readable reports also include available
objective, NA, immersion, magnification, zoom, stage coordinates, scan settings,
averaging, accumulation, pinhole settings, acquisition software and selected
detector settings. Active sequential settings take precedence; common microscope
properties may inherit acquisition settings, but another sequence's scan values
are not substituted. Original strings and source paths accompany interpreted
values. A pinhole Airy-calculation wavelength is labelled separately from the
detector emission band, and laser intensity percentages are settings, not measured
specimen power. The current focus Z setting is distinct from a selected plane's Z
position. Raw voxel spacings retain their recorded values; an original image
dimension supplies an origin only when its count, units and spacing match. Child
derived-image metadata cannot supply these values. ICS additionally maps NA to
`sensor s_params NumAperture` and objective details to history records.

Cancellation and exceptions remove the current incomplete output/sidecar,
release prepared readers, and report a distinct cancellation or explicit failure.
Already completed batch outputs remain valid. Qt completion is delivered after
the worker has finished; closing waits for cancellation and thread completion.
