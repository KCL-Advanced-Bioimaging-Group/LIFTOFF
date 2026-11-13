"""Resolve detector routes and excitation from acquisition metadata."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import replace

import lif_flim_forensics as lif
from leica_xml import parse_xml

from .data_types import RawChannel
from .dataset import DatasetInfo
from .optical_metadata import EmissionBand, read_emission_band


def positive_number(text: str | None) -> float | None:
    """Accept only finite, positive physical values."""
    try:
        value = float(text or "0")
    except ValueError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _detector_record(
    detector: ET.Element, index: int, channel: ET.Element | None = None
) -> RawChannel:
    excitation = positive_number(detector.findtext("Excitation"))
    return {
        "index": index,
        "name": detector.findtext("Name") or None,
        "identifier": detector.findtext("Identifier") or None,
        "color": (
            channel.findtext("ColorPalette") if channel is not None else None
        )
        or detector.findtext("ColorPalette")
        or None,
        "excitation_nm": excitation * 1e9 if excitation is not None else None,
    }


def raw_channels(context: str) -> list[RawChannel]:
    """Follow references with sequence-local detector IDs."""
    raw = raw_sequence_root(context)
    if raw is None:
        return []
    sequences = raw.findall("Sequence/SequenceItem")
    detectors = [item.findall("Detectors/Detectors") for item in sequences]
    channels = raw.findall("Channels/Channel")
    records: list[RawChannel] = []
    for index, channel in enumerate(channels):
        reference = channel.find("Detectors/DetectorReferences")
        if reference is None:
            continue
        try:
            sequence_index = int(reference.findtext("SequenceItemIndex", "0"))
            detector_index = int(reference.findtext("DetectorIndex", "0"))
            detector = (
                detectors[sequence_index][detector_index]
                if sequence_index >= 0 and detector_index >= 0
                else None
            )
        except ValueError, IndexError:
            continue
        if detector is not None:
            record = _detector_record(detector, index, channel)
            record.update(
                sequence_index=sequence_index,
                detector_index=int(detector.findtext("Detector", "0")),
                detector_count=max(
                    int(item.findtext("Detector", "0"))
                    for item in detectors[sequence_index]
                )
                + 1,
                sequence_count=len(sequence_indices(context)) or 1,
            )
            records.append(record)
    if not channels:
        for sequence_index in sequence_indices(context):
            route_count = (
                max(
                    int(item.findtext("Detector", "0"))
                    for item in detectors[sequence_index]
                )
                + 1
            )
            for detector in detectors[sequence_index]:
                record = _detector_record(detector, len(records))
                record.update(
                    sequence_index=sequence_index,
                    detector_index=int(detector.findtext("Detector", "0")),
                    detector_count=route_count,
                    sequence_count=len(sequence_indices(context)),
                )
                records.append(record)
    return records


def raw_sequence_root(context: str) -> ET.Element | None:
    """Read the most recent complete RawData description."""
    matches = list(
        re.finditer(r"<RawData\b[^>]*>.*?</RawData>", context, re.DOTALL)
    )
    if not matches:
        return None
    try:
        return parse_xml(matches[-1].group())
    except ET.ParseError:
        return None


def sequence_indices(context: str) -> tuple[int, ...]:
    """Keep source identities for acquired scan settings."""
    raw = raw_sequence_root(context)
    return (
        tuple(
            index
            for index, item in enumerate(raw.findall("Sequence/SequenceItem"))
            if item.findtext("HasRawData", "true").lower() != "false"
        )
        if raw is not None
        else ()
    )


def sequence_context(
    context: str, dataset: DatasetInfo
) -> tuple[str, str | None]:
    """Scope optical settings to the selected acquired sequence."""
    if dataset.sequence_count <= 1:
        return context, None
    indices = sequence_indices(context)
    configs = []
    for block in re.finditer(
        r"<LDM_Block_Sequential_List\b[^>]*>(.*?)"
        r"</LDM_Block_Sequential_List>",
        context,
        re.DOTALL,
    ):
        configs = [
            (match.group(), lif.parse_attrs(match.group(1)))
            for match in re.finditer(
                r"<ATLConfocalSettingDefinition\b([^>]*)>(.*?)"
                r"</ATLConfocalSettingDefinition>",
                block.group(1),
                re.DOTALL,
            )
            if lif.parse_attrs(match.group(1)).get("IsEnabledForScanning")
            == "1"
        ]
    if len(configs) != len(indices) or dataset.sequence_index not in indices:
        return "", None
    body, attributes = configs[indices.index(dataset.sequence_index)]
    laser_names = "".join(
        match.group() for match in re.finditer(r"<Laser\b[^>]*>", context)
    )
    return body + laser_names, attributes.get("UserSettingName")


def acquisition_context(xml: str, dataset: DatasetInfo) -> str:
    """Limit microscope settings to this acquisition's ancestry."""
    stack: list[int] = []
    memory_index = xml.find(f'MemoryBlockID="{dataset.memory_id}"')
    if memory_index < 0:
        return ""
    for match in re.finditer(
        r"<Element\b[^>]*>|</Element\s*>", xml[:memory_index]
    ):
        if match.group().startswith("</"):
            if stack:
                stack.pop()
        elif not match.group().endswith("/>"):
            stack.append(match.start())
    for start in reversed(stack):
        end = xml.find(">", start)
        attributes = lif.parse_attrs(xml[start + len("<Element") : end])
        if attributes.get("Name") == dataset.acquisition_name:
            return xml[start:memory_index]
    return ""


def _detector_settings(context: str, dataset: DatasetInfo) -> list[str]:
    """Select enabled scan settings for this detector's excitation."""
    if not dataset.detector_identifier:
        return []
    enabled: list[str] = []
    fallback: list[str] = []
    for match in re.finditer(
        r"<ATLConfocalSettingDefinition\b([^>]*)>(.*?)"
        r"</ATLConfocalSettingDefinition>",
        context,
        re.DOTALL,
    ):
        attributes = lif.parse_attrs(match.group(1))
        if attributes.get("IsEnabledForScanning") == "0":
            continue
        body = match.group(2)
        active = any(
            attrs.get("Channel") == dataset.detector_identifier
            and attrs.get("IsActive") == "1"
            for detector in re.finditer(r"<Detector\b([^>]*)>", body)
            if (attrs := lif.parse_attrs(detector.group(1)))
        )
        if not active:
            continue
        if attributes.get("IsEnabledForScanning") == "1":
            enabled.append(match.group())
        else:
            fallback = [match.group()]
    return enabled or fallback


def _active_wavelengths(context: str) -> set[float]:
    wavelengths: set[float] = set()
    for laser in re.finditer(r"<LaserLineSetting\b([^>]*)>", context):
        attributes = lif.parse_attrs(laser.group(1))
        wavelength = positive_number(attributes.get("LaserLine"))
        if (
            wavelength is not None
            and positive_number(attributes.get("IntensityDev")) is not None
            and attributes.get("LineDeactivationFlags", "0") == "0"
        ):
            wavelengths.add(wavelength)
    return wavelengths


def emission_band(context: str, dataset: DatasetInfo) -> EmissionBand | None:
    """Use the same active detector scope for every light source."""
    if not dataset.detector_identifier:
        return None
    settings = _detector_settings(context, dataset)
    band = read_emission_band("".join(settings), dataset.detector_identifier)
    if band is not None or dataset.sequence_count > 1 or not settings:
        return band
    if any(
        lif.parse_attrs(match.group(1)).get("Channel")
        == dataset.detector_identifier
        for setting in settings
        for match in re.finditer(r"<MultiBand\b([^>]*)>", setting)
    ):
        return None
    # A single sequence can inherit its sequential master's bands.
    masters = list(
        re.finditer(
            r"<LDM_Block_Sequential_Master\b[^>]*>(.*?)"
            r"</LDM_Block_Sequential_Master>",
            context,
            re.DOTALL,
        )
    )
    if not masters:
        return None
    band = read_emission_band(
        masters[-1].group(1), dataset.detector_identifier
    )
    return (
        replace(band, source_scope="sequential-master")
        if band is not None
        else None
    )


def excitation_wavelengths(
    context: str, dataset: DatasetInfo
) -> tuple[float, ...]:
    """Use detector excitation or active sequential laser settings."""
    if dataset.excitation_wavelengths_nm:
        return dataset.excitation_wavelengths_nm
    if not dataset.detector_identifier:
        return ()
    wavelengths: set[float] = set()
    for body in _detector_settings(context, dataset):
        wavelengths.update(_active_wavelengths(body))
    return tuple(sorted(wavelengths))


def _laser_names(context: str) -> dict[str, str]:
    names = {}
    for laser in re.finditer(r"<Laser\b([^>]*)>", context):
        attributes = lif.parse_attrs(laser.group(1))
        source = attributes.get("LightSourceName")
        name = attributes.get("LaserName")
        if source and name:
            names[source] = name
    return names


def excitation_sources(
    context: str, dataset: DatasetInfo, wavelengths: tuple[float, ...]
) -> tuple[str | None, ...]:
    """Map active laser lines to their declared source name."""
    lines: list[tuple[float, str]] = []
    names = _laser_names(context)
    for body in _detector_settings(context, dataset):
        local_names = {**names, **_laser_names(body)}
        for aotf in re.finditer(
            r"<Aotf\b([^>]*)>(.*?)</Aotf>", body, re.DOTALL
        ):
            attributes = lif.parse_attrs(aotf.group(1))
            source = attributes.get("LightSourceName")
            if source:
                name = local_names.get(source, source)
                lines.extend(
                    (wavelength, name)
                    for wavelength in _active_wavelengths(aotf.group(2))
                )
    return tuple(
        " + ".join(
            sorted(
                {
                    source
                    for value, source in lines
                    if math.isclose(
                        value, wavelength, rel_tol=1e-6, abs_tol=1e-4
                    )
                }
            )
        )
        or None
        for wavelength in wavelengths
    )
