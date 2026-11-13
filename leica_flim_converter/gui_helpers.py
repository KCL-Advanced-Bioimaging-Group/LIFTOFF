"""Maintained desktop component: helpers."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable
from html import escape
from pathlib import Path

import numpy as np
from PIL.ImageQt import ImageQt
from PySide6 import QtGui
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QListWidgetItem

from . import native_decoder, raw_decoder
from .dataset import DatasetInfo
from .gui_mosaic import compose_mosaic_images
from .optical_metadata import wavelength_label

_esp_preflight_cache_2 = {}


def _esp_cache_key_2(dataset):
    source = Path(dataset.source).expanduser().resolve()
    stat = source.stat()
    return (
        str(source),
        (stat.st_size),
        (stat.st_mtime_ns),
        str(dataset.key),
        str(dataset.storage_format),
        int(dataset.block_start),
        int(dataset.block_end),
        int(dataset.compressed_bytes),
        int(dataset.width),
        int(dataset.height),
        int(dataset.decoded_rows),
        int(dataset.plane_count),
        tuple(int(value) for value in dataset.plane_row_starts),
        dataset.plane_row_ranges,
        dataset.detector_route,
        dataset.repetition_storage_model,
        dataset.line_repetitions,
        dataset.frame_repetitions,
        dataset.dimension_status,
    )


def _validate_source_bounds(dataset: DatasetInfo, source_size: int) -> None:
    """Reject malformed dataset bounds before constructing a native
    decoder.
    """
    if (dataset.width) <= 0 or (dataset.height) <= 0:
        raise RuntimeError("image dimensions are missing or invalid")
    if (dataset.decoded_rows) <= 0:
        raise RuntimeError("the Leica block contains no decodable rows")
    if (dataset.plane_count) <= 0:
        raise RuntimeError("the Leica block contains no exportable T/Z planes")
    if (dataset.compressed_bytes) <= 0:
        raise RuntimeError("the Leica data block is empty")
    if not 0 <= (dataset.block_start) < (dataset.block_end) <= source_size:
        raise RuntimeError(
            "the Leica data block range is outside the source file"
        )
    if (dataset.block_end) - (dataset.block_start) < (
        dataset.compressed_bytes
    ):
        raise RuntimeError("the Leica data block is truncated")


def _esp_validate_dataset_2(dataset):
    """Perform a bounded structural and decoder-setup export
    preflight.
    """
    try:
        key = _esp_cache_key_2(dataset)
    except (OSError, TypeError, ValueError) as exc:
        return (False, f"Source file is unavailable: {exc}")
    cached = _esp_preflight_cache_2.get(key)
    if cached is not None:
        return cached
    try:
        source_size = key[1]
        _validate_source_bounds(dataset, source_size)
        if dataset.repetition_storage_model == "unresolved":
            raise RuntimeError(dataset.dimension_status)
        previous_stop = 0
        for plane in range(int(dataset.plane_count)):
            first_row, row_count = dataset.plane_row_range(plane)
            first_row = int(first_row)
            row_count = int(row_count)
            stop = first_row + row_count
            if (
                row_count <= 0
                or first_row < previous_stop
                or stop > int(dataset.decoded_rows)
            ):
                raise RuntimeError("the T/Z plane row index is invalid")
            previous_stop = stop
        if dataset.storage_format == "lmsraw":
            with raw_decoder.RawPreparedDecoder(dataset):
                pass
        elif dataset.storage_format == "compressed":
            prepared = native_decoder.NativePreparedDecoder(dataset)
            try:
                pass
            finally:
                prepared.close()
        else:
            raise RuntimeError(
                f"unsupported Leica storage format: {dataset.storage_format}"
            )
    except (OSError, RuntimeError, TypeError, ValueError, IndexError) as exc:
        result = (False, str(exc) or type(exc).__name__)
    else:
        result = (True, "Export preflight passed")
    _esp_preflight_cache_2[key] = result
    return result


def _erd_format_data_size_2(byte_count):
    byte_count = max(0, int(byte_count))
    gibibyte = 1024.0**3
    mebibyte = 1024.0**2
    if byte_count >= gibibyte:
        return f"{byte_count / gibibyte:.1f} GB"
    return f"{byte_count / mebibyte:.1f} MB"


def _plane_coordinates_2(dataset, plane):
    if plane is None:
        return (None, None)
    t_index, z_index = dataset.plane_indices(int(plane))
    return (int(t_index), int(z_index))


def _selected_groups_for_other_axis_2(dataset, selected, axis):
    result = set()
    for plane in selected:
        t_index, z_index = _plane_coordinates_2(dataset, plane)
        result.add(z_index if axis == "t" else t_index)
    return result


def _axis_label_2(index, count, expanded):
    if count <= 1:
        return "1/1"
    if not expanded:
        return "All"
    return f"{int(index) + 1:d}/{int(count):d}"


def _row_label_2(dataset, plane, modes):
    t_index, z_index = _plane_coordinates_2(dataset, plane)
    if t_index is None:
        t_index = 0
    if z_index is None:
        z_index = 0
    return (
        "T="
        f"{_axis_label_2(t_index, int(dataset.t_count), modes['t'])}"
        ", Z="
        f"{_axis_label_2(z_index, int(dataset.z_count), modes['z'])}"
    )


def _source_groups_3(
    datasets: list[DatasetInfo],
) -> list[tuple[Path, list[DatasetInfo]]]:
    """Group datasets by resolved source path while retaining their
    input order.
    """
    groups: dict[str, tuple[Path, list[DatasetInfo]]] = {}
    for dataset in datasets:
        source = Path(dataset.source).expanduser().resolve()
        identity = os.path.normcase(str(source))
        groups.setdefault(identity, (source, []))[1].append(dataset)
    return list(groups.values())


def _source_export_directory_3(dataset: DatasetInfo) -> Path:
    """Return a sibling folder named after the source LIF filename
    stem.
    """
    source = Path(dataset.source).expanduser().resolve()
    return source.parent / source.stem


def _roi_key_3(roi):
    try:
        return tuple(round(float(value), 6) for value in roi)
    except TypeError, ValueError, OverflowError:
        return (repr(roi),)


def _channel_description_2(dataset, position=None):
    del position
    detector = (
        dataset.detector_name
        or dataset.detector_identifier
        or "Unknown detector"
    )
    band = str(dataset.emission_filter_band)
    return f"Ex. {dataset.excitation_label} /\nEm. {band} ({detector})"


def _group_key_2(dataset):
    return (
        os.path.normcase(os.path.abspath(os.fspath(dataset.source))),
        dataset.memory_id,
        dataset.acquisition_name,
        dataset.series_name,
        tuple(dataset.element_path),
        dataset.timepoint_name,
        dataset.width,
        dataset.height,
        dataset.frame_count,
        dataset.z_count,
        dataset.t_count,
    )


def _sorted_group_2(group):
    return tuple(
        sorted(
            group, key=lambda item: (item.channel_index, item.detector_name)
        )
    )


def _dataset_in_group_2(dataset, group):
    key = getattr(dataset, "key", None)
    return any(getattr(item, "key", None) == key for item in group)


def _histogram_log_bounds(curves, maximum: int) -> tuple[int, int]:
    """Choose decade ticks bracketing all positive displayed counts."""
    minimum = None
    for raw_values in curves:
        values = np.asarray(raw_values).reshape(-1)
        positive = values[values > 0]
        if positive.size:
            candidate = int(positive.min())
            minimum = candidate if minimum is None else min(minimum, candidate)
    # An exact power of ten stays above the lower tick, except at one.
    lower = len(str((minimum or 1) - 1)) - 1
    upper = max(lower + 1, len(str(max(1, maximum) - 1)))
    return lower, upper


def _draw_log_tick(painter, right: float, y: float, exponent: int) -> None:
    """Draw a full-size readable exponent on a raised baseline."""
    base = QFont("Arial", 10)
    index = QFont("Arial", 9, QFont.Weight.DemiBold)
    text = "1" if exponent == 0 else "10"
    power = str(exponent) if exponent > 1 else ""
    index_width = QFontMetrics(index).horizontalAdvance(power)
    base_width = QFontMetrics(base).horizontalAdvance(text)
    painter.setFont(base)
    painter.drawText(
        QRectF(right - index_width - base_width, y - 8, base_width + 1, 20),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        text,
    )
    if power:
        painter.setFont(index)
        painter.drawText(
            QRectF(right - index_width, y - 13, index_width + 1, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            power,
        )


def _draw_histogram_axes_2(
    painter,
    plot,
    left_edge: float,
    rectangle: QRectF,
    values: np.ndarray,
    maximum: int,
    x_axis_label: str | None = None,
    *,
    log_bounds: tuple[int, int] | None = None,
):
    left, right = (rectangle.left(), rectangle.right())
    top, bottom = (rectangle.top(), rectangle.bottom())
    painter.setPen(QPen(QColor("#8c98a4"), 1))
    painter.drawLine(left, top, left, bottom)
    painter.drawLine(left, bottom, right, bottom)
    painter.setFont(QFont("Arial", 8))
    painter.setPen(QColor("#53616e"))
    if plot.logarithmic_scale:
        lower, upper = log_bounds or _histogram_log_bounds((values,), maximum)
        decades = upper - lower
        step = max(1, math.ceil(decades * 20 / max(1, bottom - top)))
        exponents = [
            lower,
            *range(lower + step, upper - step + 1, step),
            upper,
        ]
        for exponent in exponents:
            y = bottom - (exponent - lower) / decades * (bottom - top)
            painter.drawLine(QPointF(left - 4, y), QPointF(left, y))
            _draw_log_tick(painter, left - 8, y, exponent)
    else:
        painter.drawText(
            QRectF(left_edge + 23, top - 9, max(8, left - left_edge - 31), 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{maximum:,}",
        )
    painter.setFont(QFont("Arial", 8))
    painter.drawText(
        QRectF(left - 12, bottom + 4, 24, 17),
        Qt.AlignmentFlag.AlignCenter,
        "0",
    )
    painter.drawText(
        QRectF(right - 32, bottom + 4, 64, 17),
        Qt.AlignmentFlag.AlignCenter,
        str(max(0, (values.size) - 1)),
    )
    painter.drawText(
        QRectF(left, bottom + 25, max(0, right - left), 20),
        Qt.AlignmentFlag.AlignCenter,
        x_axis_label or plot.histogram_x_axis_label(),
    )
    painter.save()
    painter.translate(left_edge + 11, (top + bottom) / 2.0)
    painter.rotate(-90)
    painter.drawText(
        QRectF(-(bottom - top) / 2.0, -9, bottom - top, 18),
        Qt.AlignmentFlag.AlignCenter,
        "Photon counts",
    )
    painter.restore()


def _draw_histogram_header_2(painter, plot, scope):
    painter.setPen(QColor("#1f2933"))
    painter.setFont(QFont("Arial", 10, QFont.Weight.DemiBold))
    painter.drawText(
        QRectF(16, 7, max(0, plot.width() - 32), 20),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        "Pixel Photon-Arrival Histograms",
    )
    painter.setFont(QFont("Arial", 9))
    painter.drawText(
        QRectF(16, 29, max(0, plot.width() - 32), 18),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        scope,
    )


def _numbered_legend_rows_2(painter, plot, series):
    if not getattr(plot, "numbered_roi_legend_visible", False):
        return []

    def legend_key(entry):
        """Compute legend key."""
        label = str(entry[0])
        match = re.search("(\\d+)", label)
        return (0, int(match.group(1))) if match else (1, label.casefold())

    entries = sorted(series, key=legend_key)
    if not entries:
        return []
    painter.setFont(QFont("Arial", 8))
    metrics = painter.fontMetrics()
    available = max(120, plot.width() - 185)
    rows = [[]]
    used = 0
    for entry in entries:
        label = str(entry[0])
        item_width = 16 + metrics.horizontalAdvance(label) + 14
        if rows[-1] and used + item_width > available:
            rows.append([])
            used = 0
        rows[-1].append((entry, item_width))
        used += item_width
    for row_index, row in enumerate(rows):
        row_width = sum((item_width for _entry, item_width in row))
        x = plot.width() - 16 - row_width
        y = plot.histogram_content_top() + row_index * 18
        for entry, item_width in row:
            label, _values, color = entry
            painter.setPen(QPen(QColor(color), 2.2))
            painter.drawLine(x, y + 8, x + 12, y + 8)
            painter.setPen(QColor("#33424f"))
            painter.drawText(
                QRectF(x + 16, y, item_width - 16, 16),
                Qt.AlignmentFlag.AlignVCenter,
                str(label),
            )
            x += item_width
    return rows


def _group_description_2(group):
    return " / ".join(
        (
            _channel_description_2(dataset, position)
            for position, dataset in enumerate(group, 1)
        )
    )


def _display_title_2(group):
    first = group[0]
    if first.sequence_count > 1:
        return f"{first.acquisition_name} | {first.memory_id}"
    return (
        f"{first.acquisition_name}"
        " | "
        f"{_group_description_2(group)}"
        " | "
        f"{first.memory_id}"
    )


def summary_heading(
    dataset: DatasetInfo, channels: Iterable[DatasetInfo]
) -> str:
    """Show the entry name and selected nominal wavelength pairs."""
    emissions: dict[str, list[str]] = {}
    for channel in channels:
        excitation = (
            " / ".join(
                wavelength_label(value)
                for value in channel.excitation_wavelengths_nm
            )
            + " nm"
            if channel.excitation_wavelengths_nm
            else "unavailable"
        )
        band = re.sub(r"\s*-\s*", "-", channel.emission_filter_band)
        if band == "Emission band unavailable":
            band = "unavailable"
        bands = emissions.setdefault(excitation, [])
        if band not in bands:
            bands.append(band)
    name = escape(dataset.acquisition_name or dataset.source.stem)
    parts = [f"<b>{name}</b>"]
    parts.extend(
        escape(f"Ex. {excitation} / Em. {', '.join(bands)}")
        for excitation, bands in emissions.items()
    )
    return " | ".join(parts)


def _composite_roi_fraction_2(panels, roi):
    try:
        x0, y0, x1, y1 = (float(value) for value in roi)
    except TypeError, ValueError:
        return None
    center_x = (x0 + x1) / 2.0
    center_y = (y0 + y1) / 2.0
    image_panels = [
        panel for panel in panels if panel.get("image") is not None
    ]
    if not image_panels:
        return None
    gap = 8.0
    positions = []
    x_offset = 0.0
    for panel in image_panels:
        width = float(panel["image"].width())
        positions.append(
            (
                panel,
                float(panel.get("composite_x", x_offset)),
                width,
                float(panel.get("composite_y", 0))
                + panel.get("header_height", 0),
            )
        )
        x_offset += width + gap
    containing = [
        entry
        for entry in positions
        if entry[1] <= center_x < entry[1] + entry[2]
        and entry[3] <= center_y < entry[3] + entry[0]["image"].height()
    ]
    source_panel, source_x, source_width, header_height = (
        containing[0]
        if containing
        else min(
            positions,
            key=lambda entry: (
                (center_x - (entry[1] + entry[2] / 2.0)) ** 2
                + (center_y - (entry[3] + entry[0]["image"].height() / 2.0))
                ** 2
            ),
        )
    )
    source_height = float(source_panel["image"].height())
    left, right = sorted((x0 - source_x, x1 - source_x))
    top, bottom = sorted((y0 - header_height, y1 - header_height))
    left = min(source_width, max(0.0, left))
    right = min(source_width, max(0.0, right))
    top = min(source_height, max(0.0, top))
    bottom = min(source_height, max(0.0, bottom))
    if right <= left or bottom <= top:
        return None
    return (
        left / source_width,
        top / source_height,
        right / source_width,
        bottom / source_height,
    )


def _draw_hand_icon_2():
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#22313f"), 1.8))
    painter.setBrush(QColor("#dce5ec"))
    path = QPainterPath()
    path.moveTo(7, 11)
    path.lineTo(7, 5)
    path.quadTo(7, 3, 9, 5)
    path.lineTo(9, 10)
    path.lineTo(9, 3)
    path.quadTo(10, 1, 11, 3)
    path.lineTo(11, 10)
    path.lineTo(11, 4)
    path.quadTo(12, 2, 13, 4)
    path.lineTo(13, 11)
    path.lineTo(13, 6)
    path.quadTo(14, 4, 15, 6)
    path.lineTo(15, 13)
    path.lineTo(18, 10)
    path.quadTo(20, 9, 19, 12)
    path.lineTo(16, 19)
    path.quadTo(14, 22, 10, 20)
    path.lineTo(6, 16)
    path.quadTo(4, 13, 7, 11)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return pixmap


def _draw_magnifier_icon_2(sign, cursor=False):
    size = 32 if cursor else 24
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if cursor:
        painter.setPen(QPen(QColor("white"), 4))
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.drawLine(17, 17, 28, 28)
        painter.setPen(QPen(QColor("black"), 2))
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.drawLine(17, 17, 28, 28)
    else:
        painter.setPen(QPen(QColor("#22313f"), 2))
        painter.drawEllipse(QRectF(3, 3, 13, 13))
        painter.drawLine(14, 14, 21, 21)
    painter.setPen(
        QPen(QColor("#22313f") if not cursor else QColor("black"), 2)
    )
    center_x, center_y = (10, 10) if not cursor else (12, 12)
    radius = 4 if not cursor else 5
    painter.drawLine(center_x - radius, center_y, center_x + radius, center_y)
    if sign == "+":
        painter.drawLine(
            center_x, center_y - radius, center_x, center_y + radius
        )
    painter.end()
    return pixmap


def _make_group_item_2(group):
    first = group[0]
    frames = (
        (f" x {first.frame_count:d} frames") if first.frame_count > 1 else ""
    )
    if first.mosaic is not None:
        frames = f" | {first.mosaic.columns} x {first.mosaic.rows} tiles"
    lines = [
        (
            f"{first.acquisition_name!s}"
            " | "
            f"{first.width:d}"
            " x "
            f"{first.height:d}"
            " pixels"
            f"{frames!s}"
            " | "
            f"{first.compressed_bytes / 1000000.0:.1f}"
            " MB"
        )
    ]
    for position, dataset in enumerate(group, 1):
        detector = (
            dataset.detector_name
            or dataset.detector_identifier
            or "Unknown detector"
        )
        band = str(dataset.emission_filter_band)
        sequence = (
            f"Seq. {dataset.sequence_index + 1} | "
            if dataset.sequence_count > 1
            else ""
        )
        lines.append(
            f"{sequence}Channel {position:d} | "
            f"Ex. {dataset.excitation_label} / "
            f"Em. {band} ({detector})"
        )
    title = _display_title_2(group)
    item = QListWidgetItem("\n".join(lines))
    if first.thumbnail is not None:
        item.setIcon(
            QPixmap.fromImage(ImageQt(first.thumbnail.convert("RGBA")))
        )
    item.setData(Qt.ItemDataRole.UserRole, first)
    details = "\n".join(
        (
            _channel_tooltip(position, dataset)
            for position, dataset in enumerate(group, 1)
        )
    )
    item.setToolTip(f"{title}\nSource: {first.source}\n{details}")
    return item


def _matching_plane_index_2(combo, requested_plane):
    """Return the combo index for a decoder plane value, including
    None.
    """
    for index in range(combo.count()):
        if combo.itemData(index) == requested_plane:
            return index
    return -1


def _normalized_error_2(error):
    text = re.sub("\\s+", " ", str(error or "Unknown decode error")).strip()
    return text or "Unknown decode error"


def _roi_key_4(roi):
    return tuple(round(float(value), 6) for value in roi)


def _unique_join_2(values):
    return " / ".join(dict.fromkeys(str(value) for value in values))


def _compose_channel_images_2(panels):
    if panels and panels[0]["dataset"].mosaic is not None:
        return compose_mosaic_images(panels)
    image_panels = [
        (panel, panel["image"])
        for panel in panels
        if panel.get("image") is not None
    ]
    if not image_panels:
        return None
    labels = [
        _channel_description_2(panel["dataset"])
        for panel, _image in image_panels
    ]
    header_font = QFont("Arial", 10, QFont.Weight.DemiBold)
    lower = 1
    upper = max((image.width() for _panel, image in image_panels))
    best = 1
    while lower <= upper:
        candidate = (lower + upper) // 2
        header_font.setPixelSize(candidate)
        metrics = QtGui.QFontMetrics(header_font)
        if all(
            (
                max(
                    metrics.horizontalAdvance(line)
                    for line in label.splitlines()
                )
                <= image.width() * 0.75
                for label, (_panel, image) in zip(
                    labels, image_panels, strict=False
                )
            )
        ):
            best = candidate
            lower = candidate + 1
        else:
            upper = candidate - 1
    header_font.setPixelSize(best)
    metrics = QtGui.QFontMetrics(header_font)
    vertical_padding = max(5, (round(best * 0.25)))
    header_height = (
        metrics.height() * max(len(label.splitlines()) for label in labels)
        + vertical_padding * 2
    )
    gap = 8
    width = sum((image.width() for _panel, image in image_panels)) + gap * (
        len(image_panels) - 1
    )
    height = (
        max((image.height() for _panel, image in image_panels)) + header_height
    )
    composite = QImage(width, height, QImage.Format.Format_RGB32)
    composite.fill(QColor("#080b0d"))
    painter = QPainter(composite)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(header_font)
    x = 0
    for label, (panel, image) in zip(labels, image_panels, strict=False):
        measured_width = max(
            metrics.horizontalAdvance(line) for line in label.splitlines()
        )
        panel["header_font_pixels"] = best
        panel["header_text_width"] = measured_width
        panel["header_target_width"] = image.width() * 0.75
        panel["header_height"] = header_height
        panel["composite_x"] = x
        painter.setPen(QColor("#f2f6f8"))
        painter.drawText(
            QRectF(x, 0, image.width(), header_height),
            Qt.AlignmentFlag.AlignCenter,
            label,
        )
        painter.drawImage(x, header_height, image)
        x += image.width() + gap
    painter.end()
    return composite


def _panel_counts_view_2(panel):
    cube = panel.get("cube")
    counts = np.asarray(getattr(cube, "counts", np.empty(0)))
    if counts.ndim != 3:
        return None
    period_bins = int(panel.get("period_bins", 0) or 0)
    time_candidates = [
        index for index, size in enumerate(counts.shape) if size == period_bins
    ]
    time_axis = time_candidates[0] if time_candidates else 0
    spatial_axes = [index for index in range(3) if index != time_axis]
    dataset = panel["dataset"]
    height = int(getattr(dataset, "height", counts.shape[spatial_axes[0]]))
    width = int(getattr(dataset, "width", counts.shape[spatial_axes[1]]))
    y_candidates = [
        axis for axis in spatial_axes if counts.shape[axis] == height
    ]
    y_axis = y_candidates[0] if y_candidates else spatial_axes[0]
    x_candidates = [
        axis
        for axis in spatial_axes
        if axis != y_axis and counts.shape[axis] == width
    ]
    x_axis = (
        x_candidates[0]
        if x_candidates
        else next(axis for axis in spatial_axes if axis != y_axis)
    )
    return np.moveaxis(counts, (time_axis, y_axis, x_axis), (0, 1, 2))


def _fraction_to_slices_2(fraction, height, width):
    left, top, right, bottom = fraction
    x0 = max(0, min(width, int(np.floor(left * width))))
    x1 = max(0, min(width, int(np.ceil(right * width))))
    y0 = max(0, min(height, int(np.floor(top * height))))
    y1 = max(0, min(height, int(np.ceil(bottom * height))))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _panel_roi_values_2(panel, fractions, combine=False):
    view = _panel_counts_view_2(panel)
    if view is None:
        return np.asarray(panel["values"]).reshape(-1)
    height, width = view.shape[1:]
    slices = [
        converted
        for fraction in fractions
        if (converted := _fraction_to_slices_2(fraction, height, width))
        is not None
    ]
    if not slices:
        return np.zeros(view.shape[0], dtype=np.uint64)
    if not combine:
        x0, y0, x1, y1 = slices[0]
        return view[:, y0:y1, x0:x1].sum(axis=(1, 2), dtype=np.uint64)
    mask = np.zeros((height, width), dtype=bool)
    for x0, y0, x1, y1 in slices:
        mask[y0:y1, x0:x1] = True
    return view[:, mask].sum(axis=1, dtype=np.uint64)


def _histogram_values_2(cube, dataset):
    del dataset
    counts = np.asarray(cube.counts)
    if counts.ndim != 3:
        return counts.reshape(-1)
    period_bins = int(getattr(cube, "period_bins", 0) or 0)
    candidates = [
        index for index, size in enumerate(counts.shape) if size == period_bins
    ]
    time_axis = candidates[0] if candidates else 0
    spatial_axes = tuple(index for index in range(3) if index != time_axis)
    return counts.sum(axis=spatial_axes, dtype=np.uint64)


ROI_OVERLAP_MESSAGE = (
    "Only able to display data from one unique ROI; please move mouse "
    "to one unique ROI."
)


def _draw_histogram_curves(
    painter: QPainter,
    series,
    rectangle: QRectF,
    maximum: int,
    logarithmic: bool = False,
    *,
    log_bounds: tuple[int, int] | None = None,
    omitted: tuple[float, float] | None = None,
) -> None:
    """Draw detector or ROI curves with identical scales and pen
    widths.
    """
    left, right = (rectangle.left(), rectangle.right())
    top, bottom = (rectangle.top(), rectangle.bottom())
    lower, upper = (0, 1)
    if logarithmic:
        lower, upper = log_bounds or _histogram_log_bounds(
            (entry[1] for entry in series), maximum
        )
    for _label, raw_values, color in series:
        values = np.asarray(raw_values).reshape(-1)
        path = QPainterPath()
        connected = False
        painter.setPen(QPen(QColor(color), 2.2))
        for value_index, value in enumerate(values):
            count = int(value)
            if (
                omitted is not None and omitted[0] <= value_index <= omitted[1]
            ) or (logarithmic and count <= 0):
                connected = False
                continue
            x = left + value_index / max(1, values.size - 1) * (right - left)
            fraction = (
                (math.log10(count) - lower) / (upper - lower)
                if logarithmic
                else count / maximum
            )
            y = bottom - fraction * (bottom - top)
            if not connected:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
            connected = True
            if (
                logarithmic
                and (value_index == 0 or values[value_index - 1] <= 0)
                and (
                    value_index == values.size - 1
                    or values[value_index + 1] <= 0
                )
            ):
                # Keep isolated positive bins visible between zeros.
                painter.drawPoint(QPointF(x, y))
        painter.drawPath(path)


def _channel_tooltip(position: int, dataset: DatasetInfo) -> str:
    """Describe detector identity and emission metadata for one
    channel.
    """
    identifier = dataset.detector_identifier or "unavailable"
    band = dataset.emission_filter_band
    return (
        "Channel "
        f"{position:d}"
        ": detector "
        f"{dataset.detector_name!s}"
        ", identifier "
        f"{identifier!s}"
        f", excitation {dataset.excitation_label}"
        ", emission filter "
        f"{band!s}"
    )
