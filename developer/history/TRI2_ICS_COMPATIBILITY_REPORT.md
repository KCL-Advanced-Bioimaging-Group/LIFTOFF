# TRI2 ICS Compatibility Report

## Compatibility Oracle

The supplied `Gut_organoid_NADH.ics` is an ICS v2 file with a 676-byte ASCII
header followed by an embedded gzip stream. Its declared layout is
`bits, y, x, z`, where `z` is the FLIM time-bin dimension. The reference is
16-bit unsigned little-endian, 512 x 512 x 128, and stores y as the fastest axis.

## Confirmed Implementation

- One `.ics` file contains both header and payload; no `.ids` file is created.
- The payload begins immediately after `end\t\n` and gzip begins `1f 8b 08`.
- The exported layout is `bits, y, x, t`; the final axis is `micro-time` in ns.
- Parameter scales contain the calibrated y/x pixel sizes in metres and the
  time-bin width in ns. Time-bin width is the exported time span divided by bins.
- Physical x, y, and repetition-period calibration is also carried in
  `history extents`, with explicit `m m s` units. Parameter scales and history
  extents now describe the same calibration (allowing for decimal rounding).
- Counts are uint16 unless a bin exceeds 65535, then they are promoted to uint32.
- Output is written to a `.part` file and atomically renamed on success.
- LIF Element ancestry supplies acquisition names. Extra Leica identifiers are
  added only when needed to make filenames unique.
- JSON sidecars record Leica names, calibration, axis order, integer width,
  compression, photon totals, decoder details, and inferred fields.

## Real LIF Validation

`Project (1).lif`, `MemBlock_10498`, was decoded with the native x64 DLL and
exported as `Image001.ics` with 128 bins. Validation reconstructed the complete
cube from the ICS payload:

- Shape: 128 x 512 x 512 (time, y, x)
- Photon count before export: 52,926,684
- Photon count after reconstruction: 52,926,684
- Maximum bin count: 92
- Integer representation: uint16 little-endian
- Compressed file size: 6,250,987 bytes
- Payload offset: 678 bytes

## Inferred Or Unresolved

- LAS X headers can contain nested container fragments that are not strict XML.
  Element ancestry is therefore recovered with a bounded tag stack.
- Optional series, channel, time, z, and detector labels vary across LAS X
  versions. They are preserved when present and used for disambiguation.
- TRI2 acceptance of uint32 ICS should be checked with an overflowing real
  acquisition. The writer and round-trip tests support it without clipping.
- The original reference's placeholder spatial labels and scales are no longer
  copied. Acceptance of the corrected `t`/ns header in TRI2 has not been checked
  interactively. Payload storage order, counts, and compression are unchanged.
- Earlier exported files retain their old headers and need re-exporting. Correct
  metadata does not equalize different image and excitation acquisition periods.
