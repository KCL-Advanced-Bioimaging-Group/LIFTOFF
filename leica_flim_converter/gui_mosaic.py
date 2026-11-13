"""Compose Navigator tiles using their recorded grid cells."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter


def _tile_title(dataset, multiple):
    tile = dataset.mosaic.tiles[dataset.tile_index]
    title = f"Tile {tile.row + 1}, {tile.column + 1}"
    if multiple:
        title += (
            f"\nEx. {dataset.excitation_label}\n"
            f"Em. {dataset.emission_filter_band} ({dataset.detector_name})"
        )
    return title


def _header_style(panels, multiple, width, gap):
    font = QFont("Arial")
    size = max(1, min(64, width // 12))
    while True:
        font.setPixelSize(size)
        metrics = QFontMetrics(font)
        if size == 1 or all(
            metrics.horizontalAdvance(line) <= width * 0.9
            for panel in panels
            for line in _tile_title(panel["dataset"], multiple).splitlines()
        ):
            break
        size -= 1
    return font, metrics.height() * (3 if multiple else 1) + gap * 2


def compose_mosaic_images(panels) -> QImage:
    """Show one spatial matrix for each selected recorded pair."""
    first = panels[0]["dataset"]
    layout = first.mosaic
    if layout is None:
        raise ValueError("Mosaic composition requires recorded tile geometry")
    pairs = list(dict.fromkeys(panel["dataset"].pair_key for panel in panels))
    width, height = first.width, first.height
    gap = max(4, width // 128)
    font, header = _header_style(panels, len(pairs) > 1, width, gap)
    cell_width, cell_height = width + gap, height + header + gap
    image = QImage(
        cell_width * layout.columns * len(pairs) - gap,
        cell_height * layout.rows - gap,
        QImage.Format.Format_RGB32,
    )
    image.fill(QColor("#080b0d"))
    painter = QPainter(image)
    painter.setFont(font)
    painter.setPen(QColor("#f2f6f8"))
    for panel in panels:
        dataset = panel["dataset"]
        if dataset.tile_index is None or dataset.mosaic != layout:
            raise ValueError("Mosaic panels have inconsistent tile identities")
        tile = layout.tiles[dataset.tile_index]
        column = pairs.index(dataset.pair_key) * layout.columns + tile.column
        x, y = column * cell_width, tile.row * cell_height
        painter.drawText(
            QRectF(x, y, width, header),
            Qt.AlignmentFlag.AlignCenter,
            _tile_title(dataset, len(pairs) > 1),
        )
        painter.drawImage(x, y + header, panel["image"])
        panel.update(composite_x=x, composite_y=y, header_height=header)
    painter.end()
    return image


def mosaic_roi_fractions(panels, roi, target):
    """Intersect an ROI with each matching spatial tile."""
    x0, y0, x1, y1 = (float(value) for value in roi)
    left, right = sorted((x0, x1))
    top, bottom = sorted((y0, y1))
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    owner = min(
        panels,
        key=lambda panel: (
            (center_x - panel["composite_x"] - panel["dataset"].width / 2) ** 2
            + (
                center_y
                - panel.get("composite_y", 0)
                - panel["header_height"]
                - panel["dataset"].height / 2
            )
            ** 2
        ),
    )
    for panel in panels:
        dataset = panel["dataset"]
        if (
            dataset.pair_key != owner["dataset"].pair_key
            or dataset.tile_index != target["dataset"].tile_index
        ):
            continue
        x, y = (
            panel["composite_x"],
            panel.get("composite_y", 0) + panel["header_height"],
        )
        x0, x1 = max(0, left - x), min(dataset.width, right - x)
        y0, y1 = max(0, top - y), min(dataset.height, bottom - y)
        if x1 > x0 and y1 > y0:
            return [
                (
                    x0 / dataset.width,
                    y0 / dataset.height,
                    x1 / dataset.width,
                    y1 / dataset.height,
                )
            ]
    return []


def mosaic_roi_extent(panel, roi):
    """Retain image pixels independently of changing heading heights."""
    dataset = panel["dataset"]
    tile = dataset.mosaic.tiles[dataset.tile_index]
    gap = max(4, dataset.width // 128)
    cell_width = dataset.width + gap
    origin_x = panel["composite_x"] - tile.column * cell_width
    x0, y0, x1, y1 = roi
    return {
        "bounds": (x0 - origin_x, y0, x1 - origin_x, y1),
        "imageSize": (dataset.width, dataset.height),
        "header": panel["header_height"],
    }


def _remap_axis(
    value, old_size, old_before, old_gap, new_size, new_before, new_gap
):
    """Scale image and annotation segments within each cell."""
    cell, offset = divmod(value, old_size + old_before + old_gap)
    if offset < old_before:
        mapped = offset / old_before * new_before
    elif offset <= old_before + old_size:
        mapped = new_before + (offset - old_before) / old_size * new_size
    else:
        mapped = (
            new_before
            + new_size
            + (offset - old_before - old_size) / old_gap * new_gap
        )
    # Avoid expanding an integer pixel boundary through round-off.
    return round(cell * (new_size + new_before + new_gap) + mapped, 9)


def restore_mosaic_extent(panel, extent):
    """Restore a retained region in the selected pair's tile matrix."""
    dataset = panel["dataset"]
    tile = dataset.mosaic.tiles[dataset.tile_index]
    gap = max(4, dataset.width // 128)
    cell_width = dataset.width + gap
    origin_x = panel["composite_x"] - tile.column * cell_width
    width, height = extent["imageSize"]
    old_gap = max(4, width // 128)
    x0, y0, x1, y1 = extent["bounds"]
    return (
        origin_x + _remap_axis(x0, width, 0, old_gap, dataset.width, 0, gap),
        _remap_axis(
            y0,
            height,
            extent["header"],
            old_gap,
            dataset.height,
            panel["header_height"],
            gap,
        ),
        origin_x + _remap_axis(x1, width, 0, old_gap, dataset.width, 0, gap),
        _remap_axis(
            y1,
            height,
            extent["header"],
            old_gap,
            dataset.height,
            panel["header_height"],
            gap,
        ),
    )


def _relative_bounds(source, roi):
    x0, y0, x1, y1 = roi
    left, right = sorted((x0 - source["x"], x1 - source["x"]))
    top, bottom = sorted((y0 - source["header"], y1 - source["header"]))
    return (
        min(source["width"], max(0.0, left)) / source["width"],
        min(source["height"], max(0.0, top)) / source["height"],
        min(source["width"], max(0.0, right)) / source["width"],
        min(source["height"], max(0.0, bottom)) / source["height"],
    )


def _mirror_parts(layout, roi, source_index):
    """Mirror every intersected tile piece within the source channel."""
    source = layout[source_index]
    sources = (
        [part for part in layout if part.get("pair") == source["pair"]]
        if source.get("tile") is not None and "pair" in source
        else [source]
    )
    mirrors = []
    for part in sources:
        left, top, right, bottom = _relative_bounds(part, roi)
        if right <= left or bottom <= top:
            continue
        for index, target in enumerate(layout):
            if target in sources or target.get("tile") != part.get("tile"):
                continue
            mirrors.append(
                (
                    index,
                    (
                        target["x"] + left * target["width"],
                        target["header"] + top * target["height"],
                        target["x"] + right * target["width"],
                        target["header"] + bottom * target["height"],
                    ),
                )
            )
    return mirrors


def mirror_rectangles(layout, roi):
    """Mirror ROI geometry only between matching spatial tiles."""
    if len(layout) < 2:
        return (None, [])
    try:
        x0, y0, x1, y1 = (float(value) for value in roi)
    except TypeError, ValueError:
        return (None, [])
    center_x = (x0 + x1) / 2.0
    center_y = (y0 + y1) / 2.0
    containing = [
        (index, panel)
        for index, panel in enumerate(layout)
        if panel["x"] <= center_x < panel["x"] + panel["width"]
        and panel["header"] <= center_y < panel["header"] + panel["height"]
    ]
    source_index, _source = (
        containing[0]
        if containing
        else min(
            enumerate(layout),
            key=lambda entry: (
                abs(center_x - (entry[1]["x"] + entry[1]["width"] / 2.0)) ** 2
                + abs(
                    center_y - (entry[1]["header"] + entry[1]["height"] / 2.0)
                )
                ** 2
            ),
        )
    )
    return (
        source_index,
        _mirror_parts(layout, (x0, y0, x1, y1), source_index),
    )
