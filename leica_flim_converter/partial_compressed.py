"""Recover complete compressed planes with corroborating references."""

import mmap
import re
from dataclasses import replace

import numpy as np

import lif_flim_forensics as lif

from .compressed_index import compressed_index_error
from .dataset import DatasetInfo
from .linked_intensity import validated_intensity_starts


def _populated_extent(dataset, data, block, context):
    """Validate all detector references and find their joint extent."""
    channels = len(re.findall(r"<ChannelDescription\b", context))
    populated = np.zeros(dataset.plane_count, dtype=np.bool_)
    for channel in range(channels):
        starts = validated_intensity_starts(
            replace(dataset, channel_index=channel), block, context
        )
        for index, start in enumerate(starts):
            plane = np.frombuffer(
                data,
                dtype="<f4",
                count=dataset.width * dataset.height,
                offset=start,
            )
            if not np.all(np.isfinite(plane)) or np.any(plane < 0):
                raise ValueError("Invalid linked intensity values")
            populated[index] |= bool(np.any(plane > 0))
    nonzero = np.flatnonzero(populated)
    return int(nonzero[-1]) + 1 if nonzero.size else 0


def _prefix_model(dataset, extent):
    """Reject ambiguous repetition models and dark trailing planes."""
    if not 0 < extent < dataset.plane_count:
        return None
    models = [("frame-repeat-rows", 1)]
    if dataset.line_repetitions > 1:
        models = [
            ("in-row-line-accumulation", 1),
            ("explicit-line-repeat-rows", dataset.line_repetitions),
        ]
    candidates = []
    for model, multiplier in models:
        rows_per_plane = (
            dataset.height * dataset.frame_repetitions * multiplier
        )
        planes, remaining = divmod(dataset.decoded_rows, rows_per_plane)
        if not remaining and extent <= planes < dataset.plane_count:
            candidates.append((model, rows_per_plane, planes))
    if len(candidates) != 1:
        return None
    model, rows_per_plane, recorded = candidates[0]
    return (model, rows_per_plane) if recorded == extent else None


def attach_recorded_prefix(
    dataset: DatasetInfo,
    data: mmap.mmap,
    block: lif.MemoryBlock,
    intensity: lif.MemoryBlock | None,
    context: str,
) -> DatasetInfo:
    """Recover only a unique whole-plane prefix with empty references.

    A row deficit alone cannot identify missing planes or repetitions.
    Require a valid compressed index, validated C/T/Z reference strides,
    and an exactly matching populated extent across all detectors.
    Keep the declared axis sizes and calibration; restrict navigation
    and exports to the corroborated recorded prefix. Partial stage
    matrices need independent tile availability and remain unresolved.
    """
    if (
        dataset.storage_format != "compressed"
        or dataset.repetition_storage_model != "unresolved"
    ):
        return dataset
    if (
        dataset.stage_count != 1
        or dataset.plane_count <= 1
        or dataset.decoded_rows <= 0
        or intensity is None
        or dataset.intensity_start is None
    ):
        return dataset
    if compressed_index_error(data, block) is not None:
        return dataset
    try:
        extent = _populated_extent(dataset, data, intensity, context)
        starts = validated_intensity_starts(dataset, intensity, context)
    except KeyError, ValueError, OverflowError:
        return dataset
    candidate = _prefix_model(dataset, extent)
    if candidate is None:
        return dataset
    model, rows_per_plane = candidate
    return replace(
        dataset,
        recorded_plane_count=extent,
        frame_count=extent,
        repetition_storage_model=model,
        plane_row_starts=tuple(i * rows_per_plane for i in range(extent)),
        intensity_plane_starts=starts[:extent],
        dimension_status=(
            f"partial indexed acquisition: {extent} of "
            f"{dataset.declared_plane_count} planes recorded; "
            "trailing planes absent; compressed rows and linked "
            "intensity agree"
        ),
    )
