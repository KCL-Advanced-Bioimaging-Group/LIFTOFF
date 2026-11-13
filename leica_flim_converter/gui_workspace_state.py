"""Maintained desktop component: workspace state."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6 import QtWidgets
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QWidget,
)

from .dataset import DatasetInfo
from .gui_canvas import ImageCanvas
from .gui_controls import EventFlagSelector
from .gui_models import ChannelPanel, ChannelSequence, Roi
from .gui_pair_selector import RecordedPairSelector
from .gui_plot import HistogramPlot
from .gui_workers import (
    DecodeWorker,
    IcsExportWorker,
    PtuExportWorker,
    ScanWorker,
)
from .histogram_core import HistogramCube

if TYPE_CHECKING:
    from .gui_reflection_filter import ReflectionPhotonFilter


class WorkspaceState(QMainWindow):
    """Declared workspace state and component callback contracts."""

    def __init__(self) -> None:
        super().__init__()
        self._pending_active_roi_restore = None
        self._multichannel_channel_panels = None
        self._channel_groups_by_first_key = {}
        self._decode_failure_detail = ""
        self._decode_failure_dataset_key = None
        self._channel_group = ()

    _multichannel_sequence: ChannelSequence | None
    _leica_active_roi: Roi | None
    _leica_multi_roi_restore: list[tuple[Roi, QColor]] | None
    _leica_filter_roi_restore: tuple[list[Roi], Roi | None] | None
    _confirm_channel_roi_retention: Callable[[], bool]
    _channel_valid_signature: tuple[tuple, int | None, int] | None
    _channel_valid_counts: dict[str, int]
    _closing: bool
    backend_label: QLabel
    block_list: QListWidget
    block_title: QLabel
    cancel_button: QPushButton
    pair_selector: RecordedPairSelector
    clear_button: QPushButton
    clear_roi_button: QPushButton
    combine_rois_checkbox: QAbstractButton
    cube: HistogramCube | None
    current_plane: int | None
    datasets: list[DatasetInfo]
    decode_failures: dict[str, str]
    decode_started: float
    decode_worker: DecodeWorker | None
    event_flags: EventFlagSelector
    reflection_filter: ReflectionPhotonFilter
    export_button: QPushButton
    export_worker: IcsExportWorker | PtuExportWorker | None
    fields: dict[str, QLabel]
    histogram: HistogramPlot
    image: ImageCanvas
    image_title: QLabel
    loaded_sources: list[Path]
    next_plane: QPushButton
    open_button: QPushButton
    pan_button: QtWidgets.QToolButton
    pending_scan_paths: list[Path]
    placeholder: QLabel
    plane_combo: QComboBox
    plane_controls: QWidget
    previous_plane: QPushButton
    progress: QProgressBar
    ptu_export_button: QPushButton
    scan_worker: ScanWorker | None
    selected: DatasetInfo | None
    status_label: QLabel
    thread_spin: QSpinBox
    timer: QTimer
    workspace: QWidget
    zoom_in_button: QtWidgets.QToolButton
    zoom_out_button: QtWidgets.QToolButton

    def _groups_for_window_2(self) -> list[list[DatasetInfo]]:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def current_channel_group(self) -> tuple[DatasetInfo, ...]:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _active_roi_indices_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _update_roi_controls_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _apply_group_details_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _capture_active_roi_snapshot_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_select_block_4(self, item: QListWidgetItem) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_select_block_3(self, item) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def change_recorded_pairs(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _ask_retain_channel_rois_2(self) -> bool:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _rebuild_grouped_block_list_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def clear_pair_preview(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _selected_channel_mode_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _clear_transient_image_rois_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__show_dataset_2(self, dataset: DatasetInfo) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def start_selected_preview(self, linear_plane: int | None) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def start_channel_preview(self, linear_plane) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _set_decode_failure_details_2(self, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _restore_active_roi_snapshot_2(self, snapshot) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _refresh_all_channel_rois_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _render_all_channels_2(self, panels) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _capture_channel_panel_2(
        self, dataset: DatasetInfo, cube: HistogramCube
    ) -> ChannelPanel:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def accept_preview_result(self, cube, error: str) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def restore_filter_regions(self, cube, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _bin_summary_2(self, photon_count) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _combined_roi_values_2(self, indices) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__refresh_roi_histogram_3(self, *_args) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def restore_active_regions(self, cube, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _all_pixel_values_2(self, layout) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _combined_values_2(self, active, layout) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _cube_layout_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _summary_2(self, values) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__refresh_roi_histogram_5(self, *_args) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def refresh_completed_preview(self, cube, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def complete_channel_preview(self, cube, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def complete_preview(self, cube, error) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__event_flags_changed_7(self, mask) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__event_flags_changed_6(self, mask) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__event_flags_changed_5(self, mask) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__plane_changed_7(self, index: int) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__plane_changed_6(self, index) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__plane_changed_5(self, index) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_clear_roi_9(self) -> None:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_clear_roi_8(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_clear_roi_7(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window_clear_roi_6(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _integerize_single_channel_rois_2(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _main_window__refresh_roi_histogram_7(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def show_roi(self, _x0, _y0, _x1, _y1) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def clear_roi(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _refresh_roi_histogram(self) -> object:
        """Implemented by the owning workspace component."""
        raise NotImplementedError()

    def _show_dataset(self, dataset: DatasetInfo) -> None:
        """Display metadata through the workspace channel component."""
        raise NotImplementedError

    def _start_decode(self, linear_plane: int | None) -> None:
        """Start a preview through the workspace worker component."""
        raise NotImplementedError

    @staticmethod
    def _source_identity(path: Path) -> str:
        """Normalize an imported source through its lifecycle owner."""
        raise NotImplementedError

    def _busy(self, value: bool) -> None:
        """Apply the shared worker-state controls."""
        raise NotImplementedError

    def _decode_status(self, message: str) -> None:
        """Present a decode progress callback."""
        raise NotImplementedError

    def _decode_complete(self, cube: HistogramCube | None, error: str) -> None:
        """Accept the worker result through the preview component."""
        raise NotImplementedError

    def _active_snapshot_2(self) -> list[tuple[Roi, QColor]]:
        """Capture currently activated ROI identities."""
        raise NotImplementedError

    def _bin_width_ps(self) -> float:
        """Return calibrated preview bin width in picoseconds."""
        raise NotImplementedError

    def _hide_redundant_details_2(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _set_interaction_tool_2(self, tool, checked) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _set_empty(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def open_files(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def select_block(self, item) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _event_flags_changed(self, *args, **kwargs) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _plane_changed(self, *args, **kwargs) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _step_plane(self, direction: int) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def show_pixel(self, x, y) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def export_ics(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def export_ptu(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def cancel_active(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def clear_data(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()

    def _update_elapsed(self) -> None:
        """Dispatch through the concrete Qt workspace component."""
        raise NotImplementedError()
