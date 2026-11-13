"""Pool tile histograms without changing their underlying image data."""

import numpy as np


def separated_mosaic_graphs(
    panels: list[dict], hovered_tile: int | None
) -> list[dict]:
    """Keep unhovered tiles on their all-pixel curves."""
    if hovered_tile is None:
        return panels
    return [
        panel
        if panel.get("mosaic_tile_index") in (None, hovered_tile)
        else {
            **panel,
            "series": [("All pixels", panel["values"], panel["color"])],
        }
        for panel in panels
    ]


def combined_mosaic_graphs(panels: list[dict]) -> list[dict]:
    """Sum matching tile curves separately for each recorded pair."""
    if not panels or any(not panel.get("mosaic_pair_key") for panel in panels):
        return panels
    groups: dict[str, list[dict]] = {}
    for panel in panels:
        groups.setdefault(panel["mosaic_pair_key"], []).append(panel)
    result = []
    for tiles in groups.values():
        first = tiles[0]
        values = np.zeros_like(first["values"], dtype=np.uint64)
        curves = {}
        for tile in tiles:
            values += np.asarray(tile["values"], dtype=np.uint64)
            series = tile.get("series") or [
                ("All pixels", tile["values"], tile["color"])
            ]
            for label, counts, color in series:
                if label not in curves:
                    curves[label] = (
                        np.zeros_like(counts, dtype=np.uint64),
                        color,
                    )
                curves[label][0][:] += np.asarray(counts, dtype=np.uint64)
        result.append(
            {
                **first,
                "title": first["mosaic_pair_title"],
                "values": values,
                "photons": sum(tile["photons"] for tile in tiles),
                "series": [
                    (label, counts, color)
                    for label, (counts, color) in curves.items()
                ],
            }
        )
    return result
