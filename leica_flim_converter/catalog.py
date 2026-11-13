"""Fast LIF catalog scanning for the multi-file preview GUI."""

from __future__ import annotations

import mmap
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np

import lif_flim_forensics as lif

from .catalog_detectors import (
    acquisition_context,
    emission_band,
    excitation_sources,
    excitation_wavelengths,
    sequence_context,
)
from .catalog_index import IndexCancelled, _locate_blocks_mapped
from .catalog_metadata import (
    _block_dimensions,
    _block_layout,
    _block_timing,
    _catalogue_groups,
    _channel_dataset,
)
from .dataset import DatasetInfo
from .linked_intensity import read_intensity_plane, sum_intensity_planes
from .raw_container import RawPreparedReader as RawPreparedDecoder

IndexProgress = Callable[[str], None]
CancelCheck = Callable[[], bool]


def _element_paths(xml: str) -> dict[str, tuple[str, ...]]:
    """Recover ancestry from Leica headers that are not always strict
    XML.
    """
    paths: dict[str, tuple[str, ...]] = {}
    stack: list[str] = []
    token = re.compile(
        "<Element\\b([^>]*)>|</Element\\s*>|<Memory\\b([^>]*)/>"
    )
    for match in token.finditer(xml):
        if match.group(1) is not None:
            stack.append(lif.parse_attrs(match.group(1)).get("Name", ""))
        elif match.group(2) is not None:
            memory_id = lif.parse_attrs(match.group(2)).get("MemoryBlockID")
            if memory_id:
                paths[memory_id] = tuple(name for name in stack if name)
        elif stack:
            stack.pop()
    return paths


def _enrich_dataset(dataset: DatasetInfo, xml: str) -> DatasetInfo:
    """Attach emission bands and only independently verified partial
    line indexes.
    """
    context = acquisition_context(xml, dataset)
    dataset = replace(
        dataset,
        source_acquisition_xml=_source_acquisition_xml(xml, context, dataset),
    )
    if dataset.acquisition_timing is not None:
        timestamps = tuple(
            re.findall(
                r"<TimeStampList\b[^>]*(?:/>|>.*?</TimeStampList>)",
                context,
                re.DOTALL,
            )
        )
        dataset = replace(
            dataset,
            acquisition_timing=replace(
                dataset.acquisition_timing, timestamp_lists_xml=timestamps
            ),
        )
    context, sequence_name = sequence_context(context, dataset)
    emission = emission_band(context, dataset)
    band = (
        emission.label if emission is not None else "Emission band unavailable"
    )
    wavelengths = excitation_wavelengths(context, dataset)
    return _with_partial_layout(
        replace(
            dataset,
            emission_filter_band=band,
            emission_band_metadata=emission,
            channel_name=band,
            original_channel_name=dataset.channel_name,
            original_channel_color=dataset.channel_color,
            sequence_name=sequence_name,
            excitation_wavelengths_nm=wavelengths,
            excitation_sources=excitation_sources(
                context, dataset, wavelengths
            ),
        )
    )


def _source_acquisition_xml(
    xml: str, context: str, dataset: DatasetInfo
) -> str | None:
    """Retain the original element, including trailing settings."""
    if not context:
        return None
    memory_index = xml.find(f'MemoryBlockID="{dataset.memory_id}"')
    start = memory_index - len(context)
    depth = 0
    for match in re.finditer(r"<Element\b[^>]*>|</Element\s*>", xml[start:]):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                return xml[start : start + match.end()]
        elif not match.group().endswith("/>"):
            depth += 1
    return context


def scan_lif(
    path: str | Path,
    progress: IndexProgress | None = None,
    cancelled: CancelCheck | None = None,
    allow_linear_fallback: bool = True,
) -> list[DatasetInfo]:
    """Index FLIM datasets using sparse record seeks, independent of
    payload size.
    """
    source = Path(path).expanduser().resolve()
    report = progress or (lambda _message: None)
    is_cancelled = cancelled or (lambda: False)
    result = []
    if is_cancelled():
        raise IndexCancelled("LIF indexing cancelled")
    report(f"Reading Leica header from {source.name}")
    with (
        source.open("rb") as handle,
        mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        xml, xml_end = lif.parse_lif_header(data)
        element_paths = _element_paths(xml)
        blocks = _locate_blocks_mapped(
            data,
            lif.memory_declarations(xml),
            xml_end,
            report,
            is_cancelled,
            allow_linear_fallback,
        )
        index, flim_blocks = _catalogue_groups(
            source, data, xml, blocks, element_paths
        )
        for block_index, block in enumerate(flim_blocks):
            if is_cancelled():
                raise IndexCancelled("LIF indexing cancelled")
            report(
                f"Cataloguing FLIM block {block_index + 1}/{len(flim_blocks)}"
            )
            next_flim_offset = (
                flim_blocks[block_index + 1].record_offset
                if block_index + 1 < len(flim_blocks)
                else len(data)
            )
            timing = _block_timing(index, block)
            dimensions = _block_dimensions(timing)
            layout = _block_layout(
                index, block, next_flim_offset, timing, dimensions
            )
            for channel_index in range(layout.channel_count):
                result.append(
                    _channel_dataset(
                        index, block, timing, dimensions, layout, channel_index
                    )
                )
    return [_enrich_dataset(dataset, xml) for dataset in result]


def load_intensity(data: bytes, dataset: DatasetInfo) -> np.ndarray | None:
    """Read a T/Z overview, preserving separate mosaic positions."""
    if dataset.intensity_start is None or dataset.intensity_end is None:
        return None
    if dataset.intensity_plane_starts:
        return sum_intensity_planes(
            dataset,
            (
                np.frombuffer(
                    data,
                    dtype="<f4",
                    count=dataset.width * dataset.height,
                    offset=start,
                ).reshape(dataset.height, dataset.width)
                for start in dataset.intensity_plane_starts
            ),
        )
    expected = dataset.width * dataset.height * 4
    available = dataset.intensity_end - dataset.intensity_start
    if available % expected:
        return None
    frames = available // expected
    movie = np.frombuffer(
        data,
        dtype="<f4",
        count=frames * dataset.width * dataset.height,
        offset=dataset.intensity_start,
    ).reshape(frames, dataset.height, dataset.width)
    return sum_intensity_planes(dataset, movie)


def load_intensity_movie(dataset: DatasetInfo) -> np.ndarray | None:
    """Compute load intensity movie."""
    if dataset.intensity_start is None or dataset.intensity_end is None:
        return None
    if dataset.intensity_plane_starts:
        planes = []
        for plane in range(dataset.plane_count):
            values = read_intensity_plane(dataset, plane)
            if values is None:
                return None
            planes.append(values)
        return np.stack(planes)
    expected = dataset.width * dataset.height * 4
    available = dataset.intensity_end - dataset.intensity_start
    if not expected or available % expected:
        return None
    with dataset.source.open("rb") as handle:
        handle.seek(dataset.intensity_start)
        payload = handle.read(available)
    return (
        np.frombuffer(payload, dtype="<f4")
        .copy()
        .reshape(available // expected, dataset.height, dataset.width)
    )


def _partial_explicit_candidate(dataset):
    if dataset.sequence_count > 1 or dataset.stage_count > 1:
        return False
    if (
        dataset.storage_format != "lmsraw"
        or dataset.repetition_storage_model != "unresolved"
        or dataset.line_repetitions <= 1
        or (dataset.frame_repetitions < 1)
        or (dataset.plane_count < 1)
    ):
        return False
    in_row_expected = (
        int(dataset.height)
        * int(dataset.plane_count)
        * int(dataset.frame_repetitions)
    )
    explicit_expected = in_row_expected * int(dataset.line_repetitions)
    actual = int(dataset.decoded_rows)
    if not in_row_expected < actual < explicit_expected:
        return False
    starts = tuple(int(value) for value in dataset.plane_row_starts)
    if (
        len(starts) != int(dataset.plane_count)
        or not starts
        or starts[0] != 0
        or any(
            (
                left >= right
                for left, right in zip(starts, starts[1:], strict=False)
            )
        )
        or (starts[-1] >= actual)
    ):
        return False
    try:
        with RawPreparedDecoder(dataset):
            return True
    except OSError, RuntimeError, ValueError:
        return False


def _with_partial_layout(dataset: DatasetInfo) -> DatasetInfo:
    if not _partial_explicit_candidate(dataset):
        return dataset
    expected = (
        dataset.height
        * dataset.plane_count
        * dataset.frame_repetitions
        * dataset.line_repetitions
    )
    return replace(
        dataset,
        repetition_storage_model="explicit-line-repeat-rows",
        dimension_status=(
            "partial indexed acquisition: "
            f"{dataset.decoded_rows:,}"
            "/"
            f"{expected:,}"
            " explicit repetition rows; frame/line indexes confirmed"
        ),
    )


__all__ = ["DatasetInfo", "IndexCancelled", "scan_lif"]
