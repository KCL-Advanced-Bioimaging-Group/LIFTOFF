"""ICS dataset, plane, and output selection controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .dataset import DatasetInfo
from .event_flags import PRIMARY_EVENT_FLAGS
from .gui_controls import EventFlagSelector
from .gui_export_reflection import (
    ExportReflectionSelection,
    add_export_filter_rows,
)
from .gui_export_table import ExportTableMixin, add_export_metadata_note
from .gui_helpers import _source_groups_3
from .gui_models import connect_signal, required_table_item
from .ics import ALLOWED_BINS, proposed_ics_filenames
from .ics_export import IcsExportOptions
from .reflection_export import ReflectionWindow
from .timing import time_grid, timing_quality


class IcsExportDialog(ExportTableMixin):
    """Select datasets, planes and calibrated ICS export options."""

    export_format = "ics"

    def _ics_export_dialog___init_9(
        self,
        datasets: list[DatasetInfo],
        states: dict[str, str],
        parent=None,
        event_flag_mask=PRIMARY_EVENT_FLAGS,
        reflection_windows: tuple[ReflectionWindow, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export ICS decay stacks")
        self.resize(1120, 620)
        self.event_flags = EventFlagSelector(event_flag_mask, self)
        self.export_reflection = ExportReflectionSelection(reflection_windows)
        self.active_event_flag_mask = event_flag_mask
        self.datasets = datasets
        self.states = states
        self.names = proposed_ics_filenames(datasets)
        self.row_targets = []
        self.group_rows = {}
        self.group_headers = {}
        self.header_groups = {}
        self.dimension_mode = QComboBox()
        self.dimension_mode.addItem("Split detector/tile/T/Z planes", "split")
        self.dimension_mode.addItem("Integrate T/Z per detector", "integrate")
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels(
            [
                "",
                "Acquisition",
                "Series",
                "Channel",
                "Detector",
                "Memory block",
                "Dimensions",
                "T / Z",
                "Payload",
                "State",
                "Files",
                "Timing quality",
                "Output filename",
            ]
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(12, QHeaderView.ResizeMode.Stretch)
        self._populate_table("split")
        settings = self._build_export_selection(layout)
        self.bins = QComboBox()
        self.bins.addItem("Native timing", None)
        for value in ALLOWED_BINS:
            self.bins.addItem(str(value), value)
        self.bins.setCurrentText("128")
        self.bins.setToolTip(
            "Native timing preserves the recorded arrival increment. "
            "Numeric choices rebin one laser period; "
            "finer bins add no timing information. "
            "Photons outside the selected window are excluded "
            "and counted in the sidecar."
        )
        self.compression = QComboBox()
        self.compression.addItem("Gzip", "gzip")
        self.compression.addItem("Uncompressed", "uncompressed")
        self.collision = QComboBox()
        self.collision.addItem("Add numeric suffix", "suffix")
        self.collision.addItem("Skip existing file", "skip")
        settings.addRow("Dimensions", self.dimension_mode)
        settings.addRow("Time bins", self.bins)
        settings.addRow("Compression", self.compression)
        settings.addRow("Existing files", self.collision)
        layout.addLayout(settings)
        add_export_filter_rows(
            layout, self.event_flags, self.export_reflection
        )
        add_export_metadata_note(layout)
        connect_signal(
            self.export_reflection.checkbox.toggled, self._selection_changed
        )
        self.event_flags.set_applicable(True)
        self.active_event_flag_mask = self.event_flags.mask()
        connect_signal(self.event_flags.changed, self._flags_changed)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Export"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            False
        )
        connect_signal(self.buttons.accepted, self.accept)
        connect_signal(self.buttons.rejected, self.reject)
        connect_signal(self.destination.textChanged, self._selection_changed)
        connect_signal(
            self.source_folders.toggled, self._destination_mode_changed
        )
        connect_signal(self.bins.currentTextChanged, self._selection_changed)
        connect_signal(
            self.dimension_mode.currentIndexChanged,
            self._dimension_mode_changed,
        )
        layout.addWidget(self.buttons)
        connect_signal(self.table.itemChanged, self._selection_changed)

    def _ics_export_dialog___init_8(self, *args, **kwargs):
        self._ics_export_dialog___init_9(*args, **kwargs)
        self._rename_export_channel_column_2()

    def _ics_export_dialog___init_7(self, *args, **kwargs):
        self._compact_axis_modes = {}
        self._compact_row_planes = {}
        self._compact_original_group_rows = {}
        self._ics_export_dialog___init_8(*args, **kwargs)
        self._apply_with_row_details_2()
        self._selection_changed()

    def _ics_export_dialog___init_6(self, *args, **kwargs):
        self._ics_export_dialog___init_7(*args, **kwargs)
        self.table.setColumnHidden(2, True)

    def _ics_export_dialog__populate_table_3(self, mode: str) -> None:
        self._reset_export_rows()
        for source, source_datasets in _source_groups_3(self.datasets):
            group, header_row = self._start_source_group(source)
            enabled = any(
                dataset.decoded_rows > 0 for dataset in source_datasets
            )
            self._add_source_heading(header_row, source, enabled)
            for dataset in source_datasets:
                targets: list[int | None] = (
                    [None]
                    if mode == "integrate"
                    else list(range(dataset.plane_count))
                )
                for linear_plane in targets:
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self.row_targets.append((dataset, linear_plane))
                    self.group_rows[group].append(row)
                    check = QTableWidgetItem()
                    check.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsUserCheckable
                        if dataset.decoded_rows > 0
                        else Qt.ItemFlag.NoItemFlags
                    )
                    check.setCheckState(Qt.CheckState.Unchecked)
                    t_index = z_index = 0
                    if linear_plane is not None:
                        t_index, z_index = dataset.plane_indices(linear_plane)
                    plane_text = (
                        (
                            "T="
                            f"{t_index + 1}"
                            "/"
                            f"{dataset.t_count}"
                            ", Z="
                            f"{z_index + 1}"
                            "/"
                            f"{dataset.z_count}"
                        )
                        if linear_plane is not None
                        else (
                            f"T=all {dataset.t_count}, Z=all {dataset.z_count}"
                        )
                    )
                    values = (
                        dataset.acquisition_name or dataset.source.stem,
                        dataset.series_name or "-",
                        dataset.export_channel_label,
                        dataset.detector_name or "-",
                        dataset.memory_id,
                        f"{dataset.width} x {dataset.height}",
                        plane_text,
                        f"{dataset.compressed_bytes / 1048576:.1f} MB",
                        self.states.get(dataset.key, "not decoded"),
                        "1",
                        self._output_pattern(dataset, mode, linear_plane),
                    )
                    values = (
                        *values[:-1],
                        timing_quality(dataset, "ics"),
                        values[-1],
                    )
                    self.table.setItem(row, 0, check)
                    for column, value in enumerate(values, 1):
                        item = QTableWidgetItem(value)
                        item.setToolTip(value)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                        self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _ics_export_dialog__selection_changed_3(self, *_args) -> None:
        self._update_group_selection(_args)
        selected = self.selected_datasets()
        bins = self.bins.currentData()
        selected_targets = [
            target
            for row, target in enumerate(self.row_targets)
            if target is not None
            and required_table_item(self.table, row, 0).checkState()
            == Qt.CheckState.Checked
        ]
        size = sum(
            (
                dataset.width
                * dataset.height
                * time_grid(dataset, bins).bins
                * 2
                for dataset, _plane in selected_targets
            )
        )
        files = len(selected_targets)
        peak = max(
            (
                dataset.width
                * dataset.height
                * time_grid(dataset, bins).bins
                * 4
                for dataset in selected
            ),
            default=0,
        )
        self.estimate.setText(
            (
                f"{len(selected)}"
                " detector dataset(s) | "
                f"{files}"
                " file(s) | "
                f"{size / 1073741824:.2f}"
                " GB total | "
                f"{peak / 1048576:.0f}"
                " MB peak"
            )
            if selected
            else "No blocks selected"
        )
        valid = bool(
            selected
            and (
                self.source_folders.isChecked()
                or self.destination.text().strip()
            )
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            valid
        )

    def _ics_export_dialog__flags_changed_3(self, mask):
        self.active_event_flag_mask = mask
        self._selection_changed()

    _compact_axis_modes: dict[str, dict[str, bool]]
    _compact_original_group_rows: dict[str, list[int]]
    _compact_row_planes: dict[int, list[int]]
    active_event_flag_mask: int
    bins: QComboBox
    buttons: QDialogButtonBox
    collision: QComboBox
    compression: QComboBox
    datasets: list[DatasetInfo]
    destination: QLineEdit
    destination_browse: QPushButton
    dimension_mode: QComboBox
    estimate: QLabel
    event_flags: EventFlagSelector
    group_headers: dict[str, int]
    group_rows: dict[str, list[int]]
    header_groups: dict[int, str]
    names: dict[str, str]
    row_targets: list[tuple[DatasetInfo, int | None] | None]
    source_folders: QCheckBox
    states: dict[str, str]
    table: QTableWidget

    def __init__(self, *args, **kwargs):
        self._ics_export_dialog___init_6(*args, **kwargs)
        self._esp_apply_status_2()

    def _output_pattern(
        self, dataset: DatasetInfo, mode: str, linear_plane: int | None = None
    ) -> str:
        base = Path(self.names[dataset.key]).stem
        if dataset.plane_count == 1:
            return base + ".ics"
        if mode == "integrate":
            suffix = (
                "all-frames-summed"
                if dataset.t_count > 1 and dataset.z_count == 1
                else "all-z-summed"
                if dataset.z_count > 1 and dataset.t_count == 1
                else "all-planes-summed"
            )
            return f"{base}_{suffix}.ics"
        return f"{base}_{dataset.plane_label(linear_plane or 0)}.ics"

    def _populate_table(self, mode):
        self._ics_export_dialog__populate_table_3(mode)
        self._compact_original_group_rows = {
            group: list(rows) for group, rows in self.group_rows.items()
        }
        self._apply_with_row_details_2()

    def _dimension_mode_changed(self) -> None:
        mode = self.dimension_mode.currentData()
        self._populate_table(mode)
        self._esp_apply_status_2()

    def _choose_folder(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self, "Choose ICS output folder", self.destination.text()
        )
        if value:
            self.destination.setText(value)

    def selected_plane_selection(self):
        """Compute selected plane selection."""
        if self.dimension_mode.currentData() != "split":
            return {}
        return self._ptu_export_dialog_selected_planes_2()

    def options(self, threads: int) -> IcsExportOptions:
        """Compute options."""
        return IcsExportOptions(
            bins=self.bins.currentData(),
            compression=self.compression.currentData(),
            collision=self.collision.currentData(),
            threads=threads,
            dimension_mode=self.dimension_mode.currentData(),
            event_flag_mask=self.event_flags.mask(),
            reflection_windows=self.export_reflection.windows,
        )

    def _selection_changed(self, *args):
        for dataset in self.datasets:
            self._set_timing_quality(
                dataset.key, self._timing_state(dataset)[2]
            )
        self._ics_export_dialog__selection_changed_3(*args)
        self._correct_estimate_2()
        self._update_reflection_selection()

    def _flags_changed(self, mask):
        selected = self._selected_plane_sets_2()
        self._ics_export_dialog__flags_changed_3(mask)
        self._apply_with_row_details_2(selected)
