"""Essential acquisition metadata shared by standalone exports."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .source_acquisition import (
    acquisition_settings,
    image_timestamps,
    original_image,
)
from .spatial_metadata import spatial_calibration
from .timing import recorded_timing
from .version import APPLICATION_NAME, APPLICATION_VERSION

if TYPE_CHECKING:
    from .dataset import DatasetInfo

ICS_METADATA_PREFIX = "LeicaMetadata_"
# Keep the entire history record within the length tested in TRI2 3.0.
ICS_HISTORY_RECORD_BYTES = 220


def acquisition_metadata(
    dataset: DatasetInfo,
    linear_plane: int | None = None,
    dimension_mode: str = "split",
) -> dict:
    """Describe the selected image without bulky source XML."""
    if (
        linear_plane is None
        and dimension_mode == "split"
        and dataset.plane_count == 1
    ):
        linear_plane = 0
    t_index = z_index = None
    if linear_plane is not None:
        t_index, z_index = dataset.plane_indices(linear_plane)
    timing = recorded_timing(dataset).metadata()
    timing.pop("timestampLists")
    sequence = dataset.sequence_metadata.copy()
    sequence.pop("planeRowRanges")
    mosaic = dataset.mosaic_metadata(linear_plane)
    if mosaic is not None and mosaic["tileIndexZeroBased"] is not None:
        mosaic["tiles"] = [
            tile
            for tile in mosaic["tiles"]
            if tile["indexZeroBased"] == mosaic["tileIndexZeroBased"]
        ]
    spatial = spatial_calibration(dataset)
    z_axis = spatial["axes"]["z"]
    z_origin, z_spacing = (
        z_axis["sourceOriginMetres"],
        z_axis["spacingMetres"],
    )
    image = original_image(dataset)
    return {
        "schema": "LeicaInterrogator.Acquisition",
        "schemaVersion": 1,
        "application": {
            "name": APPLICATION_NAME,
            "version": APPLICATION_VERSION,
        },
        "sourceFilename": dataset.source.name,
        "memoryBlockID": dataset.memory_id,
        "datasetKey": dataset.key,
        "leicaNames": {
            "acquisition": dataset.acquisition_name,
            "series": dataset.series_name,
            "channel": dataset.channel_name,
            "detector": dataset.detector_name,
            "timepoint": dataset.timepoint_name,
            "z": dataset.z_name,
        },
        "dimensions": {
            "width": dataset.width,
            "height": dataset.height,
            "zCount": dataset.z_count,
            "tCount": dataset.t_count,
            "stagePositionCount": dataset.stage_count,
            "channelCountInSource": dataset.channel_count,
            "exportedChannelIndexZeroBased": dataset.channel_index,
            "dimensionOrder": list(dataset.dimension_order),
        },
        "plane": {
            "mode": dimension_mode,
            "linearIndexZeroBased": linear_plane,
            "tIndexZeroBased": t_index,
            "zIndexZeroBased": z_index,
            "sourceZPositionMetres": z_origin + z_index * z_spacing
            if z_origin is not None
            and z_spacing is not None
            and z_index is not None
            else None,
        },
        "spatialCalibration": spatial,
        "sequence": sequence,
        "opticalMetadata": dataset.optical_metadata,
        "acquisitionSettings": acquisition_settings(image, dataset)
        if image is not None
        else {},
        "imageTimestamps": image_timestamps(image, dataset, linear_plane)
        if image is not None
        else {},
        "timing": timing,
        "mosaic": mosaic,
        "planeCoverage": dataset.plane_coverage_metadata,
        "repetitions": {
            "frames": dataset.frame_repetitions,
            "lines": dataset.line_repetitions,
            "storageModel": dataset.repetition_storage_model,
        },
    }


def metadata_json(metadata: dict) -> str:
    """ASCII JSON preserves Unicode and cannot inject header lines."""
    return json.dumps(
        metadata, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    )


def header_fields(metadata: dict) -> dict:
    """Expose useful scalar fields alongside the structured summary."""
    names, dimensions, plane = (
        metadata["leicaNames"],
        metadata["dimensions"],
        metadata["plane"],
    )
    fields = {
        "Leica_AcquisitionName": names["acquisition"],
        "Leica_SeriesName": names["series"],
        "Leica_ChannelName": names["channel"],
        "Leica_DetectorName": names["detector"],
        "Leica_Excitation": metadata["opticalMetadata"]["excitation"]["label"],
        "Leica_EmissionBand": metadata["sequence"]["emissionBand"],
        "Leica_ZCount": dimensions["zCount"],
        "Leica_TCount": dimensions["tCount"],
        "Leica_ZIndex": plane["zIndexZeroBased"],
        "Leica_TIndex": plane["tIndexZeroBased"],
        "Leica_PlaneMode": plane["mode"],
    }
    for axis, calibration in metadata["spatialCalibration"]["axes"].items():
        fields[f"Leica_SpatialUnit{axis.upper()}"] = calibration["unit"]
        fields[f"Leica_SpatialScale{axis.upper()}"] = calibration["scale"]
        fields[f"Leica_Calibration{axis.upper()}"] = calibration["status"]
    return {name: value for name, value in fields.items() if value is not None}


def ics_history(metadata: dict) -> str:
    """Embed full metadata using short ASCII history records."""
    records = []
    for name, value in header_fields(metadata).items():
        record = f"history\t{name}\t{json.dumps(value, ensure_ascii=True)}\n"
        if len(record) <= ICS_HISTORY_RECORD_BYTES:
            records.append(record)
    encoded = metadata_json(metadata)
    index = number = 0
    while index < len(encoded):
        prefix = f"history\t{ICS_METADATA_PREFIX}{number:04d}\t"
        end = index + ICS_HISTORY_RECORD_BYTES - len(prefix) - 1
        records.append(f"{prefix}{encoded[index:end]}\n")
        index = end
        number += 1
    return "".join(records)
