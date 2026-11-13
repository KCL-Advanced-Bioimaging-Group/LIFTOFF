# Project history

Use the [current user guide](../../USER_GUIDE.md) for application workflows and the
[developer guides](../DEVELOPER_README.md) for building and maintaining LIFTOFF.
The [release notes](../../RELEASE_NOTES.md) cover individual versions.

The GitHub source import was taken from the 3.2.2 development snapshot
`a21181b5dce73df7a79474e4a8dea1dddca5cc4f`. Earlier development commit
IDs in these records and in the bundled provenance refer to the local
development repository. The historical validation artifacts are in the
local archive.

## Reconstruction and baseline

- [Reconstruction and provenance](RECONSTRUCTION.md)
- [2.4 parity and acceptance](PARITY_REPORT.md)
- [Reference file hashes](reference_hashes.json)
- [Earlier desktop guide](GUI_CONVERTER_GUIDE.md), [installation guide](INSTALLATION_GUIDE.md),
  [PTU guide](PTU_EXPORT_GUIDE.md), [TRI2 ICS compatibility](TRI2_ICS_COMPATIBILITY_REPORT.md),
  and [version history](VERSION_UPDATES.md)

## Investigations and implementation records

- [Detector metadata, timelapse and previews](ISSUE_RESOLUTION_2026-10-13.md)
- [Multi-excitation review](MULTI_EXCITATION_REVIEW_2026-10-13.md) and
  [implementation](MULTI_EXCITATION_IMPLEMENTATION_2026-10-13.md)
- [Mixed light sources](MIXED_LIGHT_SOURCES_2026-10-16.md)
- [Navigator mosaics](NAVIGATOR_MOSAICS_2026-10-16.md) and
  [multichannel validation](MULTICHANNEL_MOSAIC_VALIDATION_2026-10-19.md)
- [Partial compressed stacks](PARTIAL_COMPRESSED_STACK_2026-10-19.md) and
  [photon-data integrity](PANETH_CTX555_7_INTEGRITY_2026-10-19.md)
- [Timebase audit](TIMEBASE_AUDIT_2026-10-16.md) and
  [timing implementation](TIMING_IMPLEMENTATION_2026-10-16.md)
- [Source stress audit](STRESS_AUDIT_2026-10-19.md)

## Original investigation programs

- [Original LIF forensics snapshot](lif_flim_forensics.py.txt)
- [Original deflate investigation snapshot](patent_guided_deflate_attack.py.txt)

These text snapshots preserve the historical investigation command lines.
They are not application launchers or maintained utilities. Some depended
on absent experimental modules (`generative_row_codec_attack` and
`raw_line_clock_spatial_attack`) or optional OME-TIFF investigation code.

The maintained modules with the original import names retain the actual
LIF readers, metadata inspection, token grammar, compressed decoding,
event iterators, and pure analysis helpers used by Leica Image Files Translated
into Open File Formats (LIFTOFF).
Application ICS and PTU exporters have their own maintained APIs. Git
commit `3fcb503` also preserves the untouched original 2.0 tree.

Historical `validation/` paths refer to the original evidence directory,
preserved locally in the sibling `LIFTOFF_Local_Archive` folder.
