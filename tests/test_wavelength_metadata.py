"""Consistent optical settings, source provenance and nominal labels."""

import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.catalog_detectors import emission_band
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui_helpers import _make_group_item_2
from leica_flim_converter.ics import proposed_ics_filenames
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.optical_metadata import (
    read_emission_band,
    wavelength_label,
)
from leica_flim_converter.ptu_export import export_ptu_blocks
from tests.compressed_fixture import mixed_compressed_lif
from tests.test_reference_science import example_path

BOUNDS = ("565.59571609801003", "629.76875757121104")
TARGETS = (
    f'TargetWaveLengthBegin="{BOUNDS[0]}" TargetWaveLengthEnd="{BOUNDS[1]}"'
)


def _setting(name: str, band: str, enabled: str = "1") -> str:
    return (
        f'<ATLConfocalSettingDefinition UserSettingName="{name}" '
        f'IsEnabledForScanning="{enabled}">'
        '<Detector Channel="3" IsActive="1"/>'
        f"{band}</ATLConfocalSettingDefinition>"
    )


@pytest.mark.parametrize("source", ["WLL", "MP"])
def test_common_emission_fields(raw_dataset: DatasetInfo, source: str) -> None:
    """The light source cannot change emission attribute priority."""
    dataset = replace(
        raw_dataset, detector_identifier="3", excitation_sources=(source,)
    )
    context = _setting(
        "Selected",
        f'<MultiBand Channel="3" {TARGETS} LeftWorld="400" RightWorld="500"/>',
    )
    band = emission_band(context, dataset)
    assert band is not None
    assert band.label == "566 - 630 nm"
    assert band.source_bounds_nm == BOUNDS
    assert band.source_fields == (
        "TargetWaveLengthBegin",
        "TargetWaveLengthEnd",
    )
    assert band.setting_name == "Selected"


def test_paired_fallback() -> None:
    """Missing targets use both legacy bounds together."""
    band = read_emission_band(
        '<MultiBand Channel="3" TargetWaveLengthBegin="565.5" '
        'LeftWorld="410" RightWorld="490"/>',
        "3",
    )
    assert band is not None
    assert band.label == "410 - 490 nm"
    assert band.source_fields == ("LeftWorld", "RightWorld")


@pytest.mark.parametrize(
    "begin", ["NaN", "Infinity", "1e999", "-1", "0", "700", "bad"]
)
def test_invalid_band_is_unavailable(begin: str) -> None:
    """Invalid bounds cannot become a confident optical label."""
    assert (
        read_emission_band(
            f'<MultiBand Channel="3" TargetWaveLengthBegin="{begin}" '
            'TargetWaveLengthEnd="630" LeftWorld="400" RightWorld="500"/>',
            "3",
        )
        is None
    )


def test_sequence_and_master_scopes(raw_dataset: DatasetInfo) -> None:
    """Use the selected setting, with explicit legacy inheritance."""
    dataset = replace(raw_dataset, detector_identifier="3")
    saved = _setting(
        "Saved",
        '<MultiBand Channel="3" LeftWorld="400" RightWorld="500"/>',
        "0",
    )
    master = (
        "<LDM_Block_Sequential_Master>"
        + _setting("Master", f'<MultiBand Channel="3" {TARGETS}/>', "")
        + "</LDM_Block_Sequential_Master>"
    )
    current = _setting("Selected", "")
    inherited = emission_band(saved + master + current, dataset)
    assert inherited is not None
    assert inherited.source_scope == "sequential-master"
    assert inherited.setting_name == "Master"
    assert inherited.label == "566 - 630 nm"
    metadata_path = inherited.metadata["metadataPath"]
    assert isinstance(metadata_path, str)
    assert "LDM_Block_Sequential_Master" in metadata_path
    assert emission_band(saved + current, dataset) is None
    assert (
        emission_band(
            saved + master + current, replace(dataset, sequence_count=2)
        )
        is None
    )
    own = _setting(
        "Selected", '<MultiBand Channel="3" LeftWorld="570" RightWorld="620"/>'
    )
    selected = emission_band(saved + master + own, dataset)
    assert selected is not None and selected.label == "570 - 620 nm"
    assert selected.source_scope == "detector-setting"
    broken = _setting(
        "Selected", '<MultiBand Channel="3" LeftWorld="NaN" RightWorld="620"/>'
    )
    assert emission_band(saved + master + broken, dataset) is None


def test_conflicting_active_bands(raw_dataset: DatasetInfo) -> None:
    """Conflicting settings cannot supply an arbitrary last band."""
    dataset = replace(raw_dataset, detector_identifier="3")
    context = _setting("One", f'<MultiBand Channel="3" {TARGETS}/>')
    context += _setting(
        "Two", '<MultiBand Channel="3" LeftWorld="570" RightWorld="620"/>'
    )
    assert emission_band(context, dataset) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (565.5957, "566"),
        (629.7688, "630"),
        (488.00000000000006, "488"),
        (488.5, "489"),
        (740, "740"),
    ],
)
def test_nominal_wavelength_labels(value: float, expected: str) -> None:
    """Numeric storage precision cannot leak into wavelength labels."""
    assert wavelength_label(value) == expected


def test_labels_and_export_provenance(tmp_path: Path, qapp) -> None:
    """UI labels and both export formats share one optical record."""
    assert qapp is not None
    path = mixed_compressed_lif(tmp_path / "mixed.lif")
    data = path.read_bytes()
    end = 13 + struct.unpack_from("<I", data, 9)[0] * 2
    xml = (
        data[13:end]
        .decode("utf-16le")
        .replace('LeftWorld="565" RightWorld="630"', TARGETS)
        .encode("utf-16le")
    )
    path.write_bytes(
        struct.pack("<IIBI", 112, 5 + len(xml), 42, len(xml) // 2)
        + xml
        + data[end:]
    )
    datasets = scan_lif(path)
    first = datasets[0]
    assert first.emission_filter_band == first.channel_name == "566 - 630 nm"
    assert first.emission_band_metadata is not None
    assert first.emission_band_metadata.source_bounds_nm == BOUNDS
    label = _make_group_item_2(datasets).text()
    assert "566 - 630 nm" in label
    assert "565.5957" not in label
    excitation = replace(
        first,
        excitation_wavelengths_nm=(555.499,),
        excitation_sources=("WLL",),
    )
    assert excitation.excitation_label == "555 nm (WLL)"
    assert (
        "555nm"
        in proposed_ics_filenames([excitation, datasets[1]])[excitation.key]
    )
    assert (
        "555.499"
        not in proposed_ics_filenames([excitation, datasets[1]])[
            excitation.key
        ]
    )
    ptus = export_ptu_blocks(datasets, tmp_path / "ptu")
    images = export_ics_blocks(
        datasets, tmp_path / "ics", IcsExportOptions(bins=32)
    )
    for dataset, ptu, image in zip(datasets, ptus, images, strict=True):
        assert ptu["status"] == image["status"] == "exported"
        metadata = [
            json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
            for result in (ptu, image)
        ]
        assert metadata[0]["opticalMetadata"] == metadata[1]["opticalMetadata"]
        assert metadata[0]["opticalMetadata"] == dataset.optical_metadata
        assert (
            metadata[0]["sequence"]["emissionBand"]
            == dataset.emission_filter_band
        )


@pytest.mark.real_data
def test_supplied_wavelength_metadata() -> None:
    """Both real detectors use the same fields and display precision."""
    path = example_path(
        "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"
    )
    if path is None:
        pytest.skip("Optional mixed-source LIF is unavailable")
    pairs = [
        d for d in scan_lif(path) if d.acquisition_name == "paneth_ctx555_1"
    ]
    assert [d.emission_filter_band for d in pairs] == [
        "566 - 630 nm",
        "410 - 490 nm",
    ]
    for dataset, bounds in zip(pairs, (BOUNDS, ("410", "490")), strict=True):
        band = dataset.emission_band_metadata
        assert band is not None
        assert band.source_bounds_nm == bounds
        assert band.source_fields == (
            "TargetWaveLengthBegin",
            "TargetWaveLengthEnd",
        )
        assert band.source_scope == "detector-setting"
