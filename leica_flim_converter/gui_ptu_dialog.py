"""PTU dataset, plane, and output selection controls."""

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
    QSpinBox,
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
from .ptu_export import PtuExportOptions, proposed_ptu_filenames
from .reflection_export import ReflectionWindow
from .timing import timing_quality


class PtuExportDialog(ExportTableMixin):
    """Select datasets and planes for photon-record export."""

    export_format = "ptu"

    def _ptu_export_dialog___init_9(
        self,
        datasets: list[DatasetInfo],
        states: dict[str, str],
        parent=None,
        event_flag_mask=PRIMARY_EVENT_FLAGS,
        reflection_windows: tuple[ReflectionWindow, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export PicoQuant PTU event files")
        self.resize(1100, 620)
        self.event_flags = EventFlagSelector(event_flag_mask, self)
        self.export_reflection = ExportReflectionSelection(reflection_windows)
        self.active_event_flag_mask = event_flag_mask
        self.datasets = datasets
        self.states = states
        self.names = proposed_ptu_filenames(datasets)
        self.row_targets = []
        self.group_rows = {}
        self.group_headers = {}
        self.header_groups = {}
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 12)
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
                "Timing quality",
                "Output filename",
            ]
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Stretch)
        self._populate_table()
        settings = self._build_export_selection(layout)
        self.timing_mode = QComboBox()
        self.timing_mode.addItem("Recorded scan timing when complete", "auto")
        self.timing_mode.addItem("Synthetic raster", "synthetic")
        self.timing_mode.addItem(
            "Require reconstructed timing", "reconstructed"
        )
        settings.addRow("Scan timeline", self.timing_mode)
        self.pixel_ticks = QSpinBox()
        self.pixel_ticks.setRange(1, 1024)
        self.pixel_ticks.setValue(3)
        self.pixel_ticks.setToolTip(
            "Synthetic laser sync periods assigned to each pixel"
        )
        self.collision = QComboBox()
        self.collision.addItem("Add numeric suffix", "suffix")
        self.collision.addItem("Skip existing file", "skip")
        settings.addRow("Synthetic sync periods per pixel", self.pixel_ticks)
        settings.addRow("Existing files", self.collision)
        layout.addLayout(settings)
        add_export_filter_rows(
            layout, self.event_flags, self.export_reflection
        )
        add_export_metadata_note(
            layout,
            "Photon positions and microtimes are decoded from "
            "Leica data. Complete recorded scan periods allow "
            "a nominal reconstructed "
            "timeline; otherwise a labelled synthetic raster is used. "
            "Neither restores the original individual photon timestamps. ",
        )
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
            "Export PTU"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            False
        )
        connect_signal(
            self.timing_mode.currentIndexChanged, self._timing_changed
        )
        connect_signal(self.buttons.accepted, self.accept)
        connect_signal(self.buttons.rejected, self.reject)
        connect_signal(self.destination.textChanged, self._selection_changed)
        connect_signal(
            self.source_folders.toggled, self._destination_mode_changed
        )
        layout.addWidget(self.buttons)
        connect_signal(self.table.itemChanged, self._selection_changed)

    def _ptu_export_dialog___init_8(self, *args, **kwargs):
        self._ptu_export_dialog___init_9(*args, **kwargs)
        self._rename_export_channel_column_2()

    def _ptu_export_dialog___init_7(self, *args, **kwargs):
        self._compact_axis_modes = {}
        self._compact_row_planes = {}
        self._compact_original_group_rows = {}
        self._ptu_export_dialog___init_8(*args, **kwargs)
        self._apply_with_row_details_2()
        self._selection_changed()

    def _ptu_export_dialog___init_6(self, *args, **kwargs):
        self._ptu_export_dialog___init_7(*args, **kwargs)
        self.table.setColumnHidden(2, True)

    def _ptu_export_dialog__populate_table_3(self) -> None:
        self._reset_export_rows()
        for source, source_datasets in _source_groups_3(self.datasets):
            group, header_row = self._start_source_group(source)
            enabled = any(
                dataset.decoded_rows > 0
                and dataset.repetition_storage_model != "unresolved"
                for dataset in source_datasets
            )
            self._add_source_heading(header_row, source, enabled)
            for dataset in source_datasets:
                for plane in range(dataset.plane_count):
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self.row_targets.append((dataset, plane))
                    self.group_rows[group].append(row)
                    check = QTableWidgetItem()
                    item_enabled = (
                        dataset.decoded_rows > 0
                        and dataset.repetition_storage_model != "unresolved"
                    )
                    check.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsUserCheckable
                        if item_enabled
                        else Qt.ItemFlag.NoItemFlags
                    )
                    check.setCheckState(Qt.CheckState.Unchecked)
                    t_index, z_index = dataset.plane_indices(plane)
                    base = Path(self.names[dataset.key]).stem
                    suffix = (
                        f"_{dataset.plane_label(plane)}"
                        if dataset.plane_count > 1
                        else ""
                    )
                    values = (
                        dataset.acquisition_name or dataset.source.stem,
                        dataset.series_name or "-",
                        dataset.export_channel_label,
                        dataset.detector_name or "-",
                        dataset.memory_id,
                        f"{dataset.width} x {dataset.height}",
                        (
                            "T="
                            f"{t_index + 1}"
                            "/"
                            f"{dataset.t_count}"
                            ", Z="
                            f"{z_index + 1}"
                            "/"
                            f"{dataset.z_count}"
                        ),
                        f"{dataset.compressed_bytes / 1048576:.1f} MB",
                        self.states.get(dataset.key, "not decoded"),
                        f"{base}{suffix}.ptu",
                    )
                    values = (
                        *values[:-1],
                        timing_quality(dataset, "synthetic"),
                        values[-1],
                    )
                    self.table.setItem(row, 0, check)
                    for column, value in enumerate(values, 1):
                        item = QTableWidgetItem(value)
                        item.setToolTip(value)
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                        self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _ptu_export_dialog__selection_changed_3(self, *_args) -> None:
        self._update_group_selection(_args)
        selected_rows = sum(
            (
                target is not None
                and required_table_item(self.table, row, 0).checkState()
                == Qt.CheckState.Checked
                for row, target in enumerate(self.row_targets)
            )
        )
        selected = self.selected_datasets()
        photons = sum(dataset.total_photons or 0 for dataset in selected)
        self.estimate.setText(
            (
                f"{len(selected)}"
                " detector dataset(s) | "
                f"{selected_rows}"
                " PTU file(s) | approximately "
                f"{photons:,}"
                " source photons"
            )
            if selected
            else "No blocks selected"
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            bool(
                selected
                and (
                    self.source_folders.isChecked()
                    or self.destination.text().strip()
                )
            )
        )

    def _ptu_export_dialog__flags_changed_3(self, mask):
        self.active_event_flag_mask = mask
        self._selection_changed()

    _compact_axis_modes: dict[str, dict[str, bool]]
    _compact_original_group_rows: dict[str, list[int]]
    _compact_row_planes: dict[int, list[int]]
    active_event_flag_mask: int
    buttons: QDialogButtonBox
    collision: QComboBox
    datasets: list[DatasetInfo]
    destination: QLineEdit
    destination_browse: QPushButton
    estimate: QLabel
    event_flags: EventFlagSelector
    group_headers: dict[str, int]
    group_rows: dict[str, list[int]]
    header_groups: dict[int, str]
    names: dict[str, str]
    pixel_ticks: QSpinBox
    timing_mode: QComboBox
    row_targets: list[tuple[DatasetInfo, int | None] | None]
    source_folders: QCheckBox
    states: dict[str, str]
    table: QTableWidget

    def __init__(self, *args, **kwargs):
        self._ptu_export_dialog___init_6(*args, **kwargs)
        self._esp_apply_status_2()

    def _populate_table(self):
        self._ptu_export_dialog__populate_table_3()
        self._compact_original_group_rows = {
            group: list(rows) for group, rows in self.group_rows.items()
        }
        self._apply_with_row_details_2()

    def _choose_folder(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self, "Choose PTU output folder", self.destination.text()
        )
        if value:
            self.destination.setText(value)

    def selected_planes(self):
        """Return every plane represented by the checked compact
        rows.
        """
        return self._ptu_export_dialog_selected_planes_2()

    def options(self) -> PtuExportOptions:
        """Compute options."""
        return PtuExportOptions(
            pixel_ticks=self.pixel_ticks.value(),
            timing_mode=self.timing_mode.currentData(),
            collision=self.collision.currentData(),
            event_flag_mask=self.event_flags.mask(),
            reflection_windows=self.export_reflection.windows,
        )

    def _selection_changed(self, *args):
        self._ptu_export_dialog__selection_changed_3(*args)
        self._correct_estimate_2()
        self._update_reflection_selection()

    def _flags_changed(self, mask):
        selected = self._selected_plane_sets_2()
        self._ptu_export_dialog__flags_changed_3(mask)
        self._apply_with_row_details_2(selected)

    def _timing_changed(self, *_args):
        self.pixel_ticks.setEnabled(
            self.timing_mode.currentData() != "reconstructed"
        )
        self._esp_apply_status_2()
