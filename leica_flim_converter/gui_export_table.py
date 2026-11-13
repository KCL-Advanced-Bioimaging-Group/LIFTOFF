"""Shared compact export-table model and preflight behavior."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dataset import DatasetInfo
from .event_flags import PRIMARY_EVENT_FLAGS
from .gui_export_reflection import ExportReflectionSelection
from .gui_helpers import (
    _erd_format_data_size_2,
    _esp_validate_dataset_2,
    _plane_coordinates_2,
    _row_label_2,
    _selected_groups_for_other_axis_2,
    _source_export_directory_3,
)
from .gui_models import connect_signal, required_table_item
from .mosaic import MOSAIC_INTEGRATION_ERROR
from .raster_timing import raster_timing
from .timing import require_calibration, time_grid


def add_export_metadata_note(layout: QVBoxLayout, prefix: str = "") -> None:
    """Describe the companions in both export dialogs."""
    note = QLabel(
        prefix + "Each export includes embedded acquisition metadata, "
        "JSON provenance, a CSV table and a browser-readable HTML report."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#53616e")
    layout.addWidget(note)


class ExportTableMixin(QDialog):
    """Shared compact export-table model and axis expansion controls."""

    names: dict[str, str]
    source_folders: QCheckBox
    destination: QLineEdit
    destination_browse: QPushButton
    export_format: str
    table: QTableWidget
    row_targets: list[tuple[DatasetInfo, int | None] | None]
    datasets: list[DatasetInfo]
    _compact_axis_modes: dict[str, dict[str, bool]]
    dimension_mode: QComboBox
    bins: QComboBox
    timing_mode: QComboBox
    pixel_ticks: QtWidgets.QSpinBox
    group_rows: dict[str, list[int]]
    group_headers: dict[str, int]
    header_groups: dict[int, str]

    def _selection_changed(self, *args: object) -> None:
        raise NotImplementedError

    def _esp_apply_status_2(self):
        table = self.table
        header = table.horizontalHeaderItem(9)
        if header is not None:
            header.setText("Status")
        readiness = {}
        prior_states = {}
        for row, target in enumerate(self.row_targets):
            if target is None:
                continue
            state_item = required_table_item(table, row, 9)
            if state_item is not None:
                prior_states.setdefault(
                    target[0].key, state_item.text().strip().lower()
                )
        for dataset in self.datasets:
            ready, detail = _esp_validate_dataset_2(dataset)
            timing_ready, timing_detail, quality = self._timing_state(dataset)
            if not timing_ready:
                ready, detail = False, timing_detail
            self._set_timing_quality(dataset.key, quality)
            if (
                self.export_format == "ics"
                and dataset.mosaic is not None
                and self.dimension_mode.currentData() == "integrate"
            ):
                ready, detail = False, MOSAIC_INTEGRATION_ERROR
            elif (
                self.export_format == "ics"
                and prior_states.get(dataset.key) == "failed"
            ):
                ready = False
                detail = "The most recent ICS decode attempt failed"
            readiness[dataset.key] = (ready, detail)
        table.blockSignals(True)
        try:
            for row, target in enumerate(self.row_targets):
                if target is None:
                    continue
                dataset, _plane = target
                ready, detail = readiness[dataset.key]
                state_item = required_table_item(table, row, 9)
                if state_item is not None:
                    state_item.setText("Ready" if ready else "Failed")
                    state_item.setToolTip(detail)
                check_item = required_table_item(table, row, 0)
                if check_item is not None and ready:
                    check_item.setFlags(
                        check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                    )
                    check_item.setToolTip("")
                if check_item is not None and (not ready):
                    check_item.setCheckState(Qt.CheckState.Unchecked)
                    check_item.setFlags(
                        check_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
                    )
                    check_item.setToolTip(f"Cannot export: {detail}")
        finally:
            table.blockSignals(False)
        self._export_readiness = readiness
        for group in self.group_rows:
            self._sync_group_header(group)
        self._selection_changed()
        table.resizeColumnToContents(9)

    def _timing_state(self, dataset):
        try:
            require_calibration(dataset)
            if self.export_format == "ptu":
                timeline = raster_timing(
                    dataset,
                    self.timing_mode.currentData(),
                    self.pixel_ticks.value(),
                )
                return True, "", timeline.quality
            grid = time_grid(dataset, self.bins.currentData())
            quality = (
                "Recorded arrival clock"
                if grid.mode == "native"
                else "Rebinned (recorded clock)"
            )
            return True, "", quality
        except ValueError as exc:
            return False, str(exc), "Unavailable"

    def _set_timing_quality(self, key, quality):
        previous = self.table.blockSignals(True)
        try:
            for row, target in enumerate(self.row_targets):
                if target is not None and target[0].key == key:
                    item = self.table.item(row, self.table.columnCount() - 2)
                    if item is not None:
                        item.setText(quality)
        finally:
            self.table.blockSignals(previous)

    def _erd_output_column_2(self):
        return self.table.columnCount() - 1

    def _erd_files_column_2(self):
        return self._erd_output_column_2() - 2

    def _erd_restore_and_update_details_2(self):
        table = self.table
        header = table.horizontalHeaderItem(8)
        if header is not None:
            header.setText("Data Size")
        output_column = self._erd_output_column_2()
        files_column = self._erd_files_column_2()
        details = getattr(self, "_export_row_original_details", {})
        for row, values in details.items():
            data_item = required_table_item(table, row, 8)
            output_item = required_table_item(table, row, output_column)
            if data_item is not None:
                data_item.setText(values["data_size"])
            if output_item is not None:
                output_item.setText(values["output"])
            if self.export_format == "ics":
                files_item = required_table_item(table, row, files_column)
                if files_item is not None:
                    files_item.setText(values["files"])
        split_ics = (
            self.export_format == "ics"
            and self.dimension_mode.currentData() == "split"
        )
        for row, target in enumerate(self.row_targets):
            if target is None or table.isRowHidden(row):
                continue
            dataset, _plane = target
            planes = tuple(
                getattr(self, "_compact_row_planes", {}).get(row, ())
            )
            represented_count = max(1, len(planes))
            data_item = required_table_item(table, row, 8)
            if data_item is not None:
                data_item.setText(
                    _erd_format_data_size_2(
                        (dataset.compressed_bytes) * represented_count
                    )
                )
            if self.export_format == "ptu":
                if represented_count > 1:
                    required_table_item(table, row, output_column).setText(
                        f"{represented_count:d} plane-specific PTU files"
                    )
            elif split_ics:
                required_table_item(table, row, files_column).setText(
                    str(represented_count)
                )
                if represented_count > 1:
                    required_table_item(table, row, output_column).setText(
                        f"{represented_count:d} plane-specific ICS files"
                    )
        table.resizeColumnToContents(8)
        if self.export_format == "ics":
            table.resizeColumnToContents(files_column)
        table.resizeColumnToContents(output_column)

    def _erd_refresh_original_filenames_2(self):
        """Capture filename rewrites made by event-filter changes, not
        summaries.
        """
        table = self.table
        output_column = self._erd_output_column_2()
        details = getattr(self, "_export_row_original_details", {})
        summary = re.compile("^\\d+ plane-specific (?:PTU|ICS) files$")
        for row, values in details.items():
            item = required_table_item(table, row, output_column)
            if item is not None and (not summary.match(item.text())):
                values["output"] = item.text()

    def _erd_capture_original_details_2(self):
        table = self.table
        generation = getattr(self, "_compact_original_group_rows", None)
        if getattr(self, "_export_row_details_generation", None) is generation:
            return False
        output_column = self._erd_output_column_2()
        files_column = self._erd_files_column_2()
        details = {}
        for row, target in enumerate(self.row_targets):
            if target is None:
                continue
            details[row] = {
                "data_size": required_table_item(table, row, 8).text(),
                "output": required_table_item(
                    table, row, output_column
                ).text(),
                "files": required_table_item(table, row, files_column).text()
                if self.export_format == "ics"
                else None,
            }
        self._export_row_original_details = details
        self._export_row_details_generation = generation
        return True

    def _dataset_rows_2(self):
        groups = {}
        for row, target in enumerate(self.row_targets):
            if target is None:
                continue
            dataset, plane = target
            groups.setdefault(dataset.key, {"dataset": dataset, "rows": []})[
                "rows"
            ].append((row, plane))
        return groups

    def _axis_state_2(self, dataset):
        return self._compact_axis_modes.setdefault(
            dataset.key, {"t": False, "z": False}
        )

    def _selected_plane_sets_2(self):
        selected = {}
        for row, planes in getattr(self, "_compact_row_planes", {}).items():
            item = self.table.item(row, 0)
            target = self.row_targets[row]
            if (
                item is None
                or target is None
                or item.checkState() != Qt.CheckState.Checked
            ):
                continue
            dataset, _plane = target
            selected.setdefault(dataset.key, set()).update(planes)
        return selected

    def set_axis_mode(self, dataset, axis, expanded):
        """Set axis mode."""
        selected_by_key = self._selected_plane_sets_2()
        selected = selected_by_key.get(dataset.key, set())
        modes = self._axis_state_2(dataset)
        if modes[axis] == bool(expanded):
            return
        if not expanded and selected:
            selected_other = _selected_groups_for_other_axis_2(
                dataset, selected, axis
            )
            expanded_selection = set()
            for plane in range(int(dataset.plane_count)):
                t_index, z_index = _plane_coordinates_2(dataset, plane)
                other_index = z_index if axis == "t" else t_index
                if other_index in selected_other:
                    expanded_selection.add(plane)
            selected_by_key[dataset.key] = expanded_selection
        modes[axis] = bool(expanded)
        self._apply_with_row_details_2(selected_by_key)
        self._selection_changed()

    def _make_axis_menu_4(self, dataset, label):
        button = QtWidgets.QToolButton(self.table)
        button.setObjectName("tzSelectionMenuButton")
        button.setText(label)
        button.setToolTip(
            "Choose whether T-frames and Z-planes are shown separately"
        )
        button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        button.setAutoRaise(True)
        menu = QtWidgets.QMenu(button)
        modes = self._axis_state_2(dataset)
        if int(dataset.z_count) > 1:
            if modes["z"]:
                action = menu.addAction("Select all Z-planes")
                connect_signal(
                    action.triggered,
                    lambda _checked=False, owner=self, item=dataset: (
                        owner.set_axis_mode(item, "z", False)
                    ),
                )
            else:
                action = menu.addAction("Select Z-planes")
                connect_signal(
                    action.triggered,
                    lambda _checked=False, owner=self, item=dataset: (
                        owner.set_axis_mode(item, "z", True)
                    ),
                )
        if int(dataset.t_count) > 1:
            if menu.actions():
                menu.addSeparator()
            if modes["t"]:
                action = menu.addAction("Select all T-frames")
                connect_signal(
                    action.triggered,
                    lambda _checked=False, owner=self, item=dataset: (
                        owner.set_axis_mode(item, "t", False)
                    ),
                )
            else:
                action = menu.addAction("Select T-frames")
                connect_signal(
                    action.triggered,
                    lambda _checked=False, owner=self, item=dataset: (
                        owner.set_axis_mode(item, "t", True)
                    ),
                )
        button.setMenu(menu)
        button.setAccessibleName(label + " selection options")
        return button

    def _make_axis_menu_3(self, dataset, label, _previous=_make_axis_menu_4):
        button = _previous(self, dataset, label)
        button.setText(label)
        return button

    def _compact_filename_text_2(self, dataset, planes):
        if len(planes) <= 1:
            return None
        if dataset.mosaic is not None:
            return (
                f"{len(planes)} tile/plane-specific "
                f"{self.export_format.upper()} files"
            )
        if self.export_format == "ptu":
            return f"{len(planes):d} plane-specific PTU files"
        return f"{len(planes):d} plane-specific ICS files"

    def _initial_plane_selection_2(self):
        selected = {}
        for row, target in enumerate(self.row_targets):
            if target is None:
                continue
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            dataset, plane = target
            if plane is None:
                selected[dataset.key] = set(range(dataset.plane_count))
            else:
                selected.setdefault(dataset.key, set()).add(plane)
        return selected

    def _apply_compact_rows_4(self, selected_by_key=None):
        table = self.table
        table.blockSignals(True)
        try:
            selected_by_key = (
                self._initial_plane_selection_2()
                if selected_by_key is None
                else selected_by_key
            )
            dataset_groups = self._dataset_rows_2()
            self._compact_row_planes = {}
            visible_rows = set()
            for row in range(table.rowCount()):
                table.setRowHidden(row, False)
                widget = table.cellWidget(row, PRIMARY_EVENT_FLAGS)
                if widget is not None:
                    table.removeCellWidget(row, PRIMARY_EVENT_FLAGS)
                    widget.hide()
                    widget.deleteLater()
            for information in dataset_groups.values():
                dataset = information["dataset"]
                rows = information["rows"]
                modes = self._axis_state_2(dataset)
                row_groups = self._compact_row_groups(dataset, rows, modes)
                first_visible = True
                selected = selected_by_key.get(dataset.key, set())
                for entry in row_groups.values():
                    row, _planes = self._set_compact_entry(
                        dataset, modes, entry, selected, first_visible
                    )
                    visible_rows.add(row)
                    first_visible = False
                for row, _plane in rows:
                    if row not in visible_rows:
                        table.setRowHidden(row, True)
            self.group_rows = {
                group: [row for row in rows if row in visible_rows]
                for group, rows in getattr(
                    self, "_compact_original_group_rows", {}
                ).items()
            }
            table.resizeColumnToContents(PRIMARY_EVENT_FLAGS)
        finally:
            table.blockSignals(False)

    def _apply_compact_rows_3(
        self, selected_by_key=None, _previous=_apply_compact_rows_4
    ):
        table = self.table
        stale_widgets = []
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, PRIMARY_EVENT_FLAGS)
            if widget is not None:
                stale_widgets.append(widget)
        result = _previous(self, selected_by_key)
        for widget in stale_widgets:
            widget.hide()
            widget.deleteLater()
        return result

    def _apply_with_row_details_2(
        self, selected_by_key=None, _previous=_apply_compact_rows_3
    ):
        is_new_generation = self._erd_capture_original_details_2()
        if not is_new_generation:
            self._erd_refresh_original_filenames_2()
        result = _previous(self, selected_by_key)
        self._erd_restore_and_update_details_2()
        return result

    def _rename_export_channel_column_2(self):
        tables = self.findChildren(QTableWidget)
        for table in tables:
            for column in range(table.columnCount()):
                header = table.horizontalHeaderItem(column)
                if (
                    header is not None
                    and header.text().strip().casefold() == "channel"
                ):
                    header.setText("Emission filter")

    def _ptu_export_dialog_selected_planes_2(self):
        result = {}
        for row, planes in getattr(self, "_compact_row_planes", {}).items():
            item = self.table.item(row, 0)
            target = self.row_targets[row]
            if (
                item is None
                or target is None
                or item.checkState() != Qt.CheckState.Checked
            ):
                continue
            dataset, _plane = target
            result.setdefault(dataset.key, []).extend(
                int(plane) for plane in planes
            )
        return {key: sorted(set(planes)) for key, planes in result.items()}

    def _correct_estimate_2(self):
        if not hasattr(self, "estimate"):
            return
        text = self.estimate.text()
        selected_planes = self._ptu_export_dialog_selected_planes_2()
        if self.export_format == "ptu":
            file_count = sum(
                len(planes) for planes in selected_planes.values()
            )
            text = re.sub(
                "\\d+ PTU file\\(s\\)", (f"{file_count:d} PTU file(s)"), text
            )
        elif self.dimension_mode.currentData() == "split":
            file_count = sum(
                len(planes) for planes in selected_planes.values()
            )
            text = re.sub("\\d+ file\\(s\\)", f"{file_count:d} file(s)", text)
        self.estimate.setText(text)

    def _compact_row_groups(
        self,
        dataset: DatasetInfo,
        rows: list[tuple[int, int | None]],
        modes: dict[str, bool],
    ) -> dict:
        """Group represented T/Z planes while preserving the first table
        row.
        """
        row_groups = {}
        for row, plane in rows:
            if plane is None:
                group_key = (None, None)
                represented = tuple(range(dataset.plane_count))
            else:
                t_index, z_index = _plane_coordinates_2(dataset, plane)
                group_key = (
                    t_index if modes["t"] else None,
                    z_index if modes["z"] else None,
                )
                represented = ((plane),)
            entry = row_groups.setdefault(
                group_key, {"row": row, "plane": plane, "planes": []}
            )
            entry["planes"].extend(represented)
        return row_groups

    def _set_compact_entry(
        self,
        dataset: DatasetInfo,
        modes: dict[str, bool],
        entry: dict,
        selected: set[int],
        first_visible: bool,
    ) -> tuple[int, tuple[int, ...]]:
        """Set selection state, axis menus, file counts and compact
        filenames.
        """
        table = self.table
        row = entry["row"]
        planes = tuple(sorted(set(entry["planes"])))
        self._compact_row_planes[row] = planes
        check_item = required_table_item(table, row, 0)
        if check_item is not None:
            selected_count = len(set(planes).intersection(selected))
            if selected_count == len(planes) and planes:
                check_item.setCheckState(Qt.CheckState.Checked)
            elif selected_count:
                check_item.setCheckState(Qt.CheckState.PartiallyChecked)
            else:
                check_item.setCheckState(Qt.CheckState.Unchecked)
        label_modes = (
            {"t": False, "z": False} if entry["plane"] is None else modes
        )
        label = _row_label_2(dataset, entry["plane"], label_modes)
        tz_item = required_table_item(table, row, PRIMARY_EVENT_FLAGS)
        if tz_item is not None:
            tz_item.setText(label)
        has_options = (dataset.t_count) > 1 or (dataset.z_count) > 1
        if first_visible and has_options and (entry["plane"] is not None):
            table.setCellWidget(
                row,
                PRIMARY_EVENT_FLAGS,
                self._make_axis_menu_3(dataset, label),
            )
            if tz_item is not None:
                tz_item.setText("")
        compact_filename = (
            self._compact_filename_text_2(dataset, planes)
            if entry["plane"] is not None
            else None
        )
        if compact_filename is not None:
            output_column = table.columnCount() - 1
            output_item = required_table_item(table, row, output_column)
            if output_item is not None:
                output_item.setText(compact_filename)
            if self.export_format == "ics":
                files_item = required_table_item(table, row, output_column - 1)
                if files_item is not None:
                    files_item.setText(str(len(planes)))
        return (row, planes)

    def _sync_group_header(self, group: str) -> None:
        checks = [
            required_table_item(self.table, row, 0)
            for row in self.group_rows[group]
            if required_table_item(self.table, row, 0).flags()
            & Qt.ItemFlag.ItemIsUserCheckable
        ]
        checked = sum(
            item.checkState() == Qt.CheckState.Checked for item in checks
        )
        state = (
            Qt.CheckState.Unchecked
            if checked == 0
            else Qt.CheckState.Checked
            if checked == len(checks)
            else Qt.CheckState.PartiallyChecked
        )
        self.table.blockSignals(True)
        required_table_item(
            self.table, self.group_headers[group], 0
        ).setCheckState(state)
        self.table.blockSignals(False)

    def _toggle_group(self, group: str, state: Qt.CheckState) -> None:
        requested = (
            Qt.CheckState.Checked
            if state == Qt.CheckState.Checked
            else Qt.CheckState.Unchecked
        )
        self.table.blockSignals(True)
        for row in self.group_rows[group]:
            item = required_table_item(self.table, row, 0)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(requested)
        self.table.blockSignals(False)
        self._sync_group_header(group)

    def _set_all(self, state: Qt.CheckState) -> None:
        self.table.blockSignals(True)
        for row, target in enumerate(self.row_targets):
            if target is None:
                continue
            item = required_table_item(self.table, row, 0)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(state)
        self.table.blockSignals(False)
        for group in self.group_rows:
            self._sync_group_header(group)
        self._selection_changed()

    def selected_datasets(self) -> list[DatasetInfo]:
        """Compute selected datasets."""
        dialog = self
        selected: dict[str, DatasetInfo] = {}
        for row, planes in getattr(dialog, "_compact_row_planes", {}).items():
            item = dialog.table.item(row, 0)
            target = dialog.row_targets[row]
            if (
                item is None
                or target is None
                or item.checkState() != Qt.CheckState.Checked
                or (not planes)
            ):
                continue
            dataset, _plane = target
            selected.setdefault(dataset.key, dataset)
        return list(selected.values())

    def selected_filenames(self) -> dict[str, str]:
        """Compute selected filenames."""
        return {
            dataset.key: self.names[dataset.key]
            for dataset in self.selected_datasets()
        }

    def selected_output_directories(self) -> dict[str, Path]:
        """Compute selected output directories."""
        if not self.source_folders.isChecked():
            return {}
        return {
            dataset.key: _source_export_directory_3(dataset)
            for dataset in self.selected_datasets()
        }

    def _destination_mode_changed(self, use_source_folders: bool) -> None:
        self.destination.setEnabled(not use_source_folders)
        self.destination_browse.setEnabled(not use_source_folders)
        self._selection_changed()

    def _add_source_heading(
        self, header_row: int, source: Path, enabled: bool
    ) -> None:
        """Create the shared source heading and group selection
        control.
        """
        group_check = QTableWidgetItem()
        group_check.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            if enabled
            else Qt.ItemFlag.NoItemFlags
        )
        group_check.setCheckState(Qt.CheckState.Unchecked)
        group_check.setBackground(QColor("#e8eef5"))
        group_check.setToolTip(f"Select every exportable item from {source}")
        heading = QTableWidgetItem(source.name)
        heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
        heading.setBackground(QColor("#e8eef5"))
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        heading.setToolTip(str(source))
        self.table.setItem(header_row, 0, group_check)
        self.table.setItem(header_row, 1, heading)
        self.table.setSpan(header_row, 1, 1, self.table.columnCount() - 1)

    def _build_export_selection(self, layout: QVBoxLayout) -> QFormLayout:
        """Construct shared selection and destination controls for both
        export formats.
        """
        layout.addWidget(self.table, 1)
        selection = QHBoxLayout()
        select_all = QPushButton("Select All")
        clear = QPushButton("Clear Selection")
        connect_signal(
            select_all.clicked, lambda: self._set_all(Qt.CheckState.Checked)
        )
        connect_signal(
            clear.clicked, lambda: self._set_all(Qt.CheckState.Unchecked)
        )
        selection.addWidget(select_all)
        selection.addWidget(clear)
        selection.addStretch()
        self.estimate = QLabel("No blocks selected")
        selection.addWidget(self.estimate)
        layout.addLayout(selection)
        settings = QFormLayout()
        destination_row = QHBoxLayout()
        self.destination = QLineEdit(str(Path.home() / "Desktop"))
        browse = QPushButton("Choose folder")
        self.destination_browse = browse
        connect_signal(browse.clicked, self._choose_folder)
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(browse)
        destination_widget = QWidget()
        destination_widget.setLayout(destination_row)
        settings.addRow("Output folder", destination_widget)
        self.source_folders = QCheckBox(
            "Create a folder beside each source LIF (filename without .lif)"
        )
        self.source_folders.setToolTip(
            "For example, WT_NADPH.lif exports into a new or existing "
            "WT_NADPH folder beside it"
        )
        settings.addRow("Per-LIF folders", self.source_folders)
        return settings

    def _reset_export_rows(self) -> None:
        """Reset row ownership and grouped selection before changing
        dimension mode.
        """
        self.table.blockSignals(True)
        self.table.clearSpans()
        self.table.setRowCount(0)
        self.row_targets = []
        self.group_rows = {}
        self.group_headers = {}
        self.header_groups = {}

    def _start_source_group(self, source: Path) -> tuple[str, int]:
        """Reserve one selectable source heading while retaining source
        order.
        """
        group = os.path.normcase(str(source))
        header_row = self.table.rowCount()
        self.table.insertRow(header_row)
        self.row_targets.append(None)
        self.group_rows[group] = []
        self.group_headers[group] = header_row
        self.header_groups[header_row] = group
        return (group, header_row)

    def _update_group_selection(self, args: tuple) -> None:
        """Synchronize source headers when an individual export item
        changes.
        """
        if args and isinstance(args[0], QTableWidgetItem):
            item = args[0]
            if item.column() == 0:
                row = item.row()
                target = self.row_targets[row]
                if target is None:
                    self._toggle_group(
                        self.header_groups[row], item.checkState()
                    )
                else:
                    dataset, _plane = target
                    group = os.path.normcase(
                        str(Path(dataset.source).expanduser().resolve())
                    )
                    self._sync_group_header(group)

    def _choose_folder(self) -> None:
        """Implemented by each format's existing file-dialog
        callback.
        """
        raise NotImplementedError

    export_reflection: ExportReflectionSelection

    def _update_reflection_selection(self) -> None:
        """Check reflection coverage after normal export preflight."""
        planes = self._ptu_export_dialog_selected_planes_2()
        targets = [
            (dataset, plane)
            for dataset in self.selected_datasets()
            for plane in (
                [None]
                if self.export_format == "ics"
                and self.dimension_mode.currentData() == "integrate"
                else planes.get(dataset.key, [])
            )
        ]
        self.export_reflection.update_targets(targets)
        reflected = {
            window.dataset_key for window in self.export_reflection.windows
        }
        if self.export_format == "ics" and reflected:
            peak = max(
                (
                    dataset.width
                    * dataset.height
                    * 4
                    * (
                        time_grid(dataset, self.bins.currentData()).bins
                        + (
                            time_grid(dataset, None).bins
                            if dataset.key in reflected
                            else 0
                        )
                    )
                    for dataset in self.selected_datasets()
                ),
                default=0,
            )
            self.estimate.setText(
                re.sub(
                    r"\d+ MB peak",
                    f"{peak / 1048576:.0f} MB peak",
                    self.estimate.text(),
                )
            )
