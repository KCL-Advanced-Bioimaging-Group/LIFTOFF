"""Maintained desktop component: models."""

from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypedDict

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import SignalInstance
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from .dataset import DatasetInfo
from .histogram_core import HistogramCube

Roi = tuple[int | float, int | float, int | float, int | float]
Fraction = tuple[float, float, float, float]


class ChannelSequence(TypedDict):
    """Serial detector work sharing one plane and photon selection."""

    group: tuple[DatasetInfo, ...]
    queue: list[DatasetInfo]
    current: DatasetInfo
    linear_plane: int | None
    panels: list[ChannelPanel]


class ChannelPanel(TypedDict):
    """Decoded scientific data and composite image geometry."""

    dataset: DatasetInfo
    image: QImage | None
    values: NDArray[np.uint64]
    events: int
    backend: str
    elapsed: float
    nbytes: int
    dtype: str
    period_bins: int
    cube: HistogramCube
    intensity: NotRequired[NDArray[np.uint64]]
    header_font_pixels: NotRequired[int]
    header_text_width: NotRequired[int]
    header_target_width: NotRequired[float]
    header_height: NotRequired[int]
    composite_x: NotRequired[int]
    composite_y: NotRequired[int]


class MosaicExtent(TypedDict):
    """An ROI and its original image and annotation geometry."""

    bounds: Fraction
    imageSize: tuple[int, int]
    header: int


class RoiSnapshotItem(TypedDict):
    """An activated ROI in normalized source-image coordinates."""

    fraction: Fraction
    sourceKey: str | None
    tileIndex: NotRequired[int | None]
    mosaicExtent: NotRequired[MosaicExtent]
    color: QColor
    number: int


class RoiSnapshot(TypedDict):
    """Retained ROI identities across channel and plane transitions."""

    items: list[RoiSnapshotItem]
    nextNumber: int


def required_table_item(
    table: QTableWidget, row: int, column: int
) -> QTableWidgetItem:
    """Return a constructed cell or report an invalid table model."""
    item = table.item(row, column)
    if item is None:
        raise RuntimeError(f"Missing export cell ({row}, {column})")
    return item


def widget_box_layout(widget: QWidget) -> QBoxLayout:
    """Resolve the owned box layout used by the workspace controls."""
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if not isinstance(layout, QBoxLayout):
        raise RuntimeError("Workspace control has no box layout")
    return layout


def connect_signal(
    signal: SignalInstance, callback: Callable[..., object]
) -> None:
    """Bind a PySide signal through its explicit extension boundary."""
    signal.connect(callback)
