# TRI2 reflection-export memory investigation

The supplied `mScar3-Pyr_FLIM04_40MHz_570 - 700 nm_HyD X 3_single-event-photons_3.ics`
contains a 1024 x 1024 x 256 float64 cube: 2,147,483,648 payload bytes, plus
19,368 header bytes. It uses the NaN reflection mode, with native bins 209-220
missing. Its unfiltered sibling stores uint16 samples and has a 512 MiB payload.

The installed TRI2 3.0 executable and FreeImageIcs.dll are PE32 x86 binaries.
The executable is not large-address aware. A separate x86 C# probe against
that installed DLL opened the supplied header successfully but could not
allocate its 2 GiB payload. Small float32 and float64 files containing NaNs
were read successfully, including explicit inspection of the missing samples.
Thus NaNs and real64 are not rejected by the installed libics layer.

A streamed float32 copy of the complete supplied file has a 1 GiB payload.
The installed reader consumed it successfully. All 12,582,912 NaNs were kept;
the maximum difference in finite samples was zero. The user then tested it in
TRI2: the application failed at a later allocation, reporting
`GCI_readDaaFromICSFile` and `Malloc failed: Not enough space`.

Read-only inspection of the installed executable identifies separate raw
payload and GCI array allocations in that loading path. The error exit after
the second allocation does not free the first raw buffer. Process inspection
after failed attempts showed about 1.13 GB private bytes retained. Therefore
restarting TRI2 is necessary before interpreting subsequent smaller-file tests.
Compression changes disk size, not these uncompressed allocations.

A 128-bin diagnostic copy sums adjacent pairs over the same 256-native-bin
window and retains all spatial pixels. Its float32 payload is 512 MiB; a
grouped sample remains NaN if either contributing native bin is missing. The
installed DLL read it successfully, but the user reported another memory
error in TRI2 before a fresh-process check was established.

After closing and reopening TRI2, the user successfully opened a 16 MiB
float32 spatial crop retaining all 256 time bins and its NaN reflection
interval. This establishes that the TRI2 application layer accepts float32
ICS files containing NaNs.

After another TRI2 restart, the user also successfully opened the full
1024 x 1024 x 128 float32 diagnostic file containing NaNs. This confirms
end-to-end acceptance of that configuration. The full spatial image and the
256-native-bin arrival window are retained; the time-bin width increases
from 96.96969697 ps to 193.93939394 ps. The earlier 128-bin failure occurred
before the fresh-process test and is consistent with retained allocations.
This result does not establish that a full 256-bin floating stack fits.

The exporter change uses exact uint16/uint32 storage for entirely finite
integral cubes, including Poisson simulations. Other repaired cubes use
float32 when all integer samples remain exact and finite nonzero samples do
not overflow or underflow. Fractional estimates receive normal float32
rounding. Unsafe cases retain float64. Previews and repair calculations are
unchanged. Embedded metadata, JSON and readable reports record the actual
storage type and maximum absolute rounding error. No automatic spatial or
temporal reduction is introduced.

Validation: 130 selected export, reflection, orientation, compression,
metadata and precision checks passed. The independent reader tests cover
integer preservation, fractional precision, NaN positions and float64
fallback for large integers, overflow and underflow. Application acceptance
of both the small NaN-containing file and the full-image 128-bin file was
confirmed by the user after restarting TRI2. The full-image application test
used the NaN mode; fractional interpolation and integer simulation have
automated export/precision coverage but were not separately opened by the
user in this application check.

Public reference: [FreeImageIcs type mappings](https://github.com/glennpierce/FreeImageIcs/blob/master/src/FreeImageIcs_Private.cpp)
map ICS real32 and real64 to FreeImage float and double respectively.
The installed DLL, rather than a newly built public version, was used for
the file-reading probes.
