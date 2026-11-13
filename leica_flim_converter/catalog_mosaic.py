"""Validate Navigator tile geometry against stage and frame indexes."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import replace

import lif_flim_forensics as lif
from leica_xml import parse_xml

from .dataset import DatasetInfo
from .mosaic import MosaicLayout, TilePosition


def _tile_attachment(context: str) -> ET.Element:
    for match in re.finditer(
        r"<Attachment\b([^>]*)>(.*?)</Attachment>", context, re.DOTALL
    ):
        if lif.parse_attrs(match.group(1)).get("Name") == "TileScanInfo":
            return parse_xml(match.group())
    raise ValueError("Mosaic TileScanInfo is missing")


def _layout(context: str, raw_context: str, count: int) -> MosaicLayout:
    attachment = _tile_attachment(context)
    records = attachment.findall("Tile")
    stages = [
        parse_xml(match.group())
        for match in re.finditer(
            r"<StagePositions\b[^>]*>.*?</StagePositions>",
            raw_context,
            re.DOTALL,
        )
    ]
    if len(records) != count or len(stages) != count:
        raise ValueError("Mosaic tile/stage counts differ from the S axis")
    fields = [
        (int(item.attrib["FieldX"]), int(item.attrib["FieldY"]))
        for item in records
    ]
    xs, ys = sorted({x for x, _y in fields}), sorted({y for _x, y in fields})
    if (
        len(set(fields)) != count
        or len(xs) * len(ys) != count
        or any(
            following != first + 1
            for values in (xs, ys)
            for first, following in zip(values, values[1:], strict=False)
        )
    ):
        raise ValueError("Mosaic fields do not form a unique rectangular grid")
    flip_x, flip_y, swap = _orientation(attachment)
    columns, rows = (len(ys), len(xs)) if swap else (len(xs), len(ys))
    positions = [
        tuple(float(record.attrib[f"Pos{axis}"]) for axis in "XYZ")
        for record in records
    ]
    tiles = []
    matched = set()
    for stage in stages:
        position = tuple(float(stage.findtext(axis, "nan")) for axis in "XYZ")
        candidates = [
            index
            for index, other in enumerate(positions)
            if all(
                math.isfinite(value)
                and math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-12)
                for value, target in zip(position, other, strict=True)
            )
        ]
        if len(candidates) != 1 or candidates[0] in matched:
            raise ValueError(
                "Mosaic stage positions are ambiguous or duplicated"
            )
        index = candidates[0]
        matched.add(index)
        field_x, field_y = fields[index]
        column, row = xs.index(field_x), ys.index(field_y)
        if swap:
            column, row = row, column
        if flip_x:
            column = columns - 1 - column
        if flip_y:
            row = rows - 1 - row
        tiles.append(TilePosition(column, row, field_x, field_y, *position))
    return MosaicLayout(columns, rows, tuple(tiles), flip_x, flip_y, swap)


def _orientation(attachment: ET.Element) -> tuple[bool, bool, bool]:
    flags = [
        attachment.get(name, "0") for name in ("FlipX", "FlipY", "SwapXY")
    ]
    if any(value not in ("0", "1") for value in flags):
        raise ValueError("Invalid mosaic orientation flags")
    return flags[0] == "1", flags[1] == "1", flags[2] == "1"


def attach_mosaic(
    dataset: DatasetInfo, acquisition: str, raw_context: str
) -> DatasetInfo:
    """Validate each tile's owned rows before allowing decoding."""
    if dataset.stage_count <= 1:
        return dataset
    try:
        layout = _layout(acquisition, raw_context, dataset.stage_count)
        if dataset.repetition_storage_model == "unresolved":
            raise ValueError(dataset.dimension_status)
        if (
            dataset.storage_format == "lmsraw"
            and len(dataset.plane_row_starts) != dataset.plane_count
        ):
            raise ValueError("Mosaic FrameOffsets table is missing or invalid")
        ranges = tuple(
            dataset.plane_row_range(plane)
            for plane in range(dataset.plane_count)
        )
        if any(length != dataset.rows_per_plane for _start, length in ranges):
            raise ValueError("Mosaic frame index has an incomplete tile")
        if (
            any(
                first + length != following
                for (first, length), (following, _next_length) in zip(
                    ranges, ranges[1:], strict=False
                )
            )
            and dataset.sequence_count == 1
        ):
            raise ValueError(
                "Mosaic frame offsets do not bound distinct tiles"
            )
        if dataset.sequence_count == 1 and (
            ranges[0][0] != 0 or sum(ranges[-1]) != dataset.decoded_rows
        ):
            raise ValueError("Mosaic frame offsets do not cover the row table")
        if sum(length for _start, length in ranges) != dataset.indexed_rows:
            raise ValueError("Mosaic row ranges do not cover the acquisition")
        return replace(
            dataset,
            mosaic=layout,
            plane_row_ranges=ranges,
            plane_row_starts=tuple(first for first, _length in ranges),
        )
    except (ValueError, KeyError, ET.ParseError) as error:
        return replace(
            dataset,
            repetition_storage_model="unresolved",
            dimension_status=f"Mosaic: {error}",
        )
