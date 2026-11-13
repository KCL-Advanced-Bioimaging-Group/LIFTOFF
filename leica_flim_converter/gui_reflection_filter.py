"""Reversible reflection filtering for image and histogram previews."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from .gui_canvas import image_from_counts
from .gui_helpers import _compose_channel_images_2
from .gui_models import connect_signal
from .reflection_export import ReflectionWindow

if TYPE_CHECKING:
    from .gui_models import ChannelPanel
    from .gui_reflection import GraphKey
    from .gui_workspace_state import WorkspaceState


_ReflectionScope = tuple[str, tuple[int, ...] | None]


@dataclass(frozen=True)
class _ReflectionSetting:
    """A completed native interval and its preview toggle state."""

    bounds: tuple[float, float]
    enabled: bool = False


def filtered_intensity(
    counts: np.ndarray, bounds: tuple[float, float]
) -> np.ndarray:
    """Sum retained bin/y/x counts using inclusive bin centres."""
    start = max(0, math.ceil(bounds[0]))
    stop = min(counts.shape[0], math.floor(bounds[1]) + 1)
    return counts[:start].sum(axis=0, dtype=np.uint64) + counts[stop:].sum(
        axis=0, dtype=np.uint64
    )


class ReflectionPhotonFilter(QWidget):
    """Update previews while preserving decoded cubes and ROI state."""

    def __init__(self) -> None:
        super().__init__()
        self.owner: WorkspaceState | None = None
        self.panels: Callable[[], list[ChannelPanel]] = lambda: []
        self._original_image: QImage | None = None
        self._filtered_image: QImage | None = None
        self._contrast_backup = None
        self._contrast_generation = 0
        self._settings: dict[_ReflectionScope, _ReflectionSetting] = {}
        self.checkbox = QRadioButton()
        self.checkbox.setAutoExclusive(False)
        self.checkbox.setObjectName("filterReflectionPhotonsCheckBox")
        self.checkbox.setEnabled(False)
        self.checkbox.setToolTip(
            "Exclude photons between the reflection boundaries from "
            "the image and all graphs. Uncheck to restore photons and "
            "edit the boundaries. Source data and exports are unchanged."
        )
        self.status = QLabel("No reflection peak identified.")
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.checkbox)
        self.unavailable = QLabel("No reflection peak identified.")
        self.unavailable.setWordWrap(True)
        toggle_row.addWidget(self.unavailable, 1)
        layout.addLayout(toggle_row)
        layout.addWidget(self.status)

    def bind(
        self, owner: WorkspaceState, panels: Callable[[], list[ChannelPanel]]
    ) -> None:
        """Connect after the workspace's graph has been constructed."""
        self.owner = owner
        self.panels = panels
        connect_signal(owner.histogram.reflection.changed, self.sync)
        connect_signal(
            owner.histogram.reflection.regions_changed, self._save_regions
        )
        connect_signal(self.checkbox.toggled, self.apply)
        self.sync()

    def sync(self) -> None:
        """Offer filtering only for completed reflection boundaries."""
        if self.owner is None:
            return
        markers = self.owner.histogram.reflection
        if not markers.regions and self.checkbox.isChecked():
            self._apply_preview(set())
            return
        self.checkbox.setEnabled(
            bool(markers.regions) and not markers.manual.active
        )
        if not markers.regions:
            self.status.setText("No reflection peak identified.")
        elif not self.checkbox.isChecked():
            self.status.clear()
        self.status.setVisible(bool(self.status.text()))
        self.unavailable.setVisible(not bool(markers.regions))
        if not markers.regions:
            self.status.hide()

    def apply(self, enabled: bool) -> None:
        """Save the user's toggle for the bounded entries on display."""
        if self.owner is None:
            return
        regions = self.owner.histogram.reflection.regions
        for graph, scope in self._graph_scopes().items():
            if graph in regions:
                self._settings[scope] = _ReflectionSetting(
                    regions[graph], enabled
                )
        self._apply_preview(set(regions) if enabled else set())

    def _apply_preview(self, keys: set[GraphKey]) -> None:
        """Replace image pixels and the graph's display mask."""
        owner = self.owner
        if owner is None:
            return
        markers = owner.histogram.reflection
        with QSignalBlocker(self.checkbox):
            self.checkbox.setChecked(bool(keys))
        markers.set_filtered(keys)
        if keys:
            self._contrast_backup = (
                owner.image.contrast.intensities,
                owner.image.contrast.panels,
            )
            self._contrast_generation = owner.image.contrast.generation
            self._original_image = owner.image.image
            removed = self._filter_image(owner)
            self._filtered_image = owner.image.image
            subset = (
                f" {len(keys)} of {len(markers.regions)} marked channels."
                if len(keys) < len(markers.regions)
                else ""
            )
            self.status.setText(
                f"{removed:,} photons filtered.{subset} "
                "Uncheck to adjust boundaries."
            )
        else:
            # New previews may already have replaced the old image.
            if owner.image.image is self._filtered_image:
                owner.image.image = self._original_image
            if (
                self._contrast_backup is not None
                and owner.image.contrast.generation
                == self._contrast_generation
            ):
                owner.image.contrast.set_intensities(
                    *self._contrast_backup, reset=False
                )
            self._contrast_backup = None
            self._original_image = None
            self._filtered_image = None
            self.status.clear()
        owner.image.update()
        self.sync()

    def _filter_image(self, owner: WorkspaceState) -> int:
        """Apply each channel's bounds to its images and tiles."""
        markers = owner.histogram.reflection
        source_panels = self.panels()
        graph_panels = owner.histogram.multichannel_panels
        removed = 0
        if source_panels and graph_panels:
            displayed = []
            for index, (source, graph) in enumerate(
                zip(source_panels, graph_panels, strict=True)
            ):
                panel = source.copy()
                counts = source["cube"].counts
                bounds = markers.omitted(
                    markers.graph_key(graph, counts.shape[0], index)
                )
                if bounds is not None:
                    intensity = filtered_intensity(counts, bounds)
                    panel["intensity"] = intensity
                    panel["image"] = image_from_counts(intensity)
                    removed += int(source["values"].sum()) - int(
                        intensity.sum()
                    )
                displayed.append(panel)
            owner.image.image = _compose_channel_images_2(displayed)
            owner.image.contrast.set_intensities(
                [
                    panel["intensity"]
                    if "intensity" in panel
                    else panel["cube"].intensity
                    for panel in displayed
                ],
                displayed,
                reset=False,
            )
        elif owner.cube is not None:
            counts = owner.cube.counts
            bounds = markers.omitted(markers.graph_key(None, counts.shape[0]))
            if bounds is not None:
                intensity = filtered_intensity(counts, bounds)
                owner.image.image = image_from_counts(intensity)
                owner.image.contrast.set_intensities([intensity], reset=False)
                removed = int(counts.sum(dtype=np.uint64)) - int(
                    intensity.sum()
                )
        return removed

    def _graph_scopes(self) -> dict[GraphKey, _ReflectionScope]:
        """Map displayed graphs to their detector and T/Z scope."""
        owner = self.owner
        if owner is None or owner.decode_worker is not None:
            return {}
        markers = owner.histogram.reflection
        sources = (
            [
                (source["dataset"], source["cube"], graph, index)
                for index, (source, graph) in enumerate(
                    zip(
                        self.panels(),
                        owner.histogram.multichannel_panels or (),
                        strict=True,
                    )
                )
            ]
            if owner.histogram.multichannel_panels
            else []
        )
        if (
            not sources
            and owner.selected is not None
            and owner.cube is not None
        ):
            sources = [(owner.selected, owner.cube, None, 0)]
        originals = {dataset.key: dataset for dataset in owner.datasets}
        scopes = {}
        for dataset, cube, graph, index in sources:
            key = markers.graph_key(graph, cube.counts.shape[0], index)
            if key in scopes:
                continue
            original = originals.get(dataset.pair_key, dataset)
            planes = (
                None
                if cube.linear_plane is None
                else tuple(
                    plane
                    for plane in range(original.plane_count)
                    if original.plane_indices(plane)
                    == dataset.plane_indices(cube.linear_plane)
                )
            )
            scopes[key] = (original.key, planes)
        return scopes

    def _save_regions(self) -> None:
        """Commit edits for the displayed detectors and T/Z views."""
        if self.owner is None:
            return
        regions = self.owner.histogram.reflection.regions
        for graph, scope in self._graph_scopes().items():
            if graph in regions:
                self._settings[scope] = _ReflectionSetting(regions[graph])
            else:
                self._settings.pop(scope, None)

    def restore_preview(self) -> None:
        """Restore the intervals and toggles of a completed preview."""
        if self.owner is None:
            return
        markers = self.owner.histogram.reflection
        markers.sync_context()
        keys = set()
        for graph, scope in self._graph_scopes().items():
            setting = self._settings.get(scope)
            if setting is not None and setting.bounds[1] < graph[2]:
                markers.regions[graph] = setting.bounds
                if setting.enabled:
                    keys.add(graph)
        self._apply_preview(keys)

    def retain_datasets(self, dataset_keys: set[str]) -> None:
        """Discard settings when their sources leave the workspace."""
        self._settings = {
            scope: setting
            for scope, setting in self._settings.items()
            if scope[0] in dataset_keys
        }

    def export_windows(self) -> tuple[ReflectionWindow, ...]:
        """Snapshot saved bounds, preferring specific T/Z intervals."""
        return tuple(
            ReflectionWindow(
                key, *self._settings[(key, planes)].bounds, planes
            )
            for key, planes in sorted(
                self._settings,
                key=lambda scope: (scope[0], scope[1] is None, scope[1] or ()),
            )
        )
