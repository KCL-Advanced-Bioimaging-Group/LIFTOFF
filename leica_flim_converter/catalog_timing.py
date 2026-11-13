"""Read timing from detector, sequence, then acquisition scope."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .catalog_detectors import positive_number
from .timing import AcquisitionTiming, TimingValue


def read_timing(
    raw: ET.Element, sequence: ET.Element, detector: ET.Element, context: str
) -> AcquisitionTiming:
    """Retain exact values and the scope that supplied each field."""
    scopes = (
        (detector, "Detector"),
        (sequence, "SequenceItem"),
        (raw, "RawData"),
    )

    def quantity(tag: str, units: str = "s") -> TimingValue:
        for scope, name in scopes:
            text = scope.findtext(tag)
            # An explicit invalid field cannot borrow another scope's
            # value.
            if text is not None:
                value = positive_number(text)
                return TimingValue(
                    value,
                    units,
                    f"{name}/{tag}",
                    "recorded" if value is not None else "unavailable",
                )
        return TimingValue(units=units)

    return AcquisitionTiming(
        clock=quantity("ClockPeriod"),
        laser_frequency=quantity("LaserPulseFrequency", "Hz"),
        pixel_dwell=quantity("PixelTime"),
        line_period=quantity("LineTime"),
        frame_period=quantity("FrameTime"),
        timestamp_lists_xml=tuple(
            re.findall(
                r"<TimeStampList\b[^>]*(?:/>|>.*?</TimeStampList>)",
                context,
                re.DOTALL,
            )
        ),
    )
