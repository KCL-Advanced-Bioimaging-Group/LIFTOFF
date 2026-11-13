"""Readable export metadata tables for browsers and spreadsheets."""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from urllib.parse import quote

from .version import APPLICATION_NAME


@dataclass(frozen=True)
class MetadataRow:
    """One labelled value with its units and evidence."""

    section: str
    field: str
    value: str
    unit: str
    status: str
    source: str


def _display(value) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.12g}"
    if isinstance(value, (list, tuple)):
        return " / ".join(_display(item) for item in value)
    return str(value)


def _row(section, label, value, unit="", status="", source="") -> MetadataRow:
    return MetadataRow(
        section,
        label,
        _display(value),
        unit,
        "unavailable" if value is None else status,
        source or "",
    )


def _spatial_rows(metadata: dict) -> list[MetadataRow]:
    rows = []
    for axis, calibration in metadata["spatialCalibration"]["axes"].items():
        spacing = calibration["spacingMetres"]
        rows.append(
            _row(
                "Spatial calibration",
                f"{axis.upper()} sample spacing",
                spacing * 1e6 if spacing is not None else 1,
                "µm" if spacing is not None else calibration["unit"],
                calibration["quality"]
                if spacing is not None
                else "uncalibrated",
                calibration["source"],
            )
        )
    position = metadata["plane"]["sourceZPositionMetres"]
    rows.append(
        _row(
            "Spatial calibration",
            "Source Z position",
            position * 1e6 if position is not None else None,
            "µm",
            "calculated",
            "recorded Z origin + Z index × Z spacing",
        )
    )
    return rows


def _timing_rows(sidecar: dict) -> list[MetadataRow]:
    rows = []
    timing = sidecar["timing"]
    for key, label, factor, unit in (
        ("arrivalClock", "Native photon-arrival increment", 1e12, "ps"),
        ("laserFrequency", "Laser repetition rate", 1e-6, "MHz"),
        ("laserRepetitionPeriod", "Laser repetition period", 1e9, "ns"),
        ("pixelDwell", "Recorded pixel dwell", 1e6, "µs"),
        ("linePeriod", "Recorded line period", 1e3, "ms"),
        ("framePeriod", "Recorded frame period", 1, "s"),
    ):
        quantity = timing[key]
        value = quantity["value"]
        rows.append(
            _row(
                "Timing",
                label,
                value * factor if value is not None else None,
                unit,
                quantity["quality"],
                quantity["source"],
            )
        )
    grid = sidecar.get("histogramTiming")
    if grid:
        rows.extend(
            (
                _row("Timing", "Exported arrival-time bins", grid["bins"]),
                _row(
                    "Timing",
                    "Exported arrival-bin width",
                    grid["binWidthSeconds"] * 1e12,
                    "ps",
                    grid["quality"],
                    grid["binWidthSource"],
                ),
                _row(
                    "Timing",
                    "Exported arrival-time window",
                    grid["extentSeconds"] * 1e9,
                    "ns",
                    grid["windowQuality"],
                    grid["windowSource"],
                ),
            )
        )
    raster = sidecar.get("export", {}).get("rasterTiming")
    if raster:
        rows.extend(
            (
                _row(
                    "Timing",
                    "PTU raster timeline",
                    raster["quality"],
                    source="exported scan clock",
                ),
                _row(
                    "Timing",
                    "PTU raster pixel spacing",
                    raster["pixelSpacingSeconds"] * 1e6,
                    "µs",
                    raster["quality"],
                    "exported scan clock",
                ),
                _row(
                    "Timing",
                    "PTU raster fallback reason",
                    raster["fallbackReason"],
                ),
                _row("Timing", "PTU time origin", raster["timeOrigin"]),
            )
        )
    rows.append(
        _row(
            "Timing",
            "Original individual photon hardware timestamps",
            "Unavailable",
            status="unavailable",
            source="supported reduced Leica stream",
        )
    )
    return rows


def _acquisition_detail_rows(metadata: dict) -> list[MetadataRow]:
    rows = [
        _row(
            "Microscope and scan settings",
            setting["label"],
            setting["value"],
            setting["unit"],
            setting["quality"],
            setting["source"],
        )
        for setting in metadata.get("acquisitionSettings", {}).values()
    ]
    stamps = metadata.get("imageTimestamps", {})
    if stamps:
        rows.extend(
            _row(
                "Image timestamps",
                label,
                stamps.get(key),
                unit,
                stamps["quality"],
                stamps["source"],
            )
            for key, label, unit in (
                ("count", "Source image exposures (all channels)", ""),
                (
                    "firstRecordedUtc",
                    "First recorded image timestamp (UTC)",
                    "",
                ),
                ("lastRecordedUtc", "Last recorded image timestamp (UTC)", ""),
                (
                    "recordedSpanSeconds",
                    "Span of recorded image timestamps",
                    "s",
                ),
                (
                    "selectedExposureUtc",
                    "Selected image exposure timestamp (UTC)",
                    "",
                ),
                (
                    "selectedExposureElapsedSeconds",
                    "Selected image exposure elapsed time",
                    "s",
                ),
            )
        )
        rows.append(
            _row(
                "Image timestamps",
                "Timestamp association",
                stamps.get("association"),
            )
        )
    return rows


def _mosaic_rows(metadata: dict) -> list[MetadataRow]:
    mosaic = metadata.get("mosaic")
    if mosaic is None:
        return []
    rows = [
        _row("Tile identity", "Mosaic rows", mosaic["rows"]),
        _row("Tile identity", "Mosaic columns", mosaic["columns"]),
        _row(
            "Tile identity",
            "Tile index (zero-based)",
            mosaic["tileIndexZeroBased"],
        ),
    ]
    for tile in mosaic["tiles"]:
        for axis, value in zip(
            ("X", "Y", "Z"), tile["stagePositionMetres"], strict=True
        ):
            rows.append(
                _row(
                    "Tile identity",
                    f"Tile {tile['indexZeroBased']} stage {axis}",
                    value * 1e6,
                    "µm",
                    "recorded",
                    mosaic["metadataSource"],
                )
            )
    return rows


def metadata_rows(sidecar: dict) -> list[MetadataRow]:
    """Render a curated summary; detailed source XML stays in JSON."""
    metadata = sidecar["acquisitionMetadata"]
    export = sidecar.get("ics", sidecar.get("export", {}))
    rows = [
        _row("Acquisition", "Source file", sidecar["sourceLif"]),
        _row("Acquisition", "Exported file", export.get("path")),
        _row("Acquisition", "Source memory block", sidecar["memoryBlockID"]),
    ]
    rows.extend(
        _row(
            "Acquisition",
            "Source Z label" if label == "z" else label.title(),
            value,
        )
        for label, value in metadata["leicaNames"].items()
        if value is not None or label != "z"
    )
    rows.extend(
        _row("Image and plane identity", label, value)
        for label, value in (
            ("Image width", metadata["dimensions"]["width"]),
            ("Image height", metadata["dimensions"]["height"]),
            ("Source Z planes", metadata["dimensions"]["zCount"]),
            (
                "Source acquisition timepoints",
                metadata["dimensions"]["tCount"],
            ),
            ("Export plane mode", metadata["plane"]["mode"]),
            (
                "Source T index (zero-based)",
                metadata["plane"]["tIndexZeroBased"],
            ),
            (
                "Source Z index (zero-based)",
                metadata["plane"]["zIndexZeroBased"],
            ),
        )
    )
    rows.extend(_acquisition_detail_rows(metadata))
    optics = metadata["opticalMetadata"]
    rows.extend(
        (
            _row(
                "Optical settings",
                "Excitation",
                optics["excitation"]["label"],
                status="nominal setting"
                if optics["excitation"]["nominalWavelengthsNm"]
                else "unavailable",
            ),
            _row(
                "Optical settings",
                "Excitation source values",
                optics["excitation"]["sourceWavelengthsNm"] or None,
                "nm",
                "recorded source values",
            ),
            _row(
                "Optical settings",
                "Emission band",
                metadata["sequence"]["emissionBand"],
                status="nominal setting"
                if optics["emission"] is not None
                else "unavailable",
            ),
        )
    )
    if optics["emission"] is not None:
        rows.append(
            _row(
                "Optical settings",
                "Emission source bounds",
                optics["emission"]["sourceTextBoundsNm"],
                "nm",
                "original source text",
                optics["emission"]["metadataPath"],
            )
        )
    rows.extend(_spatial_rows(metadata))
    rows.extend(_mosaic_rows(metadata))
    rows.extend(_timing_rows(sidecar))
    selection = metadata.get("eventSelection", {})
    rows.append(
        _row(
            "Photon selection and counts",
            "Photon selection",
            selection.get("name"),
        )
    )
    accounting = sidecar.get("photonAccounting", sidecar.get("export", {}))
    for key, label in (
        ("selectedPhotons", "Selected photons before reflection exclusion"),
        (
            "exportedPhotons" if "photonAccounting" in sidecar else "photons",
            "Exported photons",
        ),
        ("excludedOutsideTimeWindow", "Photons outside arrival-time window"),
        ("excludedReflectionPhotons", "Excluded reflection photons"),
    ):
        if key in accounting:
            rows.append(
                _row(
                    "Photon selection and counts",
                    label,
                    accounting[key],
                    "photons",
                )
            )
    reflection = metadata.get("reflectionFilter", {})
    rows.append(
        _row(
            "Photon selection and counts",
            "Reflection exclusion enabled",
            reflection.get("enabled", False),
        )
    )
    if reflection.get("enabled"):
        rows.extend(
            _row(
                "Photon selection and counts",
                label,
                reflection[key],
                "native arrival bins",
                "inclusive boundary",
            )
            for key, label in (
                ("lowerNativeBin", "Reflection lower boundary"),
                ("upperNativeBin", "Reflection upper boundary"),
            )
        )
    rows.extend(
        _row("Header mappings", field, mapping)
        for field, mapping in metadata.get("headerMappings", {})
        .get("fields", {})
        .items()
    )
    reconstruction = sidecar["application"].get("reconstruction", {})
    rows.extend(
        (
            _row("Provenance", "Application", sidecar["application"]["name"]),
            _row(
                "Provenance",
                "Application version",
                sidecar["application"]["version"],
            ),
            _row(
                "Provenance",
                "Source revision",
                reconstruction.get("sourceCommit"),
            ),
            _row(
                "Provenance",
                "Source modified since revision",
                reconstruction.get("sourceModified"),
            ),
            _row(
                "Provenance",
                "Original Leica XML retained in JSON",
                sidecar["sourceMetadata"]["acquisitionXml"] is not None,
            ),
        )
    )
    for calibration in sidecar["sourceMetadata"]["spatialCalibration"]:
        rows.extend(
            _row(
                "Original calibration values",
                f"{calibration['axis'].upper()}: {field}",
                value,
                status="original source value",
                source=calibration["source"],
            )
            for field, value in calibration["sourceValues"].items()
        )
    return rows


def _spreadsheet_text(value: str) -> str:
    # Keep signed measurements numeric in Excel and other CSV readers.
    if re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value.strip()
    ):
        return value
    # Treat source labels resembling spreadsheet expressions as text.
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@"))
        else value
    )


def csv_report(rows: list[MetadataRow]) -> str:
    """A flat table opens directly in spreadsheet applications."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(("Section", "Field", "Value", "Unit", "Status", "Source"))
    for row in rows:
        writer.writerow(
            _spreadsheet_text(value)
            for value in (
                row.section,
                row.field,
                row.value,
                row.unit,
                row.status,
                row.source,
            )
        )
    return output.getvalue()


def _source_groups(
    rows: list[MetadataRow],
) -> list[tuple[str, list[MetadataRow]]]:
    """Share a source root only when multiple settings use it."""
    roots = [row.source.rpartition("/")[0] for row in rows]
    shared = {root for root in roots if root and roots.count(root) > 1}
    groups: dict[str, list[MetadataRow]] = {}
    for root, row in zip(roots, rows, strict=True):
        groups.setdefault(root + "/" if root in shared else "", []).append(row)
    return list(groups.items())


def _html_table(rows: list[MetadataRow], source_root: str = "") -> str:
    source_header = "Source"
    if source_root:
        source_header += (
            '<span class="source-root">Root: '
            f"{html.escape(source_root)}</span>"
        )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(value)}</td>"
            for value in (
                row.field,
                row.value,
                row.unit,
                row.status,
                row.source.removeprefix(source_root),
            )
        )
        + "</tr>"
        for row in rows
    )
    return (
        "<table><thead><tr><th>Field</th><th>Value</th><th>Unit</th>"
        f"<th>Status</th><th>{source_header}</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def html_report(target: Path, rows: list[MetadataRow]) -> str:
    """A self-contained, escaped report needs only a web browser."""
    sections = []
    for section, entries in groupby(rows, key=lambda row: row.section):
        items = list(entries)
        groups = (
            _source_groups(items)
            if section == "Microscope and scan settings"
            else [("", items)]
        )
        tables = "".join(_html_table(group, root) for root, group in groups)
        sections.append(
            f"<section><h2>{html.escape(section)}</h2>{tables}</section>"
        )
    title = html.escape(target.name)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Metadata — {title}</title><style>"
        "body{font:15px/1.5 'Segoe UI',Arial,sans-serif;margin:40px auto;"
        "max-width:1200px;padding:0 24px;color:#203047;background:#f6f8fb}"
        "h1{font-size:30px;margin-bottom:4px}h2{font-size:20px;margin-top:0}"
        "section{background:white;border:1px solid #dae1ec;border-radius:10px;"
        "padding:20px;margin:24px 0;overflow-x:auto}table{border-collapse:"
        "collapse;width:100%;table-layout:fixed}th,td{text-align:left;"
        "vertical-align:top;padding:10px;border-bottom:1px solid #e4e9f0;"
        "overflow-wrap:anywhere}th{background:#edf2f8}"
        ".source-root{display:block;font-size:13px;font-weight:normal;"
        "margin-top:4px;color:#526078}table+table{margin-top:24px}"
        "th:nth-child(2){width:30%}"
        "a{color:#175f98}footer{color:#526078}"
        "@media print{body{background:white;margin:0}"
        "section{break-inside:avoid}}"
        "</style></head><body><h1>Export metadata</h1>"
        f"<p>{title}</p><p>"
        f'<a href="{quote(target.name + ".json")}">'
        "Detailed JSON provenance</a>"
        " · "
        f'<a href="{quote(target.name + ".metadata.csv")}">'
        "Spreadsheet table</a>"
        "</p><p>Arrival time describes a photon delay within the laser cycle. "
        "Acquisition timepoint and Z-plane indices describe source image "
        "identity. Uncalibrated axes use sample units.</p>"
        + "".join(sections)
        + f"<footer>{APPLICATION_NAME} · Original source text and conversion "
        "provenance are retained in the JSON companion.</footer></body></html>"
    )
