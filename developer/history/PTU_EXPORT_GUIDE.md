# Leica Image Files Translated into Open File Formats (LIFTOFF) PTU export history

## Output contract

The earlier Leica Interrogator version writes self-contained PicoQuant PTU files
using Generic T3 record type `0x00010307`. This is the PicoQuant-supported
32-bit layout with:

- bit 31: special record flag;
- bits 25-30: detector channel or marker bit field;
- bits 10-24: 15-bit photon microtime;
- bits 0-9: sync counter;
- special channel 63: compressed sync-overflow record.

The header starts with `PQTTTR`, uses fixed 48-byte tags plus 8-byte-aligned
variable payloads, and terminates with `Header_End`. It includes
`Measurement_Mode=3`, `Measurement_SubMode=3`, image dimensions, line/frame
marker assignments, timing resolution, sync rate, record count, record type,
and bits per record.

## Preserved and reconstructed fields

Preserved from the decoded Leica event stream:

- every photon event;
- logical X and Y position;
- native decoded microtime value and resolution;
- primary versus internal reference route for compressed blocks;
- selected LMSRAW detector route;
- detector, T, Z, and repetition metadata in the JSON sidecar.

Reconstructed because it is absent from the reduced Leica payload:

- absolute macrotime;
- exact hardware sync sequence;
- exact line and frame marker timestamps.

The reconstructed raster uses the Leica laser frequency as the PTU sync rate
when available. A photon at pixel X is assigned to a deterministic synthetic
sync position within its line. `ImgHdr_LineStart=1`, `ImgHdr_LineStop=2`, and
`ImgHdr_Frame=3`; their Generic T3 marker bit fields are 1, 2, and 4.

## Repetitions and dimensions

One PTU is written for each selected Leica detector/T/Z plane. Frame repetitions
remain within that file and are delimited by frame markers. Explicit line-repeat
rows are combined into one logical line before writing, so all repeat photons
are retained without increasing `ImgHdr_PixY`. This mirrors the normal summed
line-repeat interpretation while retaining individual photon records.

## Validation

Before packaging, the development suite checked header alignment, mandatory
image/timing tags, Generic T3 record type, record-count agreement,
detector-channel counts, line/frame marker counts, repetition handling,
selected-plane naming, and JSON sidecars. The full tests and real-file evidence
are summarized in `Version Updates.md` and are intentionally omitted from the
lean V2 package. `leica_flim_converter.ptu.parse_ptu(..., parse_records=True)`
remains available as the independent structural reader used by those tests.

## Important limitation

The PTU is suitable for photon histograms, decay analysis, and image
reconstruction from the synthetic scan markers. It is not evidence of the
original PicoQuant acquisition macrotime and must not be used for analyses that
depend on authentic inter-photon timing across pixels or scan lines.
