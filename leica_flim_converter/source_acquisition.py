"""Read acquisition settings from the original image."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from leica_xml import parse_xml

if TYPE_CHECKING:
    from .dataset import DatasetInfo


def original_image(dataset: DatasetInfo) -> ET.Element | None:
    """Exclude settings and dimensions from child intensity images."""
    try:
        root = parse_xml(dataset.source_acquisition_xml or "")
    except ET.ParseError:
        return None
    return root.find("./Data/Image")


# field, label, display unit, conversion from source units
_SETTINGS = (
    ("ObjectiveName", "Objective", "", None),
    ("Magnification", "Objective magnification", "×", 1),
    ("NumericalAperture", "Numerical aperture", "", 1),
    ("Immersion", "Objective immersion", "", None),
    ("RefractionIndex", "Refractive index", "", 1),
    ("MicroscopeModel", "Microscope model", "", None),
    ("SystemSerialNumber", "Instrument serial number", "", None),
    ("Zoom", "Scan zoom", "×", 1),
    ("RotatorAngle", "Scan rotation", "degrees", 1),
    ("ScanMode", "Scan mode", "", None),
    ("ScanDirectionXName", "X scan direction", "", None),
    ("ScanSpeed", "Nominal scan frequency", "Hz", 1),
    ("PixelDwellTime", "LAS X pixel dwell setting", "µs", 1e6),
    ("StagePosX", "Stage X position", "µm", 1e6),
    ("StagePosY", "Stage Y position", "µm", 1e6),
    ("ZPosition", "Focus Z setting (not selected plane position)", "µm", 1e6),
    ("Begin", "Stack Z begin setting", "µm", 1e6),
    ("End", "Stack Z end setting", "µm", 1e6),
    ("Pinhole", "Pinhole size setting", "µm", 1e6),
    ("PinholeAiry", "Pinhole setting", "Airy units", 1),
    (
        "EmissionWavelengthForPinholeAiryCalculation",
        "Pinhole Airy calculation wavelength",
        "nm",
        1,
    ),
    ("FrameAverage", "Frame averaging", "", 1),
    ("LineAverage", "Line averaging", "", 1),
    ("FrameAccumulation", "Frame accumulation", "", 1),
    ("Line_Accumulation", "Line accumulation", "", 1),
    ("IsRoiScanEnable", "ROI scanning enabled (0/1)", "", 1),
)
_COMMON = {field for field, *_ in _SETTINGS[:7]}


def _setting_scopes(image: ET.Element, dataset: DatasetInfo) -> list:
    hardware = image.findall("Attachment[@Name='HardwareSetting']")
    if len(hardware) != 1:
        return []
    attachment = hardware[0]
    enabled = [
        node
        for node in attachment.findall(
            "LDM_Block_Sequential/LDM_Block_Sequential_List/"
            "ATLConfocalSettingDefinition"
        )
        if node.get("IsEnabledForScanning") == "1"
    ]
    selected = [
        node
        for node in enabled
        if any(
            detector.get("Channel") == dataset.detector_identifier
            and detector.get("IsActive") == "1"
            for detector in node.iter("Detector")
        )
        and (
            dataset.sequence_name is None
            or node.get("UserSettingName") == dataset.sequence_name
        )
    ]
    scopes = []
    if len(selected) == 1:
        scopes.append((selected[0], "sequential-list", False))
    # Exclude disabled or saved sequential settings.
    for node in attachment.findall("ATLConfocalSettingDefinition"):
        if node.get("IsEnabledForScanning") != "0":
            scopes.append((node, "acquisition", dataset.sequence_count > 1))
    if dataset.sequence_count == 1:
        for node in attachment.findall(
            "LDM_Block_Sequential/LDM_Block_Sequential_Master/"
            "ATLConfocalSettingDefinition"
        ):
            scopes.append((node, "sequential-master", False))
    return scopes


def acquisition_settings(image: ET.Element, dataset: DatasetInfo) -> dict:
    """Keep units, scope and original source strings for every value."""
    result = {}
    scopes = _setting_scopes(image, dataset)
    for field, label, unit, factor in _SETTINGS:
        for node, scope, common_only in scopes:
            if common_only and field not in _COMMON:
                continue
            if field not in node.attrib:
                continue
            raw = node.get(field, "")
            value = raw.strip() or None
            if factor is not None:
                try:
                    number = float(raw) * factor
                    value = number if math.isfinite(number) else None
                except ValueError:
                    value = None
            result[field] = {
                "label": label,
                "value": value,
                "unit": unit,
                "quality": "recorded setting"
                if value is not None
                else "unavailable",
                "source": f"HardwareSetting/{scope}/"
                "ATLConfocalSettingDefinition"
                f"[@UserSettingName='{node.get('UserSettingName', '')}']"
                f"/@{field}",
                "sourceValue": raw,
            }
            break  # Explicit invalid settings must not inherit other values.
    _selected_detector_settings(result, scopes, dataset)
    _selected_laser_settings(result, scopes, dataset)
    hardware = image.find("Attachment[@Name='HardwareSetting']")
    if hardware is not None:
        for field, label in (
            ("Software", "Acquisition software"),
            ("SystemTypeName", "Acquisition system"),
        ):
            if value := hardware.get(field):
                result[field] = {
                    "label": label,
                    "value": value,
                    "unit": "",
                    "quality": "recorded",
                    "sourceValue": value,
                    "source": f"HardwareSetting/@{field}",
                }
    return result


def _selected_detector_settings(result, scopes, dataset):
    for field, label in (
        ("DyeName", "Selected detector dye label"),
        ("AcquisitionModeName", "Detector acquisition mode"),
        ("Gain", "Detector gain setting"),
        ("Offset", "Detector offset setting"),
    ):
        for node, scope, common_only in scopes:
            if common_only:
                continue
            detectors = [
                detector
                for detector in node.iter("Detector")
                if detector.get("Channel") == dataset.detector_identifier
                and detector.get("IsActive") == "1"
            ]
            if len(detectors) == 1 and field in detectors[0].attrib:
                value = detectors[0].get(field)
                result[f"Detector{field}"] = {
                    "label": label,
                    "value": value or None,
                    "unit": "",
                    "quality": "recorded detector setting",
                    "sourceValue": value,
                    "source": f"HardwareSetting/{scope}/"
                    f"Detector[@Channel='{dataset.detector_identifier}']"
                    f"/@{field}",
                }
                break


def _selected_laser_settings(result, scopes, dataset):
    for wavelength in dataset.excitation_wavelengths_nm:
        for node, scope, common_only in scopes:
            if common_only:
                continue
            lines = [
                line
                for line in node.iter("LaserLineSetting")
                if line.get("LaserLine") == f"{wavelength:g}"
                and line.get("LineDeactivationFlags", "0") == "0"
            ]
            if len(lines) != 1:
                continue
            raw = lines[0].get("IntensityDev")
            try:
                number = float(raw or "nan")
                value = (
                    number
                    if math.isfinite(number) and 0 <= number <= 100
                    else None
                )
            except ValueError:
                value = None
            result[f"LaserIntensity{wavelength:g}"] = {
                "label": f"{wavelength:g} nm laser intensity setting",
                "value": value,
                "unit": "%",
                "quality": "recorded setting; not specimen power",
                "sourceValue": raw,
                "source": f"HardwareSetting/{scope}/LaserLineSetting"
                f"[@LaserLine='{wavelength:g}']/@IntensityDev",
            }
            break


def _timestamp_index(image, dataset, plane, count):
    """Require matching channel identity, shape and strides."""
    if (
        plane is None
        or dataset.sequence_count != 1
        or dataset.stage_count != 1
    ):
        return None
    channels = image.findall("ImageDescription/Channels/ChannelDescription")
    if len(channels) != dataset.channel_count:
        return None
    matches = [
        index
        for index, channel in enumerate(channels)
        if any(
            prop.findtext("Key") == "DetectorName"
            and prop.findtext("Value") == dataset.detector_name
            for prop in channel.iter("ChannelProperty")
        )
    ]
    if len(matches) != 1:
        return None
    t_index, z_index = dataset.plane_indices(plane)
    sizes = {"3": dataset.z_count, "4": dataset.t_count}
    coords = {"3": z_index, "4": t_index}
    axes = []
    try:
        if len(channels) > 1:
            offsets = [
                int(channel.get("BytesInc", "-1")) for channel in channels
            ]
            step = offsets[1]
            if step <= 0 or offsets != [
                index * step for index in range(len(channels))
            ]:
                raise ValueError("Irregular channel strides")
            axes.append((step, len(channels), matches[0]))
        seen = set()
        for dim in image.findall(
            "ImageDescription/Dimensions/DimensionDescription"
        ):
            axis = dim.get("DimID")
            size = int(dim.get("NumberOfElements", "0"))
            if axis in ("1", "2"):
                if size != (dataset.width if axis == "1" else dataset.height):
                    raise ValueError("Image size mismatch")
                continue
            if axis not in sizes or axis in seen or size != sizes[axis]:
                raise ValueError("Unknown or mismatched image dimension")
            seen.add(axis)
            if size > 1:
                step = int(dim.get("BytesInc", "0"))
                if step <= 0:
                    raise ValueError("Invalid image stride")
                axes.append((step, size, coords[axis]))
        if any(size > 1 and axis not in seen for axis, size in sizes.items()):
            raise ValueError("Missing image dimension")
        axes.sort()
        index, stride = 0, 1
        previous_end = 0
        for step, size, coord in axes:
            if step <= previous_end:
                raise ValueError("Overlapping dimension strides")
            previous_end += step * (size - 1)
            index += stride * coord
            stride *= size
        return index if stride == count else None
    except ValueError, TypeError:
        return None


def _filetime_iso(ticks: int) -> str:
    # Integer arithmetic preserves the original 100 ns precision.
    seconds, remainder = divmod(ticks, 10_000_000)
    date = datetime(1601, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    return date.strftime("%Y-%m-%dT%H:%M:%S") + f".{remainder:07d}Z"


def image_timestamps(
    image: ET.Element, dataset: DatasetInfo, plane: int | None
) -> dict:
    """Read exposure times independently of photon hardware timing."""
    node = image.find("TimeStampList")
    if node is None:
        return {}
    result: dict = {
        "source": "Image/TimeStampList",
        "quality": "unavailable",
        "interpretation": "image timestamps; not individual photon timestamps",
        "encoding": "Windows FILETIME, 100 ns since 1601-01-01 UTC",
    }
    try:
        if node.get("NumberOfTimeStamps") is not None:
            values = [int(text, 16) for text in (node.text or "").split()]
            if len(values) != int(node.get("NumberOfTimeStamps", "0")):
                return result
        else:
            values = [
                (int(stamp.get("HighInteger", "0")) << 32)
                | int(stamp.get("LowInteger", "0"))
                for stamp in node.findall("TimeStamp")
            ]
        if not values or any(value <= 0 for value in values):
            return result
        # Scan timestamps need not be stored in chronological order.
        first, last = min(values), max(values)
        index = _timestamp_index(image, dataset, plane, len(values))
        result.update(
            {
                "quality": "recorded image timestamps",
                "count": len(values),
                "firstRecordedUtc": _filetime_iso(first),
                "lastRecordedUtc": _filetime_iso(last),
                "recordedSpanSeconds": (last - first) / 1e7,
                "selectedExposureIndexZeroBased": index,
                "selectedExposureUtc": _filetime_iso(values[index])
                if index is not None
                else None,
                "selectedExposureElapsedSeconds": (values[index] - first) / 1e7
                if index is not None
                else None,
                "association": "validated channel identity and dimension "
                "strides"
                if index is not None
                else "selected-plane association unavailable",
                "sourceFirstTicks100ns": str(first),
                "sourceLastTicks100ns": str(last),
            }
        )
    except ValueError, OverflowError:
        return {**result, "quality": "unavailable"}
    return result
