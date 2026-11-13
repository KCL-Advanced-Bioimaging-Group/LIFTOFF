# Leica Image Files Translated into Open File Formats (LIFTOFF) 3.2.2

Self-contained Windows application.

## Start the application

Double-click **LIFTOFF_App_3.2.2.exe** in this folder.

No installation, administrator rights, Python, Qt or separate dependency
installation is required. The application includes its Python runtime, Qt/PySide6,
NumPy, Pillow, native Leica decoders and Microsoft C/C++ runtime libraries.

Keep the executable and the **_internal** folder together. To move the application
to another location or computer, copy the entire folder. Copying only the executable
will not work. Run it from an extracted folder rather than from inside a ZIP file.

This build targets **64-bit Windows 10 version 1809 or later, or Windows 11**,
on an **Intel/AMD x86-64-v2 processor**. NumPy's required CPU features include
SSE4.2 and POPCNT. Windows 7/8/8.1, 32-bit Windows and processors lacking that
CPU baseline are unsupported. This is an x64 build; Windows on ARM has not been
validated. Memory requirements depend on image size, histogram bins and the number
of selected recorded pairs.

See the release evidence for verification on the build computer and any
independent Windows systems. Organisation-specific application-control
policies can affect whether an unsigned application may run.

Runtime platform references: [Qt 6.11 supported platforms](https://doc.qt.io/qt-6.11/supported-platforms.html)
and [NumPy CPU baselines](https://numpy.org/doc/2.4/reference/simd/build-options.html).

## Open and explore data

1. Click **Open LIF files**, or drag LIF files onto the application.
2. Select an acquisition beside its thumbnail on the left.
3. Use **All Photons**, **First Photon** or **Single-event** to choose the event
   selection. The image and photon-arrival histogram update together.
4. For acquisitions with multiple recorded pairs, use the **Excitation | Emission**
   table on the right. Select an excitation to enable its emission choices. Expand
   a row to see additional emissions. Select one or several recorded pairs to view
   their images and histograms together; each retains its own calibration.
5. Use the time/Z selector and arrow buttons for a timelapse or Z stack.
6. Use the image controls to zoom or pan. Draw and select regions of interest
   to examine their photon-arrival histograms; **Clear all ROIs** removes them.

Excitation wavelength and source, and emission band and detector, are shown where
the acquisition supplies that metadata. Missing metadata is shown as unavailable.
Thumbnails may use available linked intensity frames from a partial acquisition.

Navigator tile scans display as a matrix. Graphs initially sum all tiles for
each selected recorded pair. **Separate graphs by tile** switches to individual
tile graphs. Without a selected ROI or hovered pixel, graphs show all pixels
in the relevant image or tile. Pixel hover works across channel comparisons.

Verified partial stacks show the number of recorded planes alongside the
declared extent. Navigation and exports include only recorded planes. If a
compressed photon block is incomplete, the app reports that failure even if
its separately stored intensity thumbnail is still available.

## Export

Use **Export PTU** for photon events or **Export ICS** for histogram image data.
Choose the acquisitions, recorded pairs, event selection and time/Z planes in the
export dialog. Outputs distinguish excitation sequences and detector channels.
JSON sidecars preserve metadata, calibration and export provenance. Keep these
sidecars with their exported files.

ICS and the viewer share calibrated arrival-time bins. PTU preserves native
arrival values and labels its reconstructed or synthetic scan timeline.
Emission labels use whole nanometres while sidecars retain source precision.

## What is included

- **LIFTOFF_App_3.2.2.exe**: desktop application.
- **_internal/**: required runtime libraries, Qt plugins and application resources.
- **THIRD_PARTY_LICENSES/**: license notices supplied with bundled dependencies.
- **README.md**: quick-start and troubleshooting information.
- **USER_GUIDE.md** in this folder covers previews, ROIs, reflection filtering,
  and PTU and ICS exports in detail.
- **RELEASE_MANIFEST.json**: version, build provenance and file checksums.

Open example LIF/PTU files directly from their existing location.

## Troubleshooting

If startup reports a missing file, restore the complete folder, including
**_internal**. Do not substitute dependencies from an older application release.

Diagnostic logs are written to **%LOCALAPPDATA%\LIFTOFF\logs**.
If an acquisition fails, the application reports the decoding error instead of
displaying an unverified result. Include the relevant log and acquisition name
when reporting a problem.

If Windows reports **"Windows cannot access the specified device, path, or file"**,
check that the complete application folder is extracted into a location your
account can access, such as your Documents folder. Your account needs Read and
execute access to the executable and its dependencies. If normal launch is denied
but running as administrator succeeds, ask your IT team to check the folder
permissions and application-control policy. The executable itself requests
standard-user privileges (`asInvoker`); administrator rights are not an application
requirement. This build is unsigned, so an organisation's policy may require approval.

The maintained scientific behavior and sequence handling are validated against
the supplied LAS X PTUs and retained single-excitation reference data. Packaging
verification also exercises bundled decoding, PTU/ICS export, and mixed sequence,
time and Z navigation. The application does not require any previous release folder
to start or run.
