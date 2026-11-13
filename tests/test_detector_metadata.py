"""Detector references, excitation scoping and optional preview data."""

from dataclasses import replace

import pytest

from leica_flim_converter.catalog_detectors import (
    acquisition_context,
    excitation_sources,
    excitation_wavelengths,
    raw_channels,
)
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui_helpers import _make_group_item_2


def test_sequence_local_detector_references() -> None:
    """Two sequence-local detector zeroes remain separate channels."""
    context = """
    <RawData><Channels>
      <Channel><Detectors><DetectorReferences>
        <SequenceItemIndex>0</SequenceItemIndex><DetectorIndex>0</DetectorIndex>
      </DetectorReferences></Detectors></Channel>
      <Channel><Detectors><DetectorReferences>
        <SequenceItemIndex>1</SequenceItemIndex><DetectorIndex>0</DetectorIndex>
      </DetectorReferences></Detectors></Channel>
    </Channels><Sequence>
      <SequenceItem><Detectors><Detectors><Detector>0</Detector>
        <Name>HyD NDD 2</Name><Identifier>1001</Identifier>
        <Excitation>1.04e-6</Excitation>
      </Detectors></Detectors></SequenceItem>
      <SequenceItem><Detectors><Detectors><Detector>0</Detector>
        <Name>HyD NDD 1</Name><Identifier>1000</Identifier>
        <Excitation>8.4e-7</Excitation>
      </Detectors></Detectors></SequenceItem>
    </Sequence></RawData>
    """
    channels = raw_channels(context)
    assert [item["identifier"] for item in channels] == ["1001", "1000"]
    assert [item["index"] for item in channels] == [0, 1]
    assert [item["excitation_nm"] for item in channels] == pytest.approx(
        [1040, 840]
    )


def _setting(channel: str, wavelength: int, enabled: str = "") -> str:
    return (
        f"<ATLConfocalSettingDefinition {enabled}>"
        f'<Detector Channel="{channel}" IsActive="1"/>'
        f'<LaserLineSetting LaserLine="{wavelength}" IntensityDev="1"/>'
        '<LaserLineSetting LaserLine="405" IntensityDev="0"/>'
        "</ATLConfocalSettingDefinition>"
    )


def test_excitation_uses_active_detector_setting(
    raw_dataset: DatasetInfo,
) -> None:
    """Ignore saved settings and other sequential detectors' lasers."""
    dataset = replace(raw_dataset, detector_identifier="1001")
    context = (
        _setting("1001", 450)
        + _setting("1001", 1040, 'IsEnabledForScanning="1"')
        + _setting("1000", 840, 'IsEnabledForScanning="1"')
        + _setting("1001", 488, 'IsEnabledForScanning="0"')
    )
    assert excitation_wavelengths(context, dataset) == (1040,)
    assert excitation_wavelengths(context, raw_dataset) == ()


def test_metadata_stays_in_acquisition_ancestry(
    raw_dataset: DatasetInfo,
) -> None:
    """Keep repeated names in closed branches out of metadata."""
    xml = (
        '<Element Name="Synthetic"><Old/></Element>'
        '<Element Name="Synthetic"><Current/>'
        '<Element Name="FLIM"><Memory MemoryBlockID="MemBlock_1"/>'
        "</Element></Element>"
    )
    context = acquisition_context(xml, raw_dataset)
    assert "<Current/>" in context
    assert "<Old/>" not in context


def test_excitation_source_uses_active_scan_route(
    raw_dataset: DatasetInfo,
) -> None:
    """Disambiguate lasers using the active source route."""
    dataset = replace(raw_dataset, detector_identifier="1001")
    context = (
        '<Laser LightSourceName="SuperContVisible Light" LaserName="WLL"/>'
        + _setting("1001", 488).replace(
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/>',
            '<Aotf LightSourceName="SuperContVisible Light">'
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/></Aotf>',
        )
        + _setting("1001", 488, 'IsEnabledForScanning="1"').replace(
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/>',
            '<Aotf LightSourceName="MP2">'
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/></Aotf>',
        )
    )
    assert excitation_sources(context, dataset, (488,)) == ("MP2",)
    assert excitation_sources(context, raw_dataset, (488,)) == (None,)


def test_excitation_source_resolves_declared_laser_name(
    raw_dataset: DatasetInfo,
) -> None:
    """Resolve the white light source's declared WLL name."""
    dataset = replace(raw_dataset, detector_identifier="2")
    context = (
        '<Laser LightSourceName="SuperContVisible Light" LaserName="WLL"/>'
        + _setting("2", 488, 'IsEnabledForScanning="1"').replace(
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/>',
            '<Aotf LightSourceName="SuperContVisible Light">'
            '<LaserLineSetting LaserLine="488" IntensityDev="1"/></Aotf>',
        )
    )
    # Detector wavelengths are in metres before conversion to nm.
    assert excitation_sources(context, dataset, (488.00000000000006,)) == (
        "WLL",
    )
    assert excitation_sources(context, dataset, (405,)) == (None,)


def test_list_label_contains_excitation(
    qapp, raw_dataset: DatasetInfo
) -> None:
    """Show excitation before emission beside thumbnails."""
    assert qapp is not None
    dataset = replace(
        raw_dataset,
        detector_name="HyD S 2",
        excitation_wavelengths_nm=(488,),
        excitation_sources=("WLL",),
        emission_filter_band="496 - 802 nm",
    )
    item = _make_group_item_2([dataset])
    assert "Channel 1 | Ex. 488 nm (WLL) / Em. 496 - 802 nm (HyD S 2)" in (
        item.text()
    )
    assert "excitation 488 nm (WLL)" in item.toolTip()
    assert "Ex. unavailable" in _make_group_item_2([raw_dataset]).text()
