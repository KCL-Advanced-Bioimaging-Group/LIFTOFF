"""Maintained desktop component: workspace."""

from __future__ import annotations

import os
import re
from pathlib import Path
from time import perf_counter

import numpy as np
from PySide6 import QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
)

from .dataset import DatasetInfo
from .gui_exports import IcsExportDialog, PtuExportDialog
from .gui_helpers import _group_key_2, _matching_plane_index_2
from .gui_models import connect_signal
from .gui_workers import IcsExportWorker, PtuExportWorker, ScanWorker
from .gui_workspace_channels import WorkspaceChannels
from .gui_workspace_layout import WorkspaceLayout
from .gui_workspace_preview import WorkspacePreview
from .gui_workspace_rois import WorkspaceRois


class MainWindow(
    WorkspaceLayout, WorkspaceChannels, WorkspaceRois, WorkspacePreview
):
    """Desktop workspace lifecycle, controls, and data ownership."""

    def _hide_redundant_details_2(self):
        fields = getattr(self, "fields", {})
        for field_name, displayed_name in (
            ("Event flags", "Photon filter"),
            ("Threads", "Threads"),
        ):
            value = fields.get(field_name)
            if value is not None:
                value.hide()
                parent = value.parentWidget()
                if parent is not None:
                    for label in parent.findChildren(QLabel):
                        if label.text().strip() in (
                            field_name,
                            displayed_name,
                        ):
                            label.hide()
        selector = getattr(self, "event_flags", None)
        active_label = getattr(selector, "selection_label", None)
        if active_label is not None:
            active_label.clear()
            active_label.hide()
            active_label.setMinimumHeight(0)
            active_label.setMaximumHeight(0)

    def _set_interaction_tool_2(self, tool, checked):
        buttons = {
            "zoom_in": self.zoom_in_button,
            "zoom_out": self.zoom_out_button,
            "pan": self.pan_button,
        }
        if checked:
            for name, button in buttons.items():
                if name != tool:
                    button.blockSignals(True)
                    button.setChecked(False)
                    button.blockSignals(False)
            self.image.interaction_tool = tool
        elif self.image.interaction_tool == tool:
            self.image.interaction_tool = None
        self.image.update_interaction_cursor()

    def show_source_menu(self, point):
        """Show source menu."""
        item = self.block_list.itemAt(point)
        if item is None or item.data(Qt.ItemDataRole.UserRole) is not None:
            return
        source_text = item.data(257)
        if not source_text:
            return
        menu = QtWidgets.QMenu(self.block_list)
        action = menu.addAction("Clear this data file")
        action.setEnabled(
            self.scan_worker is None
            and self.decode_worker is None
            and (self.export_worker is None)
        )
        selected = menu.exec(self.block_list.viewport().mapToGlobal(point))
        if selected is action:
            self.remove_source_data(Path(source_text))

    def _main_window__scan_complete_3(
        self, datasets, elapsed: float, error: str
    ) -> None:
        scanned_paths, self.pending_scan_paths = (self.pending_scan_paths, [])
        self._busy(False)
        self.block_list.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.scan_worker = None
        if self._closing:
            return
        if error:
            if error != "Cancelled":
                QMessageBox.critical(self, "LIF indexing failed", error)
            self.status_label.setText(
                "Indexing cancelled"
                if error == "Cancelled"
                else "Indexing failed"
            )
            return
        loaded = {self._source_identity(path) for path in self.loaded_sources}
        for path in scanned_paths:
            if self._source_identity(path) not in loaded:
                self.loaded_sources.append(path)
                loaded.add(self._source_identity(path))
        existing_keys = {dataset.key for dataset in self.datasets}
        additions = []
        for dataset in datasets:
            if dataset.key not in existing_keys:
                additions.append(dataset)
                existing_keys.add(dataset.key)
        self.datasets.extend(additions)
        self._rebuild_block_list()
        self.export_button.setEnabled(bool(self.datasets))
        self.ptu_export_button.setEnabled(bool(self.datasets))
        self.status_label.setText(
            "Found "
            f"{len(additions)}"
            " FLIM detector dataset(s) in "
            f"{elapsed:.2f}"
            " s; "
            f"{len(self.datasets)}"
            " total from "
            f"{len(self.loaded_sources)}"
            " open LIF file(s)"
        )

    def _tag_source_headers_2(self):
        """Attach the source path to each blue LIF header item."""
        for row in range(self.block_list.count()):
            item = self.block_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                continue
            source_text = item.toolTip().strip()
            if source_text:
                item.setData(257, source_text)

    def _main_window__rebuild_block_list_3(self):
        return self._rebuild_grouped_block_list_2()

    def _sync_plane_selector_2(self, requested_plane):
        """Update presentation state without emitting another decode
        request.
        """
        combo = getattr(self, "plane_combo", None)
        if combo is None:
            return False
        index = _matching_plane_index_2(combo, requested_plane)
        if index < 0:
            return False
        previous_blocked = combo.blockSignals(True)
        try:
            combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(previous_blocked)
        self._plane_selector_sync_value = requested_plane
        return True

    def _active_snapshot_2(self):
        self.image.ensure_interaction_state()
        self.image.ensure_roi_colors()
        indices = sorted(
            index
            for index in self.image.activated_rois
            if 0 <= index < len(self.image.rois)
        )
        return [
            (tuple(self.image.rois[index]), self.image.roi_colors[index])
            for index in indices
        ]

    def _main_window_show_pixel_3(self, x, y):
        if self.cube is None:
            return
        if self.image.activated_rois:
            self._main_window__refresh_roi_histogram_3()
            return
        values = np.asarray(self.cube.pixel(x, y), dtype=np.uint64)
        self.histogram.set_series(
            [(f"Pixel {x}, {y}", values, "#1769AA")],
            title=f"Pixel arrival histogram — Pixel {x}, {y}",
            summary=self._bin_summary_2(values.sum()),
        )

    def _main_window_clear_data_5(self) -> None:
        if self.decode_worker:
            self.decode_worker.cancel()
        if self.scan_worker:
            self.scan_worker.cancel()
        if self.export_worker:
            self.export_worker.cancel()
        self.cube = None
        self.selected = None
        self.current_plane = None
        self.datasets = []
        self.loaded_sources = []
        self.pending_scan_paths = []
        self.decode_failures.clear()
        self.block_list.clear()
        self.image.clear_image()
        self.histogram.set_histogram()
        self._set_empty()
        self.status_label.setText("Ready")
        self.backend_label.setText("Decoder: not loaded")
        self.export_button.setEnabled(False)
        self.ptu_export_button.setEnabled(False)

    def _main_window_clear_data_4(self):
        self._main_window_clear_data_5()
        self.image.reset_image_view()

    def _main_window__busy_3(self, busy: bool) -> None:
        busy = busy or self._closing
        self.plane_controls.setEnabled(not busy)
        self.event_flags.selection_busy = busy
        self.event_flags.set_applicable(not busy)
        self.open_button.setEnabled(not busy)
        self.thread_spin.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)
        self.export_button.setEnabled(not busy and bool(self.datasets))
        self.ptu_export_button.setEnabled(not busy and bool(self.datasets))
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 100)

    def _first_dataset_item_2(self):
        for row in range(self.block_list.count()):
            item = self.block_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is not None:
                return item
        return None

    def _source_matches_2(self, candidate, identity):
        try:
            return self._source_identity(candidate) == identity
        except OSError, TypeError, ValueError:
            return False

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.build_channel_controls(*args, **kwargs)
        self.block_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        connect_signal(
            self.block_list.customContextMenuRequested,
            lambda point, window=self: window.show_source_menu(point),
        )

    def _set_empty(self) -> None:
        self.workspace.hide()
        self.placeholder.show()
        self.progress.setValue(0)

    def open_files(self) -> None:
        """Compute open files."""
        if not self._can_import():
            return
        names, _ = QFileDialog.getOpenFileNames(
            self,
            "Open Leica LIF files",
            "",
            "Leica LIF (*.lif);;All files (*.*)",
        )
        self._load_files([Path(name) for name in names])

    def _can_import(self) -> bool:
        return self.open_button.isEnabled() and all(
            worker is None
            for worker in (
                self.scan_worker,
                self.decode_worker,
                self.export_worker,
            )
        )

    def _dropped_lif_paths(self, event) -> list[Path]:
        if (
            not self._can_import()
            or not event.possibleActions() & Qt.DropAction.CopyAction
        ):
            return []
        paths = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if (
                path.suffix.lower() == ".lif"
                and path.is_file()
                and (path not in paths)
            ):
                paths.append(path)
        return paths

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Compute drag enter event."""
        if self._dropped_lif_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        """Compute drag move event."""
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        """Compute drop event."""
        paths = self._dropped_lif_paths(event)
        if not paths:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self._load_files(paths)

    def _load_files(self, paths: list[Path]) -> None:
        if not paths or not self._can_import():
            return
        known = {self._source_identity(path) for path in self.loaded_sources}
        new_paths = []
        for path in paths:
            resolved = path.expanduser().resolve()
            identity = self._source_identity(resolved)
            if identity not in known:
                known.add(identity)
                new_paths.append(resolved)
        if not new_paths:
            self.status_label.setText("Selected LIF file(s) are already open")
            return
        self.pending_scan_paths = new_paths
        self._busy(True)
        self.block_list.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Indexing LIF container")
        self.scan_worker = ScanWorker(new_paths)
        connect_signal(self.scan_worker.status, self.status_label.setText)
        connect_signal(self.scan_worker.completed, self._scan_complete)
        self.scan_worker.start()

    def _scan_complete(self, datasets, elapsed, error):
        self._main_window__scan_complete_3(datasets, elapsed, error)
        if not error:
            groups = self._groups_for_window_2()
            channel_count = sum(len(group) for group in groups)
            multi_count = sum(1 for group in groups if len(group) > 1)
            self.status_label.setText(
                "Found "
                f"{len(groups):d}"
                " FLIM image(s), including "
                f"{multi_count:d}"
                " multi-channel image(s) ("
                f"{channel_count:d}"
                " detector channels), in "
                f"{elapsed:.2f}"
                " s; "
                f"{len(self.loaded_sources):d}"
                " open LIF file(s)"
            )

    @staticmethod
    def _source_identity(path: Path) -> str:
        return os.path.normcase(str(path.expanduser().resolve()))

    def _rebuild_block_list(self):
        self._main_window__rebuild_block_list_3()
        self._tag_source_headers_2()

    def select_block(self, item):
        """Compute select block."""
        if (
            self.scan_worker is not None
            or self.decode_worker is not None
            or self.export_worker is not None
        ):
            return None
        self._pending_active_roi_restore = None
        dataset = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(dataset, DatasetInfo):
            return None
        group = getattr(self, "_channel_groups_by_first_key", {}).get(
            getattr(dataset, "key", None),
            (dataset,) if isinstance(dataset, DatasetInfo) else (),
        )
        if group:
            previous_key = (
                _group_key_2(self._channel_group[0])
                if self._channel_group
                else None
            )
            current_key = _group_key_2(group[0])
            if previous_key != current_key:
                self._channel_valid_counts = {}
                self._channel_valid_signature = None
            self._channel_group = tuple(group)
            self.pair_selector.set_datasets(
                self._channel_group, previous_key == current_key
            )
            self.histogram.multichannel_panels = None
            self._multichannel_channel_panels = None
            self.image.multichannel_mirror_layout = []
            self.image.multichannel_combined_rois = False
        active = self.current_channel_group() if group else ()
        if group and not active:
            self.selected = group[0]
            self.clear_pair_preview()
            return None
        if active:
            mode = self._selected_channel_mode_2()
            target = next(
                (candidate for candidate in active if candidate.key == mode),
                active[0],
            )
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, target)
        result = self._main_window_select_block_3(item)
        self._apply_group_details_2()
        self._hide_redundant_details_2()
        self._update_roi_controls_2()
        return result

    def _start_decode(self, linear_plane):
        self.start_channel_preview(linear_plane)
        self._sync_plane_selector_2(linear_plane)

    def _decode_status(self, message: str) -> None:
        self.status_label.setText(message)
        match = re.search("(\\d+)/(\\d+) rows", message)
        if match and int(match.group(2)):
            self.progress.setValue(
                round(int(match.group(1)) * 100 / int(match.group(2)))
            )

    def _decode_complete(self, cube, error):
        sequence = getattr(self, "_multichannel_sequence", None)
        if sequence is not None:
            requested_plane = sequence.get("linear_plane")
        else:
            requested_plane = getattr(self, "current_plane", None)
        result = self.complete_preview(cube, error)
        self._sync_plane_selector_2(requested_plane)
        return result

    def _show_dataset(self, dataset):
        self._main_window__show_dataset_2(dataset)
        group = self.current_channel_group()
        if group:
            self._apply_group_details_2()
        self._hide_redundant_details_2()

    def _event_flags_changed(self, *args, **kwargs):
        if (
            self._pending_active_roi_restore is None
            and getattr(self, "_multichannel_channel_panels", None)
            and (self._selected_channel_mode_2() == "__all_channels__")
        ):
            self._pending_active_roi_restore = (
                self._capture_active_roi_snapshot_2()
            )
        return self._main_window__event_flags_changed_5(*args, **kwargs)

    def _plane_changed(self, *args, **kwargs):
        if (
            self._pending_active_roi_restore is None
            and getattr(self, "_multichannel_channel_panels", None)
            and (self._selected_channel_mode_2() == "__all_channels__")
        ):
            self._pending_active_roi_restore = (
                self._capture_active_roi_snapshot_2()
            )
        return self._main_window__plane_changed_5(*args, **kwargs)

    def _step_plane(self, direction: int) -> None:
        if (
            not self.plane_controls.isVisible()
            or self.decode_worker is not None
        ):
            return
        target = max(
            0,
            min(
                self.plane_combo.count() - 1,
                self.plane_combo.currentIndex() + direction,
            ),
        )
        self.plane_combo.setCurrentIndex(target)

    def show_pixel(self, x, y):
        """Compute show pixel."""
        if self.show_channel_pixel(x, y):
            return
        if getattr(self, "cube", None) is None:
            return
        image = getattr(self, "image", None)
        if image is not None and getattr(image, "activated_rois", set()):
            self._refresh_roi_histogram()
            return
        self._main_window_show_pixel_3(x, y)

    def _bin_width_ps(self) -> float:
        """Label native-period previews using the acquisition clock."""
        selected = self.selected
        if selected is not None and selected.clock_period_s:
            if selected.clock_period_s > 0:
                return selected.clock_period_s * 1e12
        cube = self.cube
        return (
            1e12
            / selected.laser_frequency_hz
            / max(1, cube.counts.shape[0] if cube is not None else 128)
            if selected is not None and selected.laser_frequency_hz
            else 0.0
        )

    def export_ics(self) -> None:
        """Compute export ics."""
        if (
            not self.datasets
            or self.decode_worker is not None
            or self.export_worker is not None
        ):
            return
        states = {}
        for dataset in self.datasets:
            if (
                self.selected
                and self.cube is not None
                and (dataset.key == self.selected.key)
            ):
                states[dataset.key] = "decoded"
            elif dataset.key in self.decode_failures:
                states[dataset.key] = "failed"
            elif (
                dataset.width <= 0
                or dataset.height <= 0
                or dataset.decoded_rows <= 0
            ):
                states[dataset.key] = "unavailable"
            else:
                states[dataset.key] = "not decoded"
        dialog = IcsExportDialog(
            self.datasets,
            states,
            self,
            self.event_flags.mask(),
            reflection_windows=self.reflection_filter.export_windows(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_datasets()
        cached = (
            {self.selected.key: self.cube}
            if self.selected is not None
            and self.cube is not None
            and (self.current_plane is None)
            else {}
        )
        self.export_worker = IcsExportWorker(
            selected,
            Path(dialog.destination.text()),
            dialog.options(self.thread_spin.value()),
            dialog.selected_filenames(),
            cached,
            dialog.selected_plane_selection(),
            dialog.selected_output_directories(),
        )
        connect_signal(self.export_worker.status, self._export_status)
        connect_signal(self.export_worker.completed, self._export_complete)
        self._busy(True)
        self.block_list.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Exporting selected detector/T/Z outputs")
        self.export_worker.start()

    def _export_status(
        self, message: str, completed: float, total: float
    ) -> None:
        self.status_label.setText(message)
        self.progress.setValue(round(completed * 100 / total) if total else 0)

    def _export_complete(self, results, error: str) -> None:
        self.block_list.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.export_worker = None
        self._busy(False)
        if self._closing:
            return
        if error:
            self.progress.setValue(0)
            self.status_label.setText(error)
            if error != "Cancelled":
                QMessageBox.critical(self, "ICS export failed", error)
            return
        exported = sum(
            result.get("status") == "exported" for result in results
        )
        failed = [
            result for result in results if result.get("status") == "failed"
        ]
        skipped = sum(result.get("status") == "skipped" for result in results)
        self.progress.setValue(100)
        self.status_label.setText(
            "ICS export complete: "
            f"{exported}"
            " exported, "
            f"{skipped}"
            " skipped, "
            f"{len(failed)}"
            " failed"
        )
        details = "\n".join(
            f"{item['dataset']}: {item['error']}" for item in failed[:8]
        )
        excluded = sum(result.get("excludedPhotons", 0) for result in results)
        QMessageBox.information(
            self,
            "ICS export complete",
            f"Exported: {exported}\nSkipped: {skipped}\nFailed: {len(failed)}"
            + (
                f"\nPhotons excluded outside the time window: {excluded:,}"
                if excluded
                else ""
            )
            + (f"\n\n{details}" if details else ""),
        )

    def export_ptu(self) -> None:
        """Compute export ptu."""
        if (
            not self.datasets
            or self.decode_worker is not None
            or self.export_worker is not None
        ):
            return
        states = {}
        for dataset in self.datasets:
            if (
                self.selected
                and self.cube is not None
                and (dataset.key == self.selected.key)
            ):
                states[dataset.key] = "preview decoded"
            elif dataset.key in self.decode_failures:
                states[dataset.key] = "preview failed"
            elif (
                dataset.width <= 0
                or dataset.height <= 0
                or dataset.decoded_rows <= 0
            ):
                states[dataset.key] = "unavailable"
            else:
                states[dataset.key] = "ready"
        dialog = PtuExportDialog(
            self.datasets,
            states,
            self,
            self.event_flags.mask(),
            reflection_windows=self.reflection_filter.export_windows(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.export_worker = PtuExportWorker(
            dialog.selected_datasets(),
            Path(dialog.destination.text()),
            dialog.options(),
            dialog.selected_filenames(),
            dialog.selected_planes(),
            dialog.selected_output_directories(),
        )
        connect_signal(self.export_worker.status, self._export_status)
        connect_signal(self.export_worker.completed, self._ptu_export_complete)
        self._busy(True)
        self.block_list.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.status_label.setText("Exporting selected PTU event files")
        self.export_worker.start()

    def _ptu_export_complete(self, results, error: str) -> None:
        self.block_list.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.export_worker = None
        self._busy(False)
        if self._closing:
            return
        if error:
            self.progress.setValue(0)
            self.status_label.setText(error)
            if error != "Cancelled":
                QMessageBox.critical(self, "PTU export failed", error)
            return
        exported = sum(
            result.get("status") == "exported" for result in results
        )
        skipped = sum(result.get("status") == "skipped" for result in results)
        failed = [
            result for result in results if result.get("status") == "failed"
        ]
        self.progress.setValue(100)
        self.status_label.setText(
            "PTU export complete: "
            f"{exported}"
            " exported, "
            f"{skipped}"
            " skipped, "
            f"{len(failed)}"
            " failed"
        )
        details = "\n".join(
            f"{item['dataset']}: {item['error']}" for item in failed[:8]
        )
        QMessageBox.information(
            self,
            "PTU export complete",
            f"Exported: {exported}\nSkipped: {skipped}\nFailed: {len(failed)}"
            + (f"\n\n{details}" if details else ""),
        )

    def cancel_active(self) -> None:
        """Compute cancel active."""
        if self.scan_worker:
            self.scan_worker.cancel()
            self.status_label.setText("Cancelling indexing")
        elif self.decode_worker:
            self.decode_worker.cancel()
            self.status_label.setText("Cancelling decode")
        elif self.export_worker:
            self.export_worker.cancel()
            self.status_label.setText("Cancelling export")

    def clear_data(self):
        """Compute clear data."""
        self.reflection_filter.retain_datasets(set())
        self._main_window_clear_data_4()
        self._channel_group = ()
        self._channel_groups_by_first_key = {}
        self._multichannel_sequence = None
        self._multichannel_channel_panels = None
        self._channel_valid_counts = {}
        self._channel_valid_signature = None
        self._pending_active_roi_restore = None
        self.pair_selector.set_datasets(())
        self.histogram.multichannel_panels = None
        self.image.multichannel_header_layout = []
        self.image.multichannel_mirror_layout = []
        self.image.last_mirrored_roi_layout = []
        self.image.multichannel_combined_rois = False
        self._update_roi_controls_2()

    def _busy(self, value):
        self._main_window__busy_3(value)
        if hasattr(self, "pair_selector"):
            self.pair_selector.setEnabled(not bool(value))
        self._hide_redundant_details_2()

    def _update_elapsed(self) -> None:
        self.fields["Decode time"].setText(
            f"{perf_counter() - self.decode_started:.1f} s elapsed"
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        """Compute close event."""
        workers = [
            worker
            for worker in (
                self.scan_worker,
                self.decode_worker,
                self.export_worker,
            )
            if worker is not None
        ]
        if workers:
            self._closing = True
            for worker in workers:
                worker.cancel()
            self._busy(True)
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling work before closing")
            event.ignore()
            QTimer.singleShot(50, self.close)
            return
        event.accept()

    def remove_source_data(self, source: Path) -> bool:
        """Remove one loaded LIF source while leaving every other source
        intact.
        """
        if self.scan_worker is not None or self.decode_worker is not None:
            self.status_label.setText(
                "Wait for the current operation before clearing a data file"
            )
            return False
        source = Path(source)
        identity = self._source_identity(source)
        matching_sources = [
            path
            for path in self.loaded_sources
            if self._source_matches_2(path, identity)
        ]
        if not matching_sources:
            return False
        selected_removed = (
            self.selected is not None
            and self._source_matches_2(self.selected.source, identity)
        )
        self.loaded_sources = [
            path
            for path in self.loaded_sources
            if not self._source_matches_2(path, identity)
        ]
        self.datasets = [
            dataset
            for dataset in self.datasets
            if not self._source_matches_2(dataset.source, identity)
        ]
        remaining_keys = {dataset.key for dataset in self.datasets}
        self.reflection_filter.retain_datasets(remaining_keys)
        self.decode_failures = {
            key: value
            for key, value in self.decode_failures.items()
            if key in remaining_keys
        }
        if not self.loaded_sources:
            self.clear_data()
            self.status_label.setText(
                f"Cleared {source.name}; no LIF files remain open"
            )
            return True
        self._rebuild_block_list()
        if selected_removed:
            self.selected = None
            self.cube = None
            replacement = self._first_dataset_item_2()
            if replacement is not None:
                self.block_list.setCurrentItem(replacement)
                replacement.setSelected(True)
                self.select_block(replacement)
        self.status_label.setText(
            "Cleared "
            f"{source.name!s}"
            "; "
            f"{len(self.loaded_sources):d}"
            " open LIF file(s)"
        )
        return True

    def _show_source_menu(self, point) -> None:
        self.show_source_menu(point)

    def _clear_source_data(self, source: Path) -> bool:
        return self.remove_source_data(source)

    def _components_ready(self) -> bool:
        """Confirm the concrete workspace combines all view
        components.
        """
        return True
