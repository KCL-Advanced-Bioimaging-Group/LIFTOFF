"""Bounded per-tile dataset views for the matrix preview."""

from dataclasses import replace

import numpy as np

from .dataset import DatasetInfo
from .linked_intensity import read_intensity_plane


def tile_view(dataset: DatasetInfo, index: int) -> DatasetInfo:
    """Keep a tile's T/Z planes and scientific identity separate."""
    if dataset.mosaic is None or dataset.tile_index is not None:
        raise ValueError("A tile view requires a validated mosaic acquisition")
    if not 0 <= index < dataset.stage_count:
        raise IndexError(index)
    planes = [
        plane
        for plane in range(dataset.plane_count)
        if dataset.plane_stage_index(plane) == index
    ]
    ranges = tuple(dataset.plane_row_range(plane) for plane in planes)
    starts = tuple(
        dataset.intensity_plane_starts[plane]
        for plane in planes
        if plane < len(dataset.intensity_plane_starts)
    )
    total = 0
    for plane in planes:
        values = read_intensity_plane(dataset, plane)
        if values is None:
            break
        total += int(np.rint(values).astype(np.uint64).sum())
    else:
        return _view(dataset, index, ranges, starts, total)
    return _view(dataset, index, ranges, starts, None)


def _view(dataset, index, ranges, starts, total) -> DatasetInfo:
    return replace(
        dataset,
        tile_index=index,
        plane_row_ranges=ranges,
        plane_row_starts=tuple(first for first, _length in ranges),
        intensity_plane_starts=starts,
        total_photons=total,
        thumbnail=None,
        frame_count=dataset.preview_plane_count,
        t_stride=(
            dataset.t_stride // dataset.stage_count
            if dataset.t_stride > dataset.stage_stride
            else dataset.t_stride
        ),
        z_stride=(
            dataset.z_stride // dataset.stage_count
            if dataset.z_stride > dataset.stage_stride
            else dataset.z_stride
        ),
    )
