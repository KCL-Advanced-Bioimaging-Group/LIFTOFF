# Leica Image Files Translated into Open File Formats (LIFTOFF)

This guide describes the earlier Leica Interrogator version of LIFTOFF, a
single-window Windows desktop application for
opening Leica LAS X compressed and LMSRAW FLIM blocks and inspecting pixel or ROI photon
arrival histograms. It does not use a browser or local web server.

Version 5 adds selected-block PicoQuant PTU export using the supported Generic
T3 record layout.

## Install

The earlier release used Python 3.11 or newer and installed its desktop
dependencies from its bundled requirements file. For the maintained source,
follow the [current installation steps](../../README.md#start-on-windows).

For the high-performance decoder, install Visual Studio 2022 Build Tools with
the **Desktop development with C++** workload, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_native_decoder.ps1
```

This creates:

```text
leica_flim_converter\native\LeicaFlimDecoder.dll
```

If the DLL is absent or has an incompatible API version, the application uses
the verified Python oracle and identifies that fallback in the status bar.
Native decoding errors are reported and are not silently hidden by a fallback.

## Start

Double-click `launch_leica_interrogator.bat`.

The launcher opens the PySide6 desktop window directly. It checks dependencies
in a visible console before starting `pythonw`, avoiding silent startup errors.

## Workflow

1. Select **Open LIF files** using the native Windows file dialog, or drag one or
   more `.lif` files from Windows Explorer into the application window.
2. File indexing lists FLIM detector datasets and thumbnails only. It does not
   select or decode a block.
3. Select one block from the left panel to begin its decode.
4. The selected block is converted directly into a 128 x Y x X histogram cube.
5. Move over the summed-photon image to inspect a pixel histogram.
6. Click or drag a rectangular ROI to display its integrated histogram.

Only one decoded cube is retained. Selecting another block releases the prior
cube before preparing the new selection.

Dropping or opening additional LIF files appends them to the current session and
deduplicates paths. **Clear data** closes the complete collection. Other file
types, folders, and web links are ignored. Import is available when the
application is not indexing, decoding, or exporting.

### Large-file indexing

The catalog uses Leica MemBlock record headers to seek directly over image and
photon payloads. Indexing time therefore scales with the number of records and
XML metadata, not with a 10-130 GB payload size. The GUI reports record progress
and permits cancellation. It never silently falls back to a complete payload
scan for files above 2 GiB.

The same behavior is available through the public API:

```python
from leica_flim_converter import IndexCancelled, scan_lif

datasets = scan_lif(
    "large.lif",
    progress=print,
    cancelled=lambda: False,
    allow_linear_fallback=True,
)
```

The compatibility fallback is bounded to files no larger than 2 GiB. A malformed
larger container fails promptly with an explanatory error.

Compressed LIF movie blocks use their exact encoded stream length rather than Leica's
larger fixed memory allocation. Linked intensity frames are summed for the
thumbnail and photon-count oracle. A zero-row placeholder block is shown as
unavailable and cannot be selected for decoding or export.

## TRI2-Compatible ICS Export

Click **Export ICS** to choose detector, T, and Z outputs. Nothing is selected or
decoded automatically. In split mode each row is one concrete detector/T/Z file;
any combination of rows can be selected for batch export. The dialog shows Leica
acquisition metadata, detector identity, dimensions, payload size, and each
proposed LIF-derived name.

Rows are grouped beneath bold source-LIF headings. Checking a heading selects
every exportable detector/T/Z row from that LIF; a partially selected file shows
a partial checkbox. By default all outputs use the chosen output folder. Enable
**Per-LIF folders** to instead create or reuse a folder beside each source LIF,
named from the filename without `.lif` (for example, `WT_NADPH\` beside
`WT_NADPH.lif`).

Selected blocks are decoded sequentially, exported as separate embedded-payload
ICS v2 files, and accompanied by JSON metadata sidecars. Gzip and uncompressed
payloads and 32-4096 time bins are supported; 128-bin gzip is the default.
Existing files are never overwritten silently. Cancellation removes incomplete
files, while failure of one block does not stop the remaining selections.

Detector channels are always separate files. Movies and z-stacks are split by
default. Output names include Leica channel/detector identity and use `_t001`, `_z001`, or
combined `_t001_z001` indices, with one TRI2-compatible decay cube per physical
plane. Every ICS contains exactly one logical `X, Y, photon-arrival histogram`
cube; detector, T, and Z are filename/metadata selectors and never extra payload
axes. **Integrate T/Z per detector** remains available and writes an explicitly named
`_all-frames-summed`, `_all-z-summed`, or `_all-planes-summed` file per detector.

LMSRAW `PulseVersion2` data uses Leica's LineOffsets and FrameOffsets tables to
read only the selected rows. Up to four detector routes are separated before
histogram accumulation; the complete multi-detector event block is never loaded
into RAM. Routes 1-2 are confirmed against the supplied Leica intensity planes;
routes 3-4 follow the adjacent word-pair grammar and have synthetic test coverage.

## PicoQuant PTU Export

Click **Export PTU** to select any detector/T/Z rows for batch export. No rows
are selected automatically and no FLIM payload is decoded until export starts.
Each selection produces one `.ptu` file and one `.ptu.json` sidecar.
The bold LIF headings and **Per-LIF folders** option behave identically to the
ICS export dialog.

The writer uses PicoQuant Generic T3 record type `0x00010307`, 32-bit records,
15-bit microtime, compressed overflow records, and explicit line-start,
line-stop, and frame markers. Required measurement, image, timing, record-count,
and record-type tags are written without copying a template PTU.

Photon count, X/Y assignment, decoded native microtime, and detector route are
preserved. The Leica reduced stream does not contain the original hardware
macrotime, so sync timestamps and marker timing are reconstructed on a regular
raster clock. This distinction is recorded in both `File_Comment` and the JSON
sidecar. The default is three laser sync periods per pixel and can be changed in
the export dialog.

Frame repetitions remain as frame markers in one PTU. Explicit line repetitions
are combined onto their logical Y line, preserving all photons without creating
false extra image rows. T and Z planes and Leica detector datasets remain
separately selectable files.

## Native Decoder

The C++17 DLL:

- parses each Leica descriptor-group header and dynamic Huffman table once;
- creates exact, independently bounded row jobs;
- decodes rows through a persistent native worker pool;
- fuses Huffman decoding, Leica token interpretation, microtime conversion, and
  128-bin histogram accumulation;
- creates no Python photon objects or expanded event list;
- uses one worker-local `128 x width` row histogram;
- merges under short per-output-row locks;
- checks exact row-bit consumption, bounds, cancellation, and uint32 overflow.

The DLL handles compressed blocks and writes into a NumPy-allocated uint32 cube
through a stable C ABI. LMSRAW uses the bounded streaming decoder. Native
progress callbacks are throttled and cancellation is checked for every row.

## Validation

For a packaged runtime check, run:

```powershell
python validate_installation.py
```

This confirms the Python dependencies, application imports, required local
modules, and the supplied API v3 native decoder. Before packaging, the full
development suite demanded exact native/Python array equality at multiple
thread counts and exercised fallback and cancellation paths. Those tests and
benchmark tools are summarized in `Version Updates.md` and intentionally
omitted from the lean V2 runtime package.

## Current Reference Results

The Python oracle has been validated as follows:

- sparse matched block: 34,231 photons, exact 128-bin cube;
- dense 512 x 512 block: 52,926,684 photons;
- file indexing for the 605 MB LIF: approximately one second;
- pixel lookup after decoding: approximately 0.015 ms;
- 51 x 51 ROI lookup: approximately 0.62 ms.

Native performance must be measured after compiling the DLL on the target
machine. Do not interpret Python fallback timings as native DLL performance.
