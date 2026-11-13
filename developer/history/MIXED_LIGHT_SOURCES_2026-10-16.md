# Mixed WLL and multiphoton sources

Investigated and corrected in the source tree, now `LIFTOFF_Source`, on 16 October 2026.
The supplied LIF and standalone application folders were not changed.

The example is `paneth_ctx555_1` in
`20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif`,
memory block `MemBlock_8291`. Both sources and both photon channels are
present in the file.

| Recorded pair | Excitation | Emission | Pulse frequency |
| --- | --- | --- | --- |
| HyD X 3 | 555 nm, WLL | 566–630 nm | 78.02 MHz |
| HyD NDD 2 | 740 nm, MP | 410–490 nm | 80 MHz |

## Cause

`RawData/Channels/Channel/Detectors/DetectorReferences/DetectorIndex` is an
index into the selected sequence's detector list. The reader instead matched
that index against the detector's `Detector` value, which identifies its
photon route. For the second sequence, `DetectorIndex=0` refers to its first
detector, whose photon route is `Detector=1`. The lookup discarded that
detector, leaving the catalogue with one channel.

The LMSCOMPRESSED stream interleaves the two detector routes within the
same 512 encoded rows. Its class markers contain the route number in their
low three bits. The native and Python histogram readers and PTU exporter
selected only route-zero markers (`A8`, `A0`, `B0`, optionally `B8`). The
MP detector uses `A9`, `A1`, `B1`, optionally `B9`.

The compressed catalogue also took the last pulse-frequency value in a
preceding XML window. That assigned the MP detector's 80 MHz frequency to
the WLL detector, whose own record declares 78.02 MHz.

## Correction

Detector references now resolve by list position, retaining the actual
photon route separately. The existing optical-setting reader then resolves
the second detector's MP source and 740 nm wavelength, which is absent
from its detector-level `Excitation` field (stored as zero).

Compressed histograms, prepared plane decodes and PTU exports select the
chosen detector's class markers. Each source retains its own pulse
frequency, intensity reference, image, decay and export identity. Prepared
readers reject use with a different recorded pair. Export sidecars identify
the actual detector markers. The existing photon-selection hierarchy is
preserved.

The source's native histogram library was rebuilt with API 5, which uses
four class-selection bits per detector route. Older libraries are rejected
by the bridge so Python can provide the supported fallback. LMSRAW's
separate row-index handling remains in place.

## Verification

The supplied acquisition opens with two selectable excitation/emission
pairs. Both can be displayed together with separate images and calibrated
decays. Full 32-bin native and Python cubes match at every pixel and bin
for both detectors. With the existing All Photons selection they contain
36,240,835 WLL photons and 3,482,184 MP photons.

The independent synthetic Deflate fixture is checked by standard zlib.
Regressions exercise detector routes 0, 1 and 7, all three named photon
selections, the additional fourth class, whole and prepared histograms,
separate PTU/ICS exports, exported timing and microtimes, and GUI switching
and comparison. Retained catalogue metadata and the earlier mixed-sequence
PTU references are also checked.

The stored intensity summaries (40,582,055 and 3,609,224) differ from the
selected photon totals. They remain separate reference values in the GUI;
native/Python agreement does not assert LAS X PTU parity for this example.
No companion LAS X PTU for `paneth_ctx555_1` was supplied for that comparison.

Results are saved as `validation/mixed-light-sources-*.xml` and `.log`.
The comparison screenshot is
`validation/screenshots/mixed-light-sources-paneth.png`.

- Full functional suite: **105 passed**.
- Integration checks, including five retained catalogues, four supplied
  sequence PTUs, the target LIF and source GUI: **30 passed**.
- Ruff format/lint, Pylint and Pyrefly: clean.

Restart the source application to load the updated Python modules and native
library, then open the LIF and select `paneth_ctx555_1`. Both sources appear
in the Excitation / Emission table.

The wavelength consistency follow-up uses whole-nanometre labels throughout.
Both detectors' emission values come from the same `MultiBand` attributes.
The exact source strings are retained separately in the `opticalMetadata`
object shared by PTU and ICS JSON sidecars. See `SCIENTIFIC_SEMANTICS.md`
for the field priority, scope inheritance and display policy.

Follow-up verification: **123 functional tests** and **26 targeted integration
checks** passed. Ruff format/lint, Pylint and Pyrefly are clean. An audit of
**119 detector records across eight LIF files** confirmed the intended label
rounding with no missing emission bands. The source fields, scopes and exact
values are recorded in `validation/wavelength-metadata-audit.json`; test logs
and XML results use `validation/wavelength-*`.
