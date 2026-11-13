"""Spatial calibration, explicit units and original source values."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .source_acquisition import original_image

if TYPE_CHECKING:
    from .dataset import DatasetInfo

_METRES = {"m": 1.0, "mm": 1e-3, "um": 1e-6, "µm": 1e-6, "nm": 1e-9}


def finite_number(value) -> float | None:
    """Reject absent, malformed and non-finite calibration values."""
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if math.isfinite(number) else None


def positive_spacing(value) -> float | None:
    """A physical spacing must be finite and strictly positive."""
    number = finite_number(value)
    return number if number is not None and number > 0 else None


def dimension_calibration(axis: str, record: dict) -> dict:
    """Leica Length spans the first and last sample centres."""
    unit = record.get("Unit")
    multiplier = _METRES.get(unit) if isinstance(unit, str) else None
    length = finite_number(record.get("Length"))
    count = finite_number(record.get("NumberOfElements"))
    origin = finite_number(record.get("Origin"))
    spacing = None
    if (
        multiplier is not None
        and length is not None
        and count is not None
        and count > 1
        and count.is_integer()
    ):
        spacing = positive_spacing(length * multiplier / (count - 1))
    return {
        "axis": axis,
        "spacingMetres": spacing,
        "originMetres": origin * multiplier
        if origin is not None and multiplier is not None
        else None,
        "source": "Leica/DimensionDescription",
        "calculation": "Length / (NumberOfElements - 1)",
        "quality": "calculated" if spacing is not None else "unavailable",
        "sourceValues": dict(record),
    }


def voxel_calibration(axis: str, text: str | None, scope: str) -> dict:
    """Retain an explicit voxel-size string, in recorded metres."""
    spacing = positive_spacing(text)
    return {
        "axis": axis,
        "spacingMetres": spacing,
        "originMetres": None,
        "source": f"{scope}/VoxelSize{axis.upper()}",
        "calculation": "recorded voxel size",
        "quality": "recorded" if spacing is not None else "unavailable",
        "sourceValues": {"value": text, "unit": "m"},
    }


def spatial_calibration(dataset: DatasetInfo) -> dict:
    """Keep unknown axes in sample units, never fabricate metres."""
    sources = {
        item["axis"]: item for item in acquisition_spatial_sources(dataset)
    }
    axes = {}
    for axis in ("x", "y", "z"):
        source = sources.get(axis, {})
        value = (
            getattr(dataset, f"pixel_size_{axis}_m")
            if axis in ("x", "y")
            else source.get("spacingMetres")
        )
        spacing = positive_spacing(value)
        calibrated = spacing is not None
        quality = source.get("quality", "provided")
        if source and spacing != source.get("spacingMetres"):
            quality = "provided"
        axes[axis] = {
            "spacingMetres": spacing,
            "unit": "m" if calibrated else "plane" if axis == "z" else "pixel",
            "scale": spacing if calibrated else 1.0,
            "status": "calibrated" if calibrated else "unavailable",
            "quality": quality if calibrated else "unavailable",
            "source": source.get("source"),
            "sourceOriginMetres": source.get("originMetres"),
            "originSource": source.get("originSource", source.get("source")),
        }
    return {"axes": axes, "unknownAxisPolicy": "sample units; no metric scale"}


def acquisition_spatial_sources(dataset: DatasetInfo) -> tuple[dict, ...]:
    """Enrich raw voxel scales with a matching original image origin."""
    image = original_image(dataset)
    if (
        image is None
        or dataset.stage_count != 1
        or dataset.mosaic is not None
        or dataset.sequence_count != 1
    ):
        return dataset.spatial_sources
    dimensions = image.findall(
        "ImageDescription/Dimensions/DimensionDescription"
    )
    sources = []
    for source in dataset.spatial_sources:
        axis = source["axis"]
        count = {
            "x": dataset.width,
            "y": dataset.height,
            "z": dataset.z_count,
        }[axis]
        records = [
            dim
            for dim in dimensions
            if dim.get("DimID") == {"x": "1", "y": "2", "z": "3"}[axis]
            and finite_number(dim.get("NumberOfElements")) == count
        ]
        if source.get("originMetres") is None and len(records) == 1:
            original = dimension_calibration(axis, records[0].attrib)
            spacing = source.get("spacingMetres")
            step = original["spacingMetres"]
            if (
                spacing is not None
                and step is not None
                and math.isclose(spacing, step, rel_tol=1e-5)
                and original["originMetres"] is not None
            ):
                source = {
                    **source,
                    "originMetres": original["originMetres"],
                    "originSource": "Image/ImageDescription/Dimensions/"
                    "DimensionDescription",
                    "originSourceValues": dict(records[0].attrib),
                }
        sources.append(source)
    return tuple(sources)


def source_metadata(dataset: DatasetInfo) -> dict:
    """Preserve original records separately from interpreted values."""
    return {
        "scope": "selected Leica acquisition; may include other detectors",
        "acquisitionXml": dataset.source_acquisition_xml,
        "dimensionRecords": list(dataset.dimension_records),
        "spatialCalibration": list(acquisition_spatial_sources(dataset)),
    }
