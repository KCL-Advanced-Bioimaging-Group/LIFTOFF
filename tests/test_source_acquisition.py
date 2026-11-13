"""Acquisition metadata must match the selected image and detector."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from leica_flim_converter.acquisition_metadata import acquisition_metadata
from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.spatial_metadata import (
    source_metadata,
    voxel_calibration,
)
from tests.test_reference_science import example_path


def _original_xml():
    # Two channels at each of two Z planes. Misleading child settings
    # a different current focus position catch wrong scoping.
    return """<Element Name="Acquired"><Data><Image>
    <ImageDescription><Channels>
    <ChannelDescription BytesInc="0"><ChannelProperty>
    <Key>DetectorName</Key><Value>HyD NDD 2</Value>
    </ChannelProperty></ChannelDescription>
    <ChannelDescription BytesInc="4"><ChannelProperty>
    <Key>DetectorName</Key><Value>HyD NDD 3</Value>
    </ChannelProperty></ChannelDescription>
    </Channels><Dimensions>
    <DimensionDescription DimID="1" NumberOfElements="2"
    Origin="0" Length="1e-6" Unit="m" BytesInc="1"/>
    <DimensionDescription DimID="2" NumberOfElements="2"
    Origin="0" Length="1e-6" Unit="m" BytesInc="2"/>
    <DimensionDescription DimID="3" NumberOfElements="2"
    Origin="-75e-6" Length="10e-6" Unit="m" BytesInc="8"/>
    </Dimensions></ImageDescription>
    <TimeStampList NumberOfTimeStamps="4">
    1dd362970d306e0 1dd362970d306e0 1dd36297d124010 1dd36297d124010
    </TimeStampList>
    <Attachment Name="HardwareSetting" Software="LAS X example">
    <ATLConfocalSettingDefinition UserSettingName="Acquisition"
    ObjectiveName="20x DRY" Magnification="20" NumericalAperture="0.75"
    Zoom="2.4" StagePosX="0.0661" ZPosition="-65e-6"
    ScanSpeed="400" Pinhole="0.0006" PinholeAiry="10.6"
    EmissionWavelengthForPinholeAiryCalculation="580"/>
    <LDM_Block_Sequential><LDM_Block_Sequential_List>
    <ATLConfocalSettingDefinition UserSettingName="Wrong saved setting"
    IsEnabledForScanning="0" ScanSpeed="999" NumericalAperture="1.4"/>
    <ATLConfocalSettingDefinition UserSettingName="Setting 1"
    IsEnabledForScanning="1" PixelDwellTime="1.4e-6">
    <Detector Channel="1001" IsActive="1" DyeName="NADPH"
    AcquisitionModeName="PhotonCounting"/>
    <Detector Channel="1002" IsActive="1" DyeName="Other dye"/>
    <LaserLineSetting LaserLine="735" IntensityDev="3"/>
    </ATLConfocalSettingDefinition>
    </LDM_Block_Sequential_List></LDM_Block_Sequential>
    </Attachment></Image></Data><Children><Element Name="Derived">
    <Data><Image><ImageDescription><Dimensions>
    <DimensionDescription DimID="3" NumberOfElements="2"
    Origin="0" Length="1" Unit="m"/>
    </Dimensions></ImageDescription><Attachment Name="HardwareSetting">
    <ATLConfocalSettingDefinition NumericalAperture="1.9" ScanSpeed="999"/>
    </Attachment></Image></Data></Element></Children></Element>"""


def _dataset(raw_dataset):
    return replace(
        raw_dataset,
        z_count=2,
        z_stride=1,
        channel_count=2,
        detector_name="HyD NDD 2",
        detector_identifier="1001",
        excitation_wavelengths_nm=(735,),
        source_acquisition_xml=_original_xml(),
        spatial_sources=tuple(
            voxel_calibration(axis, value, "RawData")
            for axis, value in (("x", "1e-6"), ("y", "1e-6"), ("z", "10e-6"))
        ),
    )


def test_source_image_origin_and_focus_are_distinct(raw_dataset):
    """The first plane uses the stack origin, never final focus."""
    dataset = _dataset(raw_dataset)
    first, last = (acquisition_metadata(dataset, plane) for plane in (0, 1))
    assert first["plane"]["sourceZPositionMetres"] == pytest.approx(-75e-6)
    assert last["plane"]["sourceZPositionMetres"] == pytest.approx(-65e-6)
    settings = first["acquisitionSettings"]
    assert settings["ZPosition"]["value"] == pytest.approx(-65)
    assert settings["StagePosX"]["value"] == pytest.approx(66100)
    assert settings["NumericalAperture"]["value"] == 0.75
    assert settings["Pinhole"]["value"] == pytest.approx(600)
    assert settings["ScanSpeed"]["value"] == 400
    assert settings["DetectorDyeName"]["value"] == "NADPH"
    assert settings["LaserIntensity735"]["value"] == 3
    assert settings["PixelDwellTime"]["sourceValue"] == "1.4e-6"
    original = source_metadata(dataset)["spatialCalibration"][2]
    assert original["sourceValues"]["value"] == "10e-6"
    assert original["originSourceValues"]["Origin"] == "-75e-6"
    assert (
        acquisition_metadata(dataset, dimension_mode="integrate")["plane"][
            "sourceZPositionMetres"
        ]
        is None
    )


@pytest.mark.parametrize("change", ["count", "spacing", "unit", "malformed"])
def test_incompatible_original_dimensions_do_not_supply_origin(
    raw_dataset, change
):
    """Preserve voxel spacing when a parent image cannot be matched."""
    dataset = _dataset(raw_dataset)
    xml = dataset.source_acquisition_xml
    assert xml is not None
    changes = {
        "count": (
            'DimID="3" NumberOfElements="2"',
            'DimID="3" NumberOfElements="3"',
        ),
        "spacing": ('Length="10e-6"', 'Length="20e-6"'),
        "unit": ('Length="10e-6" Unit="m"', 'Length="10e-6" Unit="pixel"'),
        "malformed": ("</Element>", ""),
    }
    dataset = replace(
        dataset, source_acquisition_xml=xml.replace(*changes[change])
    )
    metadata = acquisition_metadata(dataset, 0)
    assert metadata["plane"]["sourceZPositionMetres"] is None
    assert (
        metadata["spatialCalibration"]["axes"]["z"]["spacingMetres"] == 10e-6
    )


def test_channel_and_plane_timestamp_association(raw_dataset):
    """Paired channel timestamps follow source dimension strides."""
    dataset = _dataset(raw_dataset)
    other = replace(
        dataset, detector_name="HyD NDD 3", detector_identifier="1002"
    )
    for plane in (0, 1):
        for channel, selected in enumerate((dataset, other)):
            metadata = acquisition_metadata(selected, plane)
            stamps = metadata["imageTimestamps"]
            assert (
                stamps["selectedExposureIndexZeroBased"] == 2 * plane + channel
            )
            assert stamps["recordedSpanSeconds"] == 20.547
            assert stamps["selectedExposureElapsedSeconds"] == plane * 20.547
            assert stamps["firstRecordedUtc"] == "2026-08-27T13:39:10.5420000Z"
            assert (
                metadata["timing"]["originalPhotonMacrotimesAvailable"]
                is False
            )
            assert metadata["timing"]["linePeriod"]["value"] is None
    assert (
        acquisition_metadata(other, 0)["acquisitionSettings"][
            "DetectorDyeName"
        ]["value"]
        == "Other dye"
    )
    unassociated = acquisition_metadata(
        replace(dataset, detector_name="Unknown"), 0
    )
    assert unassociated["imageTimestamps"]["selectedExposureUtc"] is None


def test_invalid_selected_setting_and_multisequence_do_not_borrow(raw_dataset):
    """Reject invalid settings and values from another sequence."""
    dataset = _dataset(raw_dataset)
    xml = _original_xml().replace(
        'PixelDwellTime="1.4e-6"',
        'PixelDwellTime="nan" NumericalAperture="nan"',
    )
    settings = acquisition_metadata(
        replace(dataset, source_acquisition_xml=xml), 0
    )["acquisitionSettings"]
    assert settings["PixelDwellTime"]["value"] is None
    assert settings["NumericalAperture"]["value"] is None
    multi = acquisition_metadata(
        replace(dataset, sequence_count=2, sequence_name="Other sequence"), 0
    )
    assert "ScanSpeed" not in multi["acquisitionSettings"]
    assert "DetectorDyeName" not in multi["acquisitionSettings"]
    assert multi["imageTimestamps"]["selectedExposureUtc"] is None


@pytest.mark.parametrize("kind", ["ics", "ptu"])
def test_settings_are_embedded_and_in_readable_reports(
    raw_dataset, tmp_path, kind
):
    """Both formats retain image settings without changing photons."""
    dataset = replace(_dataset(raw_dataset), recorded_plane_count=1)
    options = {"event_flag_mask": 256}
    if kind == "ics":
        result = export_ics_blocks(
            [dataset], tmp_path, IcsExportOptions(bins=32, **options)
        )[0]
    else:
        result = export_ptu_blocks(
            [dataset], tmp_path, PtuExportOptions(**options)
        )[0]
    assert result["status"] == "exported", result
    target = Path(result["path"])
    sidecar = json.loads(Path(result["sidecar"]).read_text(encoding="utf8"))
    expected = sidecar["acquisitionMetadata"]
    if kind == "ics":
        image = read_ics(target)
        assert image.counts.sum() == 6
        header = target.read_bytes().split(b"end\t\n", 1)[0]
        assert b"sensor\ts_params\tNumAperture\t0.75\n" in header
        chunks = sorted(
            key
            for key in image.header
            if key.startswith("history/LeicaMetadata_")
        )
        embedded = json.loads("".join(image.header[key][0] for key in chunks))
    else:
        tags = {
            tag["ident"]: tag["value"] for tag in parse_ptu(target)["tags"]
        }
        acquisition, comment = tags["Leica_Acquisition"], tags["File_Comment"]
        assert isinstance(acquisition, str) and isinstance(comment, str)
        embedded = json.loads(acquisition)
        assert "20x DRY" in comment
    assert embedded["acquisitionSettings"] == expected["acquisitionSettings"]
    assert embedded["imageTimestamps"] == expected["imageTimestamps"]
    report = Path(result["metadataReports"]["html"]).read_text(encoding="utf8")
    assert "20x DRY" in report
    assert "13:39:10.5420000Z" in report
    assert "Other dye" not in report
    assert "Source Z label" not in report
    with Path(result["metadataReports"]["csv"]).open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = {row["Field"]: row for row in csv.DictReader(stream)}
    assert float(rows["Source Z position"]["Value"]) == pytest.approx(-75)


@pytest.mark.real_data
def test_iahf_metadata_matches_lasx_reference():
    """Check the supplied two-channel stack against the LAS X report."""
    # LAS X PDF: 6 Z planes, 10 µm spacing, -74.58 µm first Z,
    # 20x/0.75 DRY objective, 2.4 zoom, 400 Hz, 1.4 µs, 3% at 735 nm.
    source = example_path("Autofluorescence.lif")
    if source is None:
        pytest.skip("Optional example LIF is unavailable")
    channels = [
        dataset
        for dataset in scan_lif(source)
        if dataset.acquisition_name == "IAHF"
    ]
    assert len(channels) == 2
    for dataset in channels:
        for plane in range(6):
            metadata = acquisition_metadata(dataset, plane)
            assert metadata["plane"]["sourceZPositionMetres"] == pytest.approx(
                -7.457941e-5 + plane * 1.0000238e-5
            )
            stamps = metadata["imageTimestamps"]
            assert stamps["recordedSpanSeconds"] == 102.735
            assert stamps["selectedExposureElapsedSeconds"] == pytest.approx(
                plane * 20.547
            )
            assert (
                stamps["selectedExposureIndexZeroBased"]
                == 2 * plane + dataset.channel_index
            )
            settings = metadata["acquisitionSettings"]
            assert settings["NumericalAperture"]["value"] == 0.75
            assert settings["Magnification"]["value"] == 20
            assert settings["Zoom"]["value"] == 2.4
            assert settings["ScanSpeed"]["value"] == 400
            assert settings["PixelDwellTime"]["value"] == pytest.approx(1.4)
            assert settings["LaserIntensity735"]["value"] == 3
            assert metadata["timing"]["linePeriod"]["value"] is None
            assert metadata["timing"]["framePeriod"]["value"] is None
            emission = metadata["opticalMetadata"]["emission"][
                "nominalBoundsNm"
            ]
            assert emission == (
                [440, 500] if dataset.channel_index == 0 else [530, 600]
            )
