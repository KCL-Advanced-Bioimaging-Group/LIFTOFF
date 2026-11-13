"""Maintained desktop component: workspace channels."""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

from PySide6 import QtGui
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QListWidgetItem, QMessageBox

from .dataset import DatasetInfo
from .event_flags import selection_name
from .gui_helpers import (
    _channel_description_2,
    _compose_channel_images_2,
    _group_key_2,
    _make_group_item_2,
    _sorted_group_2,
    _unique_join_2,
    summary_heading,
)
from .gui_workspace_state import WorkspaceState
from .mosaic_views import tile_view


class WorkspaceChannels(WorkspaceState):
    """Detector grouping and synchronized multi-channel presentation."""

    def _groups_for_window_2(self):
        groups = {}
        order = []
        for dataset in self.datasets:
            key = _group_key_2(dataset)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(dataset)
        return [list(_sorted_group_2(groups[key])) for key in order]

    def current_acquisition_group(self):
        """Return all recorded pairs for the selected acquisition."""
        group = self._channel_group
        if group:
            return tuple(group)
        if self.selected is None:
            return ()
        key = _group_key_2(self.selected)
        return next(
            (
                tuple(candidate)
                for candidate in self._groups_for_window_2()
                if _group_key_2(candidate[0]) == key
            ),
            (self.selected,),
        )

    def current_channel_group(self):
        """Return independently selected recorded pairs."""
        return self.pair_selector.selected_datasets()

    def _apply_group_details_2(self):
        group = self.current_channel_group()
        if not group:
            return
        first = group[0]
        self.block_title.setText(summary_heading(first, group))
        dimensions = f"{first.width:d} x {first.height:d} x C={len(group):d}"
        if first.frame_count > 1:
            dimensions += f" x {first.frame_count:d} frames"
        dimensions += (
            " | line repeats="
            f"{first.line_repetitions:d}"
            ", frame repeats="
            f"{first.frame_repetitions:d}"
        )
        self.fields["Dimensions"].setText(dimensions)
        self.fields["Rows"].setText(
            f"{f'{first.indexed_rows:,}'}"
            " per channel | "
            f"{first.dimension_status}"
        )
        self.fields["Rows"].setMinimumHeight(0)
        if first.sequence_count > 1:
            self.fields["Dimensions"].setText(
                f"{first.width} x {first.height} x T={first.t_count} "
                f"x Z={first.z_count}"
            )
            settings = {item.sequence_index: item for item in group}
            rows = self.fields["Rows"]
            rows.setText(
                "\n".join(
                    f"Seq. {item.sequence_index + 1}: "
                    f"{item.indexed_rows:,} rows | "
                    f"{item.dimension_status}\n"
                    f"line repeats={item.line_repetitions}, "
                    f"frame repeats={item.frame_repetitions}"
                    for item in settings.values()
                )
            )
            rows.setMinimumHeight(
                len(settings)
                * 2
                * QtGui.QFontMetrics(rows.font()).lineSpacing()
                + 6
            )
            rows.setToolTip(
                "\n".join(item.sequence_label for item in settings.values())
            )
        if first.recorded_plane_count is not None:
            dimensions = self.fields["Dimensions"]
            dimensions.setText(
                dimensions.text() + f" | {first.plane_count} of "
                f"{first.declared_plane_count} planes recorded"
            )
        valid_counts = getattr(self, "_channel_valid_counts", {})
        count_lines = []
        for position, dataset in enumerate(group, 1):
            valid = valid_counts.get(dataset.key)
            valid_text = (
                f"{valid:,} valid counts"
                if valid is not None
                else "valid counts pending"
            )
            count_lines.append(
                "Channel "
                f"{position:d}"
                ": "
                f"{valid_text!s}"
                " / "
                f"{dataset.raw_photon_label}"
            )
        count_label = self.fields["Photons"]
        count_label.setWordWrap(True)
        count_label.setMinimumHeight(0)
        count_label.setText("\n".join(count_lines))
        self.fields["Memory block"].setText(first.memory_id)

    def _main_window_select_block_4(self, item: QListWidgetItem) -> None:
        if (
            self.scan_worker is not None
            or self.decode_worker is not None
            or self.export_worker is not None
        ):
            return
        dataset = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(dataset, DatasetInfo):
            return
        if dataset.decoded_rows <= 0:
            QMessageBox.information(
                self,
                "FLIM block unavailable",
                "This Leica block contains no encoded FLIM rows.",
            )
            return
        self.cube = None
        self.selected = dataset
        self.current_plane = None
        self._show_dataset(dataset)
        self._start_decode(self.plane_combo.currentData())

    def _main_window_select_block_3(self, item):
        old_key = getattr(self.selected, "key", None)
        self._main_window_select_block_4(item)
        new_key = getattr(self.selected, "key", None)
        if new_key != old_key:
            self._leica_multi_roi_restore = None
            self.image.clear_roi()
            self.image.reset_image_view()

    def change_recorded_pairs(self):
        """Decode selected pairs and retain the current T/Z plane."""
        if (
            self.decode_worker is not None
            or self.export_worker is not None
            or self.scan_worker is not None
        ):
            return
        group = self.current_channel_group()
        snapshot = self._capture_active_roi_snapshot_2()
        self._pending_active_roi_restore = (
            snapshot
            if group
            and snapshot is not None
            and self._confirm_channel_roi_retention()
            else None
        )
        self.histogram.multichannel_panels = None
        self._multichannel_channel_panels = None
        self.image.multichannel_mirror_layout = []
        self.image.multichannel_combined_rois = False
        self.cube = None
        self.image.clear_roi()
        self.image.reset_image_view()
        if not group:
            self.clear_pair_preview()
            return
        dataset = group[0]
        plane = self.current_plane
        if plane is not None and plane >= dataset.plane_count:
            plane = 0 if dataset.plane_count > 1 else None
        self.selected = dataset
        self._show_dataset(dataset)
        self._start_decode(plane)
        self._apply_group_details_2()
        self._update_roi_controls_2()

    def clear_pair_preview(self):
        """Clear images and histograms when no pair is selected."""
        self.cube = None
        if self.selected is not None:
            self.block_title.setText(summary_heading(self.selected, ()))
        self._channel_valid_counts = {}
        self._channel_valid_signature = None
        self.image.clear_image()
        self.histogram.set_histogram(
            summary="Select excitation and emission channels to view data"
        )
        self.fields["Photons"].setText("No recorded pairs selected")
        self.fields["Histogram cube"].setText("Not loaded")
        self.fields["Decoder"].setText("No recorded pairs selected")
        self.fields["Decode time"].setText("-")
        self.backend_label.setText("Decoder: not loaded")
        self.progress.setValue(0)
        self.status_label.setText(
            "Select excitation and emission channels to view data"
        )
        self._update_roi_controls_2()

    def _rebuild_grouped_block_list_2(self):
        selected_key = getattr(self.selected, "key", None)
        by_source = {}
        source_paths: dict[str, Path] = {}
        for group in self._groups_for_window_2():
            identity = self._source_identity(group[0].source)
            by_source.setdefault(identity, []).append(group)
            source_paths.setdefault(identity, group[0].source)
        source_order = []
        for source in list(self.loaded_sources) + list(source_paths.values()):
            identity = self._source_identity(source)
            if identity in by_source and identity not in source_order:
                source_order.append(identity)
        self._channel_groups_by_first_key = {}
        self.block_list.clear()
        selected_item = None
        for identity in source_order:
            source = source_paths[identity]
            header = QListWidgetItem(source.name)
            header_font = header.font()
            header_font.setBold(True)
            header.setFont(header_font)
            header.setToolTip(str(source))
            header.setForeground(QBrush(QColor("#17324d")))
            header.setBackground(QBrush(QColor("#dbeafe")))
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setData(Qt.ItemDataRole.UserRole, None)
            self.block_list.addItem(header)
            for group in by_source[identity]:
                item = _make_group_item_2(group)
                first = group[0]
                self._channel_groups_by_first_key[first.key] = tuple(group)
                self.block_list.addItem(item)
                if selected_key and any(
                    dataset.key == selected_key for dataset in group
                ):
                    selected_item = item
        self.block_list.clearSelection()
        if selected_item is not None:
            self.block_list.setCurrentItem(selected_item)
        if selected_item is not None:
            selected_item.setSelected(True)

    def _selected_channel_mode_2(self):
        group = self.current_channel_group()
        return (
            "__all_channels__"
            if len(group) > 1 or any(item.mosaic is not None for item in group)
            else group[0].key
            if group
            else None
        )

    def _main_window__show_dataset_2(self, dataset: DatasetInfo) -> None:
        self.placeholder.hide()
        self.workspace.show()
        self.block_title.setText(summary_heading(dataset, (dataset,)))
        self.event_flags.set_applicable(True)
        self.fields["Event flags"].setText(
            selection_name(self.event_flags.mask())
        )
        dimensions = (
            f"{dataset.width}"
            " x "
            f"{dataset.height}"
            " x C="
            f"{dataset.channel_index + 1}"
            "/"
            f"{dataset.channel_count}"
        )
        if dataset.t_count > 1:
            dimensions += f" x T={dataset.t_count}"
        if dataset.z_count > 1:
            dimensions += f" x Z={dataset.z_count}"
        dimensions += (
            " | line repeats="
            f"{dataset.line_repetitions}"
            ", frame repeats="
            f"{dataset.frame_repetitions}"
        )
        rows = (
            f"{dataset.decoded_rows:,}"
            " | "
            f"{dataset.repetition_storage_model}"
            " | "
            f"{dataset.dimension_status}"
        )
        self.fields["Dimensions"].setText(dimensions)
        self.fields["Rows"].setText(rows)
        self.fields["Photons"].setText(dataset.raw_photon_label)
        self.fields["Memory block"].setText(dataset.memory_id)
        for name in ("Histogram cube", "Decoder", "Threads", "Decode time"):
            self.fields[name].setText("Preparing")
        self.plane_combo.blockSignals(True)
        self.plane_combo.clear()
        self.plane_combo.addItem("Summed overview", None)
        selector = (
            tile_view(dataset, 0)
            if dataset.mosaic is not None and dataset.tile_index is None
            else dataset
        )
        for linear_plane in range(dataset.preview_plane_count):
            self.plane_combo.addItem(
                selector.plane_label(linear_plane, include_tile=False),
                linear_plane,
            )
        self.plane_combo.setCurrentIndex(
            1
            if dataset.storage_format == "lmsraw"
            and dataset.preview_plane_count > 1
            else 0
        )
        self.plane_combo.blockSignals(False)
        self.plane_controls.setVisible(dataset.preview_plane_count > 1)

    def _render_all_channels_2(self, panels):
        pairs = list(
            dict.fromkeys(panel["dataset"].pair_key for panel in panels)
        )
        if panels and panels[0]["dataset"].mosaic is not None:
            panels.sort(
                key=lambda panel: (
                    pairs.index(panel["dataset"].pair_key),
                    panel["dataset"]
                    .mosaic.tiles[panel["dataset"].tile_index]
                    .row,
                    panel["dataset"]
                    .mosaic.tiles[panel["dataset"].tile_index]
                    .column,
                )
            )
        for panel in panels:
            self._channel_valid_counts[panel["dataset"].key] = int(
                panel["events"]
            )
        composite = _compose_channel_images_2(panels)
        if composite is not None:
            self.image.image = composite
            self.image.contrast.set_intensities(
                [panel["cube"].intensity for panel in panels], panels
            )
            if panels[0]["dataset"].mosaic is not None:
                self.image.shape = (composite.height(), composite.width())
            self.image.multichannel_header_layout = [
                {
                    "fontPixels": panel["header_font_pixels"],
                    "textWidth": panel["header_text_width"],
                    "targetWidth": panel["header_target_width"],
                    "height": panel["header_height"],
                }
                for panel in panels
                if "header_font_pixels" in panel
            ]
            self.image.multichannel_mirror_layout = [
                {
                    "x": float(panel["composite_x"]),
                    "width": float(panel["image"].width()),
                    "height": float(panel["image"].height()),
                    "header": float(panel["header_height"]),
                    "tile": panel["dataset"].tile_index,
                    "pair": panel["dataset"].pair_key,
                }
                for panel in panels
                if panel.get("image") is not None and "composite_x" in panel
            ]
            for geometry, panel in zip(
                self.image.multichannel_mirror_layout, panels, strict=True
            ):
                geometry["header"] += panel.get("composite_y", 0)
            self.image.rois = []
            self.image.roi_colors = []
            self.image.activated_rois = set()
            self.image.drag_start = None
            self.image.drag_current = None
            self.image.update()
        histogram_panels = []
        for position, panel in enumerate(panels, 1):
            dataset = panel["dataset"]
            title = _channel_description_2(dataset, position)
            if dataset.mosaic is not None and dataset.tile_index is not None:
                tile = dataset.mosaic.tiles[dataset.tile_index]
                title = f"Tile {tile.row + 1}, {tile.column + 1}"
                if len(pairs) > 1:
                    title += "\n" + _channel_description_2(dataset, position)
            histogram_panels.append(
                {
                    "title": title,
                    "values": panel["values"],
                    "color": QColor(
                        ("#1473b8", "#d97706", "#6f42c1", "#16856b")[
                            (position - 1)
                            % len(("#1473b8", "#d97706", "#6f42c1", "#16856b"))
                        ]
                    ),
                    "photons": int(panel["events"]),
                    "mosaic_pair_key": dataset.pair_key
                    if dataset.mosaic is not None
                    else None,
                    "mosaic_tile_index": dataset.tile_index,
                    "mosaic_pair_title": "Mosaic\n"
                    + _channel_description_2(dataset),
                    "x_axis_label": (
                        f"Time bins | {dataset.clock_period_s * 1e12:.2f} "
                        "ps/bin"
                        if dataset.clock_period_s
                        else "Time bins"
                    ),
                }
            )
        self.histogram.multichannel_panels = histogram_panels
        self._multichannel_channel_panels = list(panels)
        self.histogram.multichannel_scope = "All Pixels"
        self.histogram.numbered_roi_legend_visible = False
        self.histogram.title = "Pixel Photon-Arrival Histograms"
        self.histogram.summary = (
            f"{sum(panel['events'] for panel in panels):,} photons"
        )
        self.histogram.message = ""
        self.histogram.update()
        self.cube = None
        self.image.multichannel_combined_rois = False
        self.combine_rois_checkbox.setChecked(False)
        self._update_roi_controls_2()
        dtypes = sorted({panel["dtype"] for panel in panels})
        self.fields["Histogram cube"].setText(
            f"{sum(panel['nbytes'] for panel in panels) / 1000000.0:.1f}"
            " MB total, "
            f"{'/'.join(dtypes)}"
        )
        self.fields["Decoder"].setText(
            _unique_join_2(panel["backend"] for panel in panels)
        )
        self.fields["Decode time"].setText(
            f"{sum(panel['elapsed'] for panel in panels):.3f} s total"
        )
        self.status_label.setText(
            "Ready: "
            f"""{f"{sum(panel['events'] for panel in panels):,}"!s}"""
            " photons across "
            f"{len(panels):d}"
            " channels | "
            f"{_unique_join_2(panel['backend'] for panel in panels)!s}"
        )
        self._apply_group_details_2()
        if panels and panels[0]["dataset"].mosaic is not None:
            totals = {}
            for panel in panels:
                key = panel["dataset"].pair_key
                totals[key] = totals.get(key, 0) + panel["events"]
            self._channel_valid_counts.update(totals)
            self._apply_group_details_2()
            dataset = panels[0]["dataset"]
            layout = dataset.mosaic
            self.fields["Dimensions"].setText(
                f"{layout.columns} x {layout.rows} tiles | "
                f"{dataset.width} x {dataset.height} pixels per tile | "
                f"T={dataset.t_count}, Z={dataset.z_count}"
            )
            self.image_title.setText(
                f"{layout.columns} x {layout.rows} tiles | "
                + (
                    f"Ex. {dataset.excitation_label} / "
                    f"Em. {dataset.emission_filter_band}"
                    if len(totals) == 1
                    else f"{len(totals)} excitation/emission pairs"
                )
            )
            self.fields["Rows"].setText(
                f"{sum(panel['cube'].decoded_rows for panel in panels):,} "
                f"rows | {dataset.dimension_status}\n"
                f"{dataset.frame_repetitions} frame repeats per tile; "
                f"{dataset.line_repetitions} line repeats"
            )
            self.image_title.show()
            self.status_label.setText(
                f"Ready: {sum(totals.values()):,} photons across "
                f"{layout.columns * layout.rows} tiles"
                + (f" x {len(totals)} pairs" if len(totals) > 1 else "")
            )
        else:
            self.image_title.hide()
        self._report_channel_arrival_window(panels)
        snapshot = getattr(self, "_pending_active_roi_restore", None)
        self._pending_active_roi_restore = None
        if self._restore_active_roi_snapshot_2(snapshot):
            self._refresh_all_channel_rois_2()

    def _report_channel_arrival_window(self, panels):
        """Report exclusions across every displayed channel and tile."""
        excluded = sum(panel["cube"].overflow_events for panel in panels)
        self.fields["Histogram cube"].setToolTip(
            f"Arrival window excludes {excluded:,} selected photons "
            "across the displayed images; the same window policy "
            "is used for calibrated exports."
        )
        if excluded:
            self.status_label.setText(
                self.status_label.text()
                + f" | {excluded:,} outside arrival window"
            )

    @abstractmethod
    def _components_ready(self) -> bool:
        """Require the final Qt workspace to combine all components."""
        raise NotImplementedError
