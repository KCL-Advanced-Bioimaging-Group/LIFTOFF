"""Reversible reflection filtering for image and histogram previews."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from secrets import randbits
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .gui_canvas import image_from_counts
from .gui_helpers import _compose_channel_images_2
from .gui_models import connect_signal
from .reflection_export import ReflectionWindow
from .reflection_metadata import MODE_LABELS, REPAIR_MODES
from .reflection_processing import corrected_cube

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
    mode: str = "nan"
    seed: int = 0


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
        self._original_cubes = []
        self.checkbox = QRadioButton()
        self.checkbox.setAutoExclusive(False)
        self.checkbox.setObjectName("filterReflectionPhotonsCheckBox")
        self.checkbox.setEnabled(False)
        self.checkbox.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.checkbox.setToolTip(
            "Apply the selected treatment per pixel to the image and all "
            "graphs. Uncheck to restore counts and edit boundaries."
        )
        self.mode = QComboBox()
        self.mode.setObjectName("reflectionProcessingMode")
        self.mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.mode.setMinimumContentsLength(12)
        self.mode.setPlaceholderText("Mixed saved modes")
        for mode, label in MODE_LABELS.items():
            self.mode.addItem(label, mode)
        self.mode.setCurrentIndex(0)
        self.mode.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.mode.setToolTip(
            "Join whole-image log counts across the reflection interval. "
            "Smooth interpolation distributes expected counts across pixels. "
            "Simulation draws each pixel's counts from that Poisson mean "
            "using a reproducible seed. ICS exports use the saved choice."
        )
        self.status = QLabel("No reflection peak identified.")
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.checkbox)
        toggle_row.addWidget(self.mode)
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
        connect_signal(self.mode.currentIndexChanged, self._mode_changed)
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
        self.mode.setVisible(bool(markers.regions))
        self.mode.setEnabled(not markers.manual.active)
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
                previous = self._settings.get(scope)
                self._settings[scope] = _ReflectionSetting(
                    regions[graph],
                    enabled,
                    self.mode.currentData()
                    or (previous.mode if previous else "nan"),
                    previous.seed if previous else randbits(64),
                )
        self._apply_preview(set(regions) if enabled else set())

    def _mode_changed(self, _index: int) -> None:
        if self.mode.currentData() is not None:
            self.apply(self.checkbox.isChecked())

    def _apply_preview(self, keys: set[GraphKey]) -> None:
        """Replace image pixels and the graph's display mask."""
        owner = self.owner
        if owner is None:
            return
        self._restore_preview_data(owner)
        markers = owner.histogram.reflection
        with QSignalBlocker(self.checkbox):
            self.checkbox.setChecked(bool(keys))
        markers.set_filtered(keys)
        markers.processing_modes = {
            graph: self._settings.get(scope, _ReflectionSetting((0, 1))).mode
            for graph, scope in self._graph_scopes().items()
            if graph in keys
        }
        if keys:
            self._contrast_backup = (
                owner.image.contrast.intensities,
                owner.image.contrast.panels,
            )
            self._contrast_generation = owner.image.contrast.generation
            self._original_image = owner.image.image
            self._filter_image(owner)
            self._filtered_image = owner.image.image
            subset = (
                f" {len(keys)} of {len(markers.regions)} marked channels."
                if len(keys) < len(markers.regions)
                else ""
            )
            self.status.setText(
                self._preview_status()
                + subset
                + " Uncheck to adjust boundaries."
            )
        else:
            self.status.clear()
        # Rebuild every active curve from the newly selected cube.
        owner._refresh_roi_histogram()  # pylint: disable=protected-access
        owner.image.update()
        self.sync()

    def _preview_status(self) -> str:
        interpolations = [
            derived.reflection_processing
            for _, _, derived in self._original_cubes
            if derived.reflection_processing["mode"] in REPAIR_MODES
        ]
        if any(not item["interpolationAvailable"] for item in interpolations):
            return (
                "Interpolation unavailable for one or more images: "
                "positive whole-image count endpoints are required. "
                "Undefined intervals remain NaN."
            )
        if interpolations:
            if any(item["mode"] == "simulate" for item in interpolations):
                return (
                    "Synthetic Poisson counts from the whole-image "
                    "log-linear bridge. The realization is reproducible."
                )
            return (
                "Smooth whole-image log-linear bridge; pixel weights use "
                "counts outside the interval."
            )
        return "Reflection interval assigned to NaNs."

    def _restore_preview_data(self, owner) -> None:
        for source, original, derived in self._original_cubes:
            if source is None:
                if owner.cube is derived:
                    owner.cube = original
            elif source["cube"] is derived:
                source["cube"] = original
                source["values"] = original.counts.sum(
                    axis=(1, 2), dtype=np.uint64
                )
        self._original_cubes.clear()
        if owner.image.image is self._filtered_image:
            owner.image.image = self._original_image
        if self._contrast_backup is not None and (
            owner.image.contrast.generation == self._contrast_generation
        ):
            owner.image.contrast.set_intensities(
                *self._contrast_backup, reset=False
            )
        self._contrast_backup = None
        self._original_image = self._filtered_image = None

    def _filter_image(self, owner: WorkspaceState) -> None:
        """Apply each channel's bounds to its images and tiles."""
        markers = owner.histogram.reflection
        source_panels = self.panels()
        graph_panels = owner.histogram.multichannel_panels
        seeds = {
            graph: self._settings[scope].seed
            for graph, scope in self._graph_scopes().items()
            if scope in self._settings
        }
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
                    original = source["cube"]
                    key = markers.graph_key(graph, counts.shape[0], index)
                    derived = corrected_cube(
                        original,
                        bounds,
                        markers.processing_modes[key],
                        seed=seeds.get(key, 0),
                    )
                    self._original_cubes.append((source, original, derived))
                    source["cube"] = derived
                    source["values"] = derived.counts.sum(axis=(1, 2))
                    intensity = derived.intensity
                    panel["intensity"] = intensity
                    panel["image"] = image_from_counts(intensity)
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
                original = owner.cube
                key = markers.graph_key(None, counts.shape[0])
                derived = corrected_cube(
                    original,
                    bounds,
                    markers.processing_modes[key],
                    seed=seeds.get(key, 0),
                )
                self._original_cubes.append((None, original, derived))
                owner.cube = derived
                intensity = derived.intensity
                owner.image.image = image_from_counts(intensity)
                owner.image.contrast.set_intensities([intensity], reset=False)

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
                previous = self._settings.get(scope)
                self._settings[scope] = _ReflectionSetting(
                    regions[graph],
                    mode=(
                        previous.mode
                        if previous
                        else self.mode.currentData() or "nan"
                    ),
                    seed=previous.seed if previous else randbits(64),
                )
            else:
                self._settings.pop(scope, None)

    def restore_preview(self) -> None:
        """Restore the intervals and toggles of a completed preview."""
        if self.owner is None:
            return
        markers = self.owner.histogram.reflection
        markers.sync_context()
        keys = set()
        modes = set()
        for graph, scope in self._graph_scopes().items():
            setting = self._settings.get(scope)
            if setting is not None and setting.bounds[1] < graph[2]:
                markers.regions[graph] = setting.bounds
                modes.add(setting.mode)
                if setting.enabled:
                    keys.add(graph)
        with QSignalBlocker(self.mode):
            self.mode.setCurrentIndex(
                self.mode.findData(next(iter(modes)))
                if len(modes) == 1
                else -1
                if modes
                else 0
            )
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
                key,
                *self._settings[(key, planes)].bounds,
                planes,
                self._settings[(key, planes)].mode,
                seed=self._settings[(key, planes)].seed,
            )
            for key, planes in sorted(
                self._settings,
                key=lambda scope: (scope[0], scope[1] is None, scope[1] or ()),
            )
        )
