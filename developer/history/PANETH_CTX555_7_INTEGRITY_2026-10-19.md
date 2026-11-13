# paneth_ctx555_7: compressed photon-data integrity

Investigated 19 October 2026 using the source version only.

## Conclusion

The supplied LIF contains an incomplete, zero-filled compressed photon
block for `paneth_ctx555_7`. The app correctly rejects it. No incorrect
memory-block location, channel interpretation or row-table offset was
found for this entry.

This concerns the time-resolved photon data. Its separate intensity
images survive, so the visible thumbnail and raw intensity counts do
not establish that the photon-arrival data are complete.

## Evidence in the source file

Source:
`Leica Interrogator Example Data\20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif`.

The two channels share compressed block `MemBlock_8630`. The entry has
512 × 512 pixels, T=1 and Z=1. Both WLL and MP photons therefore depend
on the same damaged block; a multichannel or multiplane layout mismatch
does not explain this failure.

| Check | Result |
| --- | --- |
| XML memory declaration | 33,554,432 bytes |
| Independently parsed binary record size | 33,554,432 bytes |
| Absolute payload start in the LIF | 2,915,040,631 bytes |
| Container version and stream start | Version 1, offset 64; same format as working entries |
| Declared compressed stream size | 17,044,590 bytes |
| Declared image rows | 512 |
| Declared row-table size | 5,592 bytes: 1,398 four-byte entries |
| Actual row-table contents | All 1,398 entries are zero |
| Actual footer contents | Both eight-byte values are zero |
| First byte of the all-zero suffix | Block-relative offset 16,777,216: exactly 16 MiB |
| Verified all-zero suffix | Entire second half of the 32 MiB block: 16,777,216 bytes |

The header places the following components at these block-relative
byte ranges, with exclusive upper bounds:

| Component | Start | End |
| --- | ---: | ---: |
| Compressed stream | 64 | 17,044,654 |
| Row descriptor table | 17,044,654 | 17,050,246 |
| Footer | 17,050,246 | 17,050,262 |

The zero-filled region starts **before the declared compressed stream
ends**. It includes its final **267,438 bytes**, the entire descriptor
table and the footer. This is not merely unused allocation after a
complete compressed payload.

The last byte before that boundary is nonzero. The following 16 MiB
was checked using an ordinary binary file read as well as a memory map.
The next LIF record, `MemBlock_8618`, begins at the correct end of the
declared block. The file is structurally present beyond the damage;
this is an internal zero-filled block suffix, not a short file read.

## Checks against an application fault

1. Searched the binary section directly for the encoded memory-block ID
   and independently parsed the record header. Its location and size
   agree with the app and the XML declaration.
2. Checked the table at the offsets declared by the container itself.
   Zero bytes remain zero regardless of byte order. No alternative
   standard descriptor-group prefix was found elsewhere in this block.
3. Compared all **35 compressed acquisition blocks** in this LIF.
   Only `paneth_ctx555_7` has an empty descriptor table. The other 34
   have populated tables; working neighbouring entries also have the
   expected nonzero footer values.
4. Bypassed the catalogue's rejection for a forensic native-reader
   attempt. The underlying native reader independently fails with
   `descriptor group has no row payload`.
5. Invoked the Python descriptor reader directly. It independently
   fails with `Descriptor group 0 has no row payload`.

A standard zlib failure was **not** used to diagnose damage: the LAS X
grouped stream also fails ordinary zlib decoding for working entries.
The decisive evidence is the verified source bytes and absent index,
not an assumption that Leica's grouped format is ordinary zlib.

## Why the image thumbnail still works

Intensity data are stored separately in `MemBlock_8618`. Its channel
images contain 41,562,453 and 4,287,088 intensity counts. The app can
read these to make a thumbnail and report raw counts even though the
compressed photon block cannot produce valid pixel-arrival histograms.
Intensity counts do not retain the individual photon-arrival times
needed to reconstruct the missing FLIM data.

Some leading compressed data survives. The evidence establishes that
the complete indexed photon dataset is unavailable in this copy; it
does not prove that every surviving photon is beyond possible partial
salvage. Treating this entry as a complete decoded image would require
inventing missing information.

The abrupt 16 MiB boundary is consistent with an incomplete write or
zeroed storage region. The file alone cannot establish whether this
occurred during acquisition, saving, copying or subsequent storage.

## Recommended next step

Obtain another copy of the original acquisition LIF and compare this
entry. If the original still contains valid FLIM data in LAS X, re-save
or export it from there. Check actual decay/photon data in LAS X rather
than just the intensity image. Re-copying this same damaged file will
not restore the missing information.

## Validation and changes

No production decoder change was necessary. Added a real-data
regression that independently checks the binary header and zero-filled
suffix, verifies the surviving intensity counts, and ensures that both
preview and export reject the invalid photon dataset.

The compressed-integrity, compressed-stack and real partial-stack tests
were rerun, together with the maintained Python formatting, lint and
type checks: **48 tests passed**. All **110 maintained Python files**
pass Ruff formatting and linting, Pylint (10.00/10) and Pyrefly (zero
diagnostics). Final results are recorded under
`validation/paneth7-investigation-2026-10-19/`.

Evidence files:

- `findings.json`: exact component ranges and conclusion.
- `independent-offset-verification.json`: binary ID search, embedded
  record sizes, next record and full zero-suffix verification.
- `container-comparison.json`: the target and working neighbours.
- `all-compressed-records.json`: every compressed block in this LIF.
- `stream-zero-analysis.json`: abrupt zero boundary inside the stream.
- `independent-decoder-checks.json`: native and Python reader errors.
- `compressed-container.bin`: bounded extracted header, declared stream,
  index and footer; its SHA-256 is in `container-comparison.json`.
- `tests-final.log` and `quality-final.log`: final validation results.

The supplied LIF and standalone executables were not modified.
