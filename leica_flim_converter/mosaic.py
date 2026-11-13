"""Recorded tile identities, spatial grid and acquisition positions."""

from __future__ import annotations

from dataclasses import dataclass

MOSAIC_INTEGRATION_ERROR = (
    "Mosaic tiles represent different positions; "
    "choose split export to keep tiles separate"
)


@dataclass(frozen=True)
class TilePosition:
    """One native stage position and its display cell."""

    column: int
    row: int
    field_x: int
    field_y: int
    stage_x_m: float
    stage_y_m: float
    stage_z_m: float


@dataclass(frozen=True)
class MosaicLayout:
    """Tiles in photon-storage order, independent of display order."""

    columns: int
    rows: int
    tiles: tuple[TilePosition, ...]
    flip_x: bool = False
    flip_y: bool = False
    swap_xy: bool = False

    def metadata(self, tile_index: int | None = None) -> dict:
        """Keep stage coordinates and matrix interpretation explicit."""
        return {
            "columns": self.columns,
            "rows": self.rows,
            "tileCount": len(self.tiles),
            "tileIndexZeroBased": tile_index,
            "displayMode": "separate unstitched tiles",
            "metadataSource": "TileScanInfo and RawData stage positions",
            "flipX": self.flip_x,
            "flipY": self.flip_y,
            "swapXY": self.swap_xy,
            "tiles": [
                {
                    "indexZeroBased": index,
                    "columnZeroBased": tile.column,
                    "rowZeroBased": tile.row,
                    "fieldX": tile.field_x,
                    "fieldY": tile.field_y,
                    "stagePositionMetres": [
                        tile.stage_x_m,
                        tile.stage_y_m,
                        tile.stage_z_m,
                    ],
                }
                for index, tile in enumerate(self.tiles)
            ],
        }
