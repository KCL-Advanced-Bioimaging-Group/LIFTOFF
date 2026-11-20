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

ICS numeric choices are powers of two from 16 through 32768. The full-resolution
native window N is the nearest power of two to `1 / (selected_rate * clock)`;
absolute distance in native bins determines the result, with halfway ties
choosing the smaller power. A missing/invalid selected setting uses the actual
recorded detector/sequence rate as an explicitly labelled fallback. The numeric
grid metadata records that rate's value, units, source and role. Windows above
32768 native increments are rejected; windows below 16 permit Native timing only.

Numeric exports retain native indices 0 through N-1. N output bins preserve
the full-precision recorded clock width. Smaller counts sum adjacent groups
of `N / output_bins`, with widths equal to that integer times the clock.
Assignment uses integer division, avoiding floating-point boundary drift.
All numeric choices share `[0, N * clock)`. Arrivals at index N and above
are excluded and counted, never clipped into the final bin. The same integer
lookup feeds native and Python decoders. Output counts above N are rejected.
For the supplied clock, selected 80/40/20/10 MHz gives N=128/256/512/1024.

The GUI defaults to N and labels it with the rate, e.g. `256 (default for 40MHz)`.
Options above N remain visible but disabled. A batch uses the smallest N among
checked outputs, or all loaded datasets before any are checked. The automatic
default follows changes in that selection; explicit valid downsampling/Native
choices persist. Both GUI defaults and numeric windows use the actual rate
when the selected rate is unavailable. The dropdown tooltip and numeric grid
metadata identify the fallback. The API's explicit bin count is validated
per dataset; Native timing remains `bins=None`.
Native timing retains the preview grid described above. PTU preserves native
arrivals, allowing independent reconciliation of included/excluded counts.

The info panel's repetition rate separates the selected WLL pulse-picker
setting from the actual recorded detector/sequence LaserPulseFrequency. The
selected setting comes from the matched source's PulsePickerRatio (MHz) in
the enabled detector/sequence settings, with the same acquisition/master
inheritance restrictions as other acquisition settings. Invalid or ambiguous
settings remain unavailable; an MP detector never borrows a WLL setting. The
selected rate or explicit actual-rate fallback defines the numeric window.
The recorded clock and source calibration are never rewritten.

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

The optional **Filter reflection** preview treatment affects native bin
centres in the inclusive interval `[lower, upper]`. **Assign to NaNs** stores
missing samples rather than zeros. The other two modes are **Interpolate
values (smooth)** and **Simulate photon counts from interpolation**. They
share the whole-image log-linear endpoint bridge for the corresponding decoded
detector/ tile and T/Z view or export output. Original decoded cubes are
retained and restored exactly when treatment is disabled.

Let `C[i]` sum all pixels at native bin `i`, `S=ceil(lower)`,
`E=floor(upper)`, `a=S-1`, `b=E+1`, and `t=(i-a)/(b-a)`. For `S..E`, the
expected whole-image counts are `M[i]=exp((1-t)*ln(C[a])+t*ln(C[b]))`. This
joins both exterior count endpoints exactly in log space. Only these two
positive finite samples are required: there is no derivative estimate, extra
exterior stencil, pseudocount or Gaussian smoothing. Missing/non-positive
endpoints leave the interval NaN.

For pixel `p`, let `A_p` sum its native counts outside `S..E`; define
`w_p=A_p/sum(A)`. Smooth replacement is `mu[i,p]=M[i]*w_p`. A pixel with no
exterior counts has zero expected count. The sum recovers the expected whole-
image bridge to floating precision. This is an explicit common decay shape
with spatial allocation, not an independent estimate of each pixel's lifetime.
All exterior samples are unchanged.

Simulation draws `N[i,p] ~ Poisson(mu[i,p])` independently for each native bin
and pixel. It draws replacement counts directly, without adding a second mean
or generating noise at repaint/ROI time. Undefined means stay NaN. Float64
cubes preserve missing samples and hold simulated integer counts exactly in
the supported count range. Image projections, pixel/ROI curves and mosaic
graph sums read the same derived cube. Smooth interpolation has a dashed graph
overlay. Simulation shows one unconnected dot per simulated native-bin count,
using the same axis mapping and series colour as the retained measured curve.

Each committed reflection scope retains a random unsigned 64-bit base seed.
Mode/toggle changes and boundary edits preserve it. For sampling, SHA256
hashes versioned canonical JSON containing that seed, dataset key, plane seed
index, event mask, exact float native boundaries and spatial shape. The first
eight digest bytes, interpreted little endian, seed NumPy PCG64. A single
generator samples ascending native bins and C-order spatial pixels. Thread
count, panel order, compression and output rebinning never enter the seed.
Plane None and plane zero share seed index zero so single-plane overviews
replay in split exports; other plane indices give distinct streams. Integrated
and split data can have different means. Base and realization seeds are stored
as decimal strings to avoid JSON integer precision loss. Metadata records the
algorithm version, generator, NumPy version, sample order and complete seed
context.

Every pixel, ROI, tile and all-pixel graph reads the same derived cube. Mosaic
graphs pool repaired tile cubes. Missing endpoints propagate NaNs through
spatial sums; image projections sum finite contributions. Bounds, mode, base
seed and toggle persist per detector/T/Z view while loaded. Disabling
treatment restores raw counts and the prior image. Boundaries stay locked
while enabled.

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
covering both the native preview interval and requested output window. It
repairs pixels using the saved mode before assigning samples to the physical
output grid. Filtered ICS stores finite integral samples in exact unsigned
16-/32-bit form when possible, including simulated counts. Missing or
fractional samples use IEEE real/signed float32. Integer-valued samples and
NaNs are preserved exactly; fractional estimates undergo float32 rounding.
If float32 would change integer counts, overflow finite values or turn a
nonzero into zero, the entire output retains float64. Embedded metadata and
sidecars record the selected dtype, precision policy and maximum absolute
rounding error. Internal calculations and previews remain float64. Grouped
bins propagate native NaNs. The
legacy programmatic `exclude` mode retains integer photon-exclusion behavior.
Cached original cubes stay intact, and derived caches are rejected. Memory
estimates include native decoding, repair, output and grouping buffers.

PTU removes matching arrivals after event selection, before record encoding,
regardless of the selected NaN/smooth/simulation mode. The dialog, embedded
metadata and sidecars explain that PTU cannot represent NaNs or interpolated
counts. Empty logical lines retain scan markers, and kept events preserve
native microtimes and detector routes. Raster timing is unchanged.

ICS accounting separates retained measured photons, removed measured
reflection photons, and measured photons outside the time window. Their sum
equals the selected measured events before treatment. Reflection removal takes
precedence where native samples also lie outside a numeric ICS window.
Synthetic expected and simulated count totals and missing sample counts are
reported separately; replacements are never labelled as measured/exported
photon events. Embedded ICS and JSON metadata identify synthetic native
centres and affected output-bin indices, all spatial pixels, method and replay
seeds. CSV/HTML summaries expose the same provenance. PTU metadata
distinguishes the requested mode from applied event exclusion and never claims
synthetic counts. Exported sample totals may therefore differ from measured
photon accounting.

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

ICS v2 headers retain sample size, little-endian representation, payload
compression, axes `bits,y,x,t`, pixel calibration in metres, and arrival-bin
calibration in seconds in both parameter and history fields. Native 16-/32-bit counts, gzip/uncompressed payloads,
non-square orientation and native and 16-/32-/64-/128-bin exports are read back
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
