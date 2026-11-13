# Using Leica Image Files Translated into Open File Formats (LIFTOFF) 3.2.2

Open one or more LIF files with **Open LIF files**, drag files into the window, or add
more files to the current session. Acquisitions are grouped under their source
file and related detectors share one acquisition entry. Reopening an already
loaded file does not create duplicates. Use the source-file menu to remove its
data, or the clear control to empty the workspace.

Select an acquisition. For acquisitions with several recorded pairs, use the
**Excitation | Emission** table to choose one or more pairs. Select an excitation
to enable its emission choices, then expand its row to see additional emissions.
The plane selector and previous and next buttons keep the views on the same
T/Z plane. Previews use native timing bins independently of export binning.

Excitation and emission wavelength labels use whole nanometres throughout,
for example **566–630 nm**. PTU and ICS metadata retain the original source
values separately from these nominal labels, with their source fields and
settings, so stored decimal places do not imply optical accuracy.

The three photon selections are **All Photons**, **First Photons**, and
**Single-event Photons**. Changing a selection recalculates the image and graphs.
Details distinguish selected valid photon counts from raw stream counts. A failed
decode is displayed with its reason; no fabricated histogram replaces it.

Drag on an image to draw an ROI. Ctrl-click inside an ROI activates or deactivates
it; overlapping outlines can be activated together. Stable ROI numbers and colors
are retained while navigating and changing the photon filter. Changing detector
selection offers to retain active ROIs. **Combine all ROIs** draws the combined
decay in orange and counts overlapping pixels once. Right-click deletes an
inactive ROI while protecting active ones. **Clear all ROIs** removes all outlines.

Use the checkable **Log scale** button at the top right of the photon-arrival
graphs to change their **Photon counts** y-axis. Checked means logarithmic;
unchecked means linear (the default). It is independent of the intensity
histograms' scale toggle.
The logarithmic view starts at the power-of-ten tick below the lowest positive
count across the curves in each graph (at least one photon) and omits
zero-count bins. Its tick labels use index notation (10, 10², 10³, and so on).
Switching scales changes only the graph display; photon
counts, the **Time bins** x-axis, and exported data remain unchanged.

A single graph has no channel subtitle. When several graphs are displayed,
each has a single-line channel or tile title. **Clear** is immediately to the
right of **Auto-detect reflection peak**, and **Combine all ROIs** is below,
right-aligned with **Clear**.

Click **Auto-detect reflection peak**, below **Log scale**, to mark a late
secondary rise in the decay summed over **all pixels** in the image, even
when a pixel or ROI curve is currently displayed. Each recorded channel uses
its own whole-image decay. Black vertical lines bracket the suggested
reflection interval and the space between them is shaded grey. Drag either
line left or right to adjust the interval; **Clear** removes the markers.
The same boundaries appear on all pixel and ROI views and stay in the same
time bins when switching scales. Mosaic detection pools all tiles for each
recorded channel and shares its boundaries with separate tile graphs.
Loading a new preview clears the markers.

To place boundaries yourself, click **Manually-detect reflection peak**.
A box beside the pointer immediately says **Please drop first boundary**.
Click inside the graph to place a black line. The prompt changes to
**Please drop second boundary**; click again to complete the interval and
shade the space between the lines grey. Choose positions at least one time
bin apart, in either order. Both clicks must belong to the same recorded
channel; matching mosaic tile graphs share the same interval.

Manual boundaries can be dragged and appear on pixel and ROI graphs just
like automatic boundaries. Press **Escape** or click the manual button again
to cancel a partial placement and restore any previous interval. **Clear**
removes the markers and cancels placement. **Auto-detect reflection peak**
switches back to automatic detection.

Detection uses the smoothed logarithmic decay. A rise followed by a fall in
its first derivative identifies a candidate after the main peak. The outer
positive maxima of the second derivative position the two boundaries.
Both the rise-and-fall pattern and the boundary features must exceed three
estimated noise standard deviations; no percentage-of-height cutoff is used.
Weak or ambiguous peaks may produce **No reflection peak detected**. Treat
the suggested interval as a visual aid and adjust it as needed. Detection
and dragging alone do not filter counts.

Check **Filter reflection**, below **Event selection** in the details
panel, to exclude the interval from the displayed image and every graph.
The space between the black boundaries becomes blank white. Only native time
bins whose centres lie on or between the boundaries are excluded. Channels
without boundaries keep all their photons. The filter applies to the current
event selection and reports the number of excluded photons below the checkbox.
Until boundaries have been completed, the checkbox is disabled and displays
**No reflection peak identified.**

While filtering is enabled, the boundaries are locked and the detection and
**Clear** buttons are disabled. Uncheck **Filter reflection** to
restore the image and graph photons, return the interval to grey shading and
adjust the boundaries. Each detector keeps its completed boundaries and filter
setting for each T/Z view and its summed overview while the LIF is open. In a
multi-channel preview, saved filter settings apply to their respective channels.
Changing the checkbox applies to all displayed channels with boundaries.

Use the magnifier controls, mouse wheel, and pan control to inspect image detail.
The horizontal curve below each image is a conventional intensity histogram,
calculated from original pixel intensities, including zeros, before display
clipping or 8-bit conversion. Its **Intensity** axis has equal-width bins;
pixel frequency uses a linear scale by default.
Use **Log scale** below the intensity histograms to switch their pixel-frequency
axis to logarithmic; uncheck it to return to linear. This shared toggle does
not change the intensity axis, contrast boundaries or fluorescence-decay scale.
Zero-frequency bins are omitted on the logarithmic scale. The full range is
retained. Narrow integer ranges use one bin per intensity value; wider ranges
use 256 equal-width bins. These bins count original pixels and do not quantise
or change the source intensities.
Drag its lower black-level line or upper white-level line to adjust contrast.
Default boundaries are P0 and P99.8. Right-click the histogram and select
**Reset (P0 - P99.8)** to restore them. These controls change the view
only, preserving photon data, ROIs and exports. For multiple channels or mosaic
tiles, each channel has independent contrast levels; a mosaic channel's curve
pools its tiles. Channel headers are excluded. Reset affects only that
image's levels. New previews reset all levels. Switching the
reflection preview filter preserves the selected contrast levels.
The labels above each histogram express its contrast boundaries as percentiles;
P0 is the actual minimum and P100 the true maximum. The boundaries are drawn
at their corresponding intensity values on the axis. Percentile spacing is
not used to draw the frequency curve, since it distorts histogram shapes.

Shift-drag also pans. Zooming and panning change the view while keeping ROI
coordinates in image data space. Escape exits the current navigation tool.

ICS and PTU dialogs share compact acquisition rows, detector/filter labels, T/Z
menus, selection controls, and preflight status. The T/Z menu expands individual
planes while retaining their selections. **Ready** means the source, metadata,
and index support the requested export; **Failed** includes a diagnostic tooltip
and disables that row. Filenames identify detector/filter, selected plane, and
nondefault photon selection. Existing files are suffixed or skipped according to
the chosen collision policy.

ICS exports provide independently selected 128- or 256-bin calibrated integer
histograms, with gzip or uncompressed payloads and JSON metadata. PTU exports
retain native photon microtimes and include raster markers and overflow records.
Their macrotime is reconstructed from the raster acquisition; see the scientific
contracts before interpreting it as a hardware timestamp. Partial acquisitions
export only indexed data and record the actual and nominal row counts.

LAS X Navigator mosaics open as a labelled matrix of separate tiles. For
example, **R1 (4)** in **HCC1954 mS3-mitoPyr-ShadowR.lif** shows a 2 × 2 matrix,
with each tile retaining its 1024 × 1024 pixels. The matrix follows the
recorded stage positions, including scans stored in a snake pattern. It is
an unstitched view; overlapping image areas are retained in each tile.

By default, one photon-arrival graph pools counts across the whole mosaic.
Use **Separate graphs by tile**, beside **Combine all ROIs**, to show an
individual graph for each tile. Toggle it off to return to the whole-mosaic
graph. This changes the graph display immediately. Detector/excitation pairs
keep separate graphs and their own timing calibration in either mode.

With no active ROI or pixel inspection, graphs show **All Pixels**: the
whole mosaic in combined mode, or each corresponding tile in separate mode.
Hovering a tile pixel inspects that pixel; other separate tile graphs retain
their all-pixel counts. Moving into a tile heading, a gap, the surrounding
black margin, or outside the image viewer restores the default graphs.
Activated ROIs retain priority over pixel hovering.

Pixel inspection and ROIs use the corresponding tile's counts. An ROI may
cross tile boundaries. **Combine all ROIs** pools their selected pixels
across the mosaic, counting shared pixels once. When
comparing detectors, regions are mirrored between matching spatial tiles.
Time and depth controls, where present, change T/Z while keeping the matrix.
Split PTU and ICS exports keep tiles separate and identify their row and
column in filenames, with stage coordinates in the JSON metadata. Use split
export for mosaics; integration would superimpose different stage positions
and is unavailable for these acquisitions.

Cancel stops active indexing, decoding, or export at the next bounded work step.
Closing during work first cancels and waits for the worker to finish. Completed
outputs are retained; an interrupted current output is removed. Diagnostic logs
are written to the LIFTOFF folder in the platform application-data directory.
Set `LIFTOFF_LOG_DIR` to override that location. The previous
`LEICA_INTERROGATOR_LOG_DIR` setting is also accepted as a fallback.


Timing exports use the selected detector and scan sequence's recorded arrival
clock and laser frequency. The export table shows timing quality. ICS retains
128 bins as its compatibility default; choose **Native timing** to preserve the
recorded increment, or choose a numeric bin count to rebin one laser period.
Finer output bins do not add timing information. Photons outside the chosen
arrival window are excluded and counted in the JSON sidecar and completion
message. ICS temporal calibration is written in seconds in both header fields.
Native bin counts can be non-powers of two; confirm support in downstream tools
before adopting that option as a routine default.

ICS and PTU files also contain essential acquisition metadata, including
excitation/emission settings, detector names, T/Z identity, tile position and
spatial calibration. Detailed provenance and original Leica acquisition XML
remain in the companion JSON. Keep the JSON for traceability; software reading
only the image file may show the embedded metadata as custom header fields.

Every ICS/PTU export also creates two readable reports beside the data file:
`example.ics.metadata.csv` / `example.ptu.metadata.csv` for Excel and other
spreadsheet applications, and `example.ics.metadata.html` /
`example.ptu.metadata.html` for a web browser. The HTML report links to the CSV
and detailed JSON. Tables show each value with its units, evidence status and
source; long original XML remains in JSON. CSV uses UTF-8 with a byte-order
mark so units and names display correctly in Excel. Source text resembling a
spreadsheet formula is stored as text.

In the HTML microscope and scan settings, values sharing a source root are
grouped together. The Source column heading shows that root once, and each row
shows the remaining field name, such as `@ObjectiveName`. CSV and JSON retain
the complete source paths.

The reports and embedded metadata include available objective, numerical
aperture, immersion, magnification, zoom, stage positions, scan frequency,
averaging, accumulation and pinhole settings. Detector settings belong to the
exported channel. Laser intensity percentages are instrument settings, not
measurements of power at the specimen. A pinhole calculation wavelength is
separate from the detector's emission band.

Recorded image timestamps appear in UTC, with the first and last source image
times, their span, and the selected image time when its channel/plane association
can be verified. LAS X may display these times in local time. Image timestamps
do not restore individual photon hardware times or supply missing line/frame
periods. The current focus Z setting is labelled separately from the selected
plane's position; that position uses a matching original stack origin and the
recorded Z spacing.

ICS now also writes defined sensor fields for a single nominal excitation
wavelength, channel description and detector model, plus conventional history
fields for the acquisition title, detector, objective and emission-band name,
plus the defined numerical-aperture sensor field when available. Multiple
excitation wavelengths remain in the structured metadata; no single wavelength
is invented. An emission band is kept as a range, rather than replaced by its
midpoint. PTU's standard file-comment field includes a readable acquisition
summary and timing interpretation, alongside its defined calibration tags.
Application-specific interpretation of these fields has not yet been tested.

Existing-file handling protects the entire data/JSON/CSV/HTML set. A report or
active temporary file also reserves its filename. If report writing fails,
the current output set is removed and the export is reported as failed;
already completed exports are retained.

Spatial calibration read from Leica dimension lengths uses the distance
between the first and last pixel centres (`Length / (pixel count - 1)`).
Explicit recorded voxel sizes are used directly. Unknown X/Y calibration is
labelled in pixels, with one pixel per sample, rather than metres. Each axis
is treated independently. PTU's single standard pixel-size field is omitted
when X/Y differ or either calibration is unavailable; separate axis values
and units remain in its custom header metadata and JSON.

Both export windows have a **Filter reflection photons where applicable**
checkbox directly below **Event selection**. It starts unchecked and works
independently of the preview filter checkbox. It becomes available when at
least one selected output has saved boundaries. Check it to exclude photons
within the saved boundaries wherever they apply, in addition to the chosen
event selection. Outputs without matching boundaries skip reflection filtering.

Boundaries from an individual T/Z preview apply to that T/Z position.
Boundaries from a summed overview apply throughout that channel. Split outputs
use the individual T/Z bounds when both are saved. Filtering an integrated
output requires a single interval covering the full output. Mosaic tiles share
their channel's interval.

ICS excludes the native arrival bins before rebinning, so counts on either
side of a boundary remain correct even when they share an output bin. PTU
omits matching photon records while preserving the scan markers and remaining
native arrival values. JSON sidecars record the exact boundaries and number
of excluded reflection photons separately from photons outside the ICS time
window. Unchecked exports retain the usual photon-selection behaviour.

PTU **Recorded scan timing when complete** uses a nominal reconstructed scan
only when the necessary recorded periods are consistent. Otherwise it produces
an explicitly labelled **Synthetic** raster. **Require reconstructed timing**
fails when those fields are incomplete; **Synthetic raster** preserves the
previous raster convention. Sync periods per pixel affect only synthetic timing.
Neither option restores original individual photon timestamps. Actual recorded
scan timing, tile/repetition identities, and raw timestamp metadata are retained
in each JSON sidecar. Missing arrival-clock or laser-rate calibration prevents a
calibrated export and is shown as **Unavailable**.
