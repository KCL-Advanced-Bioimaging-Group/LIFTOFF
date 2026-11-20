"""Keep nominal laser settings separate from actual recorded timing."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from leica_flim_converter import source_acquisition
from leica_flim_converter.acquisition_metadata import acquisition_metadata
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.repetition_rate import repetition_rate_text
from leica_flim_converter.source_acquisition import selected_repetition_rate
from leica_flim_converter.timing import numeric_time_window


def rate_dataset(template: DatasetInfo, setting: str = "80") -> DatasetInfo:
    """Include misleading acquisition and other-sequence settings."""
    xml = f"""<Element><Data><Image>
    <Attachment Name="HardwareSetting">
    <ATLConfocalSettingDefinition UserSettingName="Acquisition">
      <Laser LaserName="WLL" LightSourceType="4" PulsePickerRatio="10"/>
    </ATLConfocalSettingDefinition>
    <LDM_Block_Sequential><LDM_Block_Sequential_List>
      <ATLConfocalSettingDefinition UserSettingName="Saved"
       IsEnabledForScanning="0">
        <Detector Channel="3" IsActive="1"/>
        <Laser LaserName="WLL" LightSourceType="4" PulsePickerRatio="20"/>
      </ATLConfocalSettingDefinition>
      <ATLConfocalSettingDefinition UserSettingName="Setting 1"
       IsEnabledForScanning="1">
        <Detector Channel="3" IsActive="1"/>
        <Laser LaserName="WLL" LightSourceType="4"
         PulsePickerRatio="{setting}"/>
        <Laser LaserName="MP" LightSourceType="3"/>
      </ATLConfocalSettingDefinition>
      <ATLConfocalSettingDefinition UserSettingName="Setting 2"
       IsEnabledForScanning="1">
        <Detector Channel="5" IsActive="1"/>
        <Laser LaserName="WLL" LightSourceType="4" PulsePickerRatio="40"/>
      </ATLConfocalSettingDefinition>
    </LDM_Block_Sequential_List></LDM_Block_Sequential>
    </Attachment></Image></Data></Element>"""
    return replace(
        template,
        laser_frequency_hz=78.02e6,
        detector_identifier="3",
        sequence_count=2,
        sequence_name="Setting 1",
        excitation_sources=("WLL",),
        source_acquisition_xml=xml,
    )


@pytest.mark.parametrize("setting", ["10", "20", "40", "80"])
def test_recorded_rate_setting_and_actual_are_distinct(raw_dataset, setting):
    """Read the active source setting separately from actual timing."""
    dataset = rate_dataset(raw_dataset, setting)
    rate = selected_repetition_rate(dataset)
    assert rate["value"] == float(setting)
    assert rate["unit"] == "MHz"
    assert rate["sourceValue"] == setting
    assert "sequential-list" in rate["source"]
    assert repetition_rate_text(dataset) == (
        f"{setting} MHz (selected) / 78.02 MHz (actual)"
    )
    assert (
        acquisition_metadata(dataset)["acquisitionSettings"][
            "LaserRepetitionRate"
        ]
        == rate
    )


def test_rate_metadata_is_reused_per_dataset(raw_dataset, monkeypatch):
    """Reuse the parsed rate and resolve replacement metadata afresh."""
    read_image = Mock(wraps=source_acquisition.original_image)
    monkeypatch.setattr(source_acquisition, "original_image", read_image)
    dataset = rate_dataset(raw_dataset)

    metadata = dataset.selected_rate_metadata
    metadata["value"] = 20
    assert numeric_time_window(dataset).frequency.value == 80e6
    assert (
        repetition_rate_text(dataset)
        == "80 MHz (selected) / 78.02 MHz (actual)"
    )
    read_image.assert_called_once_with(dataset)

    other = replace(
        dataset, sequence_name="Setting 2", detector_identifier="5"
    )
    assert numeric_time_window(other).frequency.value == 40e6
    assert read_image.call_count == 2


@pytest.mark.parametrize("setting", ["0", "-80", "nan", "inf", "invalid"])
def test_invalid_selected_rate_cannot_inherit_a_saved_value(
    raw_dataset, setting
):
    """An explicitly invalid local rate stays unavailable."""
    dataset = rate_dataset(raw_dataset, setting)
    assert selected_repetition_rate(dataset)["value"] is None
    assert repetition_rate_text(dataset) == (
        "Unavailable (selected) / 78.02 MHz (actual)"
    )


def test_mp_source_cannot_borrow_the_wll_setting(raw_dataset):
    """Matching the detector's excitation source is required."""
    dataset = replace(rate_dataset(raw_dataset), excitation_sources=("MP",))
    assert not selected_repetition_rate(dataset)
    assert repetition_rate_text(dataset) == (
        "Unavailable (selected) / 78.02 MHz (actual)"
    )


@pytest.mark.parametrize("actual", [None, 0, float("nan"), float("inf")])
def test_missing_actual_rate_is_not_fabricated(raw_dataset, actual):
    """Do not use a selected nominal setting as measured timing."""
    dataset = replace(rate_dataset(raw_dataset), laser_frequency_hz=actual)
    assert repetition_rate_text(dataset) == (
        "80 MHz (selected) / Unavailable (actual)"
    )
