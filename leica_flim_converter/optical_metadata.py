"""Nominal wavelength labels and traceable emission boundaries."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import lif_flim_forensics as lif

from .data_types import JsonObject


def nominal_wavelength_nm(value: float | str) -> int:
    """Round positive wavelengths to whole nm, with half values up."""
    number = Decimal(str(value))
    if not number.is_finite() or number <= 0:
        raise ValueError("A wavelength must be finite and positive")
    return int(number.to_integral_value(rounding=ROUND_HALF_UP))


def wavelength_label(value: float | str) -> str:
    """Format a wavelength without implying sub-nm accuracy."""
    return str(nominal_wavelength_nm(value))


@dataclass(frozen=True)
class EmissionBand:
    """Preserve source text independently of the nominal band label."""

    source_bounds_nm: tuple[str, str]
    source_fields: tuple[str, str]
    detector_identifier: str
    setting_name: str | None = None
    source_scope: str = "detector-setting"

    @property
    def nominal_bounds_nm(self) -> tuple[int, int]:
        """Return the whole-nm setting shown in every user label."""
        begin, end = self.source_bounds_nm
        return nominal_wavelength_nm(begin), nominal_wavelength_nm(end)

    @property
    def label(self) -> str:
        """Describe a nominal emission band in nm."""
        begin, end = self.nominal_bounds_nm
        return f"{begin} - {end} nm"

    @property
    def metadata(self) -> JsonObject:
        """Separate nominal settings from unrounded source metadata."""
        begin, end = self.source_bounds_nm
        lower, upper = self.nominal_bounds_nm
        scope = (
            "LDM_Block_Sequential_Master/"
            if self.source_scope == "sequential-master"
            else ""
        )
        return {
            "label": self.label,
            "nominalBoundsNm": [lower, upper],
            "sourceBoundsNm": [float(begin), float(end)],
            "sourceTextBoundsNm": [begin, end],
            "sourceFields": list(self.source_fields),
            "settingName": self.setting_name,
            "sourceScope": self.source_scope,
            "metadataPath": (
                f"{scope}ATLConfocalSettingDefinition//MultiBand"
                f"[@Channel='{self.detector_identifier}']"
            ),
        }


def read_emission_band(
    context: str, detector_identifier: str
) -> EmissionBand | None:
    """Read one matched detector using complete attribute pairs."""
    bands = []
    for match in re.finditer(r"<MultiBand\b([^>]*)>", context, re.IGNORECASE):
        attributes = lif.parse_attrs(match.group(1))
        if attributes.get("Channel") != detector_identifier:
            continue
        for fields in (
            ("TargetWaveLengthBegin", "TargetWaveLengthEnd"),
            ("LeftWorld", "RightWorld"),
        ):
            begin, end = (attributes.get(field, "") for field in fields)
            if not begin or not end:
                continue
            try:
                lower, upper = Decimal(begin), Decimal(end)
                if (
                    not lower.is_finite()
                    or not upper.is_finite()
                    or not math.isfinite(float(lower))
                    or not math.isfinite(float(upper))
                    or not 0 < lower < upper
                ):
                    break
            except InvalidOperation:
                break
            bands.append(
                EmissionBand(
                    (begin, end),
                    fields,
                    detector_identifier,
                    setting_name=_setting_name(context[: match.start()]),
                )
            )
            break
    if (
        not bands
        or len({tuple(map(Decimal, band.source_bounds_nm)) for band in bands})
        != 1
    ):
        return None
    return bands[-1]


def _setting_name(context: str) -> str | None:
    settings = list(
        re.finditer(r"<ATLConfocalSettingDefinition\b([^>]*)>", context)
    )
    return (
        lif.parse_attrs(settings[-1].group(1)).get("UserSettingName")
        if settings
        else None
    )
