"""Workspace control and layout construction."""

from __future__ import annotations

import os
from abc import abstractmethod
from html import escape
from pathlib import Path

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPaintEvent, QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

from .gui_canvas import ImageCanvas
from .gui_controls import EventFlagSelector
from .gui_dataset_list import DatasetItemDelegate
from .gui_helpers import _draw_hand_icon_2, _draw_magnifier_icon_2
from .gui_models import connect_signal, widget_box_layout
from .gui_pair_selector import RecordedPairSelector
from .gui_plot import HistogramPlot
from .gui_reflection_filter import ReflectionPhotonFilter
from .gui_window_fit import ScreenFit
from .gui_workspace_state import WorkspaceState
from .platform_paths import branding_directory
from .version import (
    APPLICATION_FULL_NAME,
    APPLICATION_NAME,
    APPLICATION_VERSION,
)


def _application_wordmark() -> QLabel:
    """Build the accessible workspace header at 48 logical pixels."""
    label = QLabel()
    label.setObjectName("applicationWordmark")
    label.setAccessibleName(APPLICATION_NAME)
    label.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    pixmap = QPixmap(str(branding_directory() / "liftoff-wordmark.png"))
    pixmap = pixmap.scaledToHeight(
        96, Qt.TransformationMode.SmoothTransformation
    )
    pixmap.setDevicePixelRatio(2)
    label.setPixmap(pixmap)
    return label


def _image_view_row(image: ImageCanvas) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(image, 1)
    layout.addWidget(image.contrast)
    image.contrast.show()
    return layout


def _wrapping_row(owner: QWidget) -> QFormLayout:
    """Stack control groups when their labels cannot fit in one row."""
    layout = QFormLayout(owner)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    layout.setFieldGrowthPolicy(
        QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    )
    return layout


class _StatusLabel(QLabel):
    """Show shortened status text with the full message on hover."""

    def setText(self, text: str) -> None:  # noqa: N802
        """Keep the original text available even when it is elided."""
        super().setText(text)
        self.setToolTip(f"<qt>{escape(text)}</qt>")

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        """Fit one line of text inside the assigned status area."""
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, rect.width()
        )
        painter = QStylePainter(self)
        painter.drawItemText(
            rect,
            self.alignment(),
            self.palette(),
            self.isEnabled(),
            text,
            QPalette.ColorRole.WindowText,
        )
        painter.end()


# Qt window ownership and existing callbacks require named widget
# fields.
# pylint: disable-next=too-many-instance-attributes
class WorkspaceLayout(WorkspaceState):
    """Initialize the Qt workspace and its owned layout controls."""

    def initialize_workspace(self) -> None:
        """Initialize workspace."""
        self._plane_selector_sync_value = None
        self._decode_failure_detail = ""
        self._decode_failure_dataset_key = None
        self.setWindowTitle(f"{APPLICATION_FULL_NAME} {APPLICATION_VERSION}")
        self.setWindowIcon(
            QtGui.QIcon(str(branding_directory() / "liftoff-icon.png"))
        )
        self.resize(1500, 900)
        self.datasets = []
        self.cube = None
        self.loaded_sources = []
        self.pending_scan_paths = []
        self.selected = None
        self.scan_worker = None
        self.decode_worker = None
        self.export_worker = None
        self.decode_failures = {}
        self.current_plane = None
        self._closing = False
        self.decode_started = 0.0
        self._build()
        self._set_empty()
        self.setAcceptDrops(True)
        for editor in self.thread_spin.findChildren(QLineEdit):
            editor.setAcceptDrops(False)
        self.open_button.setToolTip(
            "Open LIF files, or drag and drop them into the window"
        )
        ScreenFit(self)

    def build_image_navigation(self, *args, **kwargs):
        """Build image navigation."""
        self.initialize_workspace(*args, **kwargs)
        self.combine_rois_checkbox = QCheckBox("Combine all ROIs")
        self.combine_rois_checkbox.setToolTip(
            "Pool activated ROIs; overlapping pixels are counted once"
        )
        summary_layout = widget_box_layout(self.clear_roi_button)
        summary_layout.insertWidget(
            summary_layout.indexOf(self.clear_roi_button),
            self.combine_rois_checkbox,
        )
        connect_signal(
            self.combine_rois_checkbox.toggled, self._refresh_roi_histogram
        )
        toolbar = QFrame(self.image)
        toolbar.setObjectName("imageNavigationToolbar")
        toolbar.setStyleSheet(
            "QFrame#imageNavigationToolbar { background: "
            "rgba(250,250,250,220); border: 1px solid #9aa6b2; "
            "border-radius: 5px; }QToolButton { border: 0; "
            "padding: 3px; border-radius: 3px; }QToolButton:hover "
            "{ background: #dcebf7; }QToolButton:checked { "
            "background: #9ed0f2; border: 1px solid #2d83bd; }"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(3, 3, 3, 3)
        toolbar_layout.setSpacing(2)
        self.zoom_in_button = QtWidgets.QToolButton(toolbar)
        self.zoom_in_button.setObjectName("zoomInTool")
        self.zoom_in_button.setIcon(QtGui.QIcon(_draw_magnifier_icon_2("+")))
        self.zoom_in_button.setToolTip(
            "Zoom in tool (click again to return to ROI drawing)"
        )
        self.zoom_out_button = QtWidgets.QToolButton(toolbar)
        self.zoom_out_button.setObjectName("zoomOutTool")
        self.zoom_out_button.setIcon(QtGui.QIcon(_draw_magnifier_icon_2("-")))
        self.zoom_out_button.setToolTip(
            "Zoom out tool (click again to return to ROI drawing)"
        )
        self.pan_button = QtWidgets.QToolButton(toolbar)
        self.pan_button.setObjectName("panTool")
        self.pan_button.setIcon(QtGui.QIcon(_draw_hand_icon_2()))
        self.pan_button.setToolTip("Pan tool (Shift+drag also pans)")
        for button in (
            self.zoom_in_button,
            self.zoom_out_button,
            self.pan_button,
        ):
            button.setCheckable(True)
            button.setFixedSize(30, 30)
            toolbar_layout.addWidget(button)
        connect_signal(
            self.zoom_in_button.toggled,
            lambda checked: self._set_interaction_tool_2("zoom_in", checked),
        )
        connect_signal(
            self.zoom_out_button.toggled,
            lambda checked: self._set_interaction_tool_2("zoom_out", checked),
        )
        connect_signal(
            self.pan_button.toggled,
            lambda checked: self._set_interaction_tool_2("pan", checked),
        )
        self.image.navigation_toolbar = toolbar
        self.image.zoom_in_cursor = QtGui.QCursor(
            _draw_magnifier_icon_2("+", True), 8, 8
        )
        self.image.zoom_out_cursor = QtGui.QCursor(
            _draw_magnifier_icon_2("-", True), 8, 8
        )
        self.image.position_navigation_toolbar(None)

    def build_channel_controls(self, *args, **kwargs):
        """Build channel controls."""
        self.build_image_navigation(*args, **kwargs)
        self._channel_group = ()
        self._channel_groups_by_first_key = {}
        self._multichannel_sequence = None
        self._multichannel_channel_panels = None
        self._channel_valid_counts = {}
        self._channel_valid_signature = None
        self._pending_active_roi_restore = None
        self._confirm_channel_roi_retention = self._ask_retain_channel_rois_2
        self.histogram.channel_owner = self
        self.reflection_filter.bind(
            self, lambda: self._multichannel_channel_panels or []
        )
        self.image.multichannel_mirror_layout = []
        self.image.last_mirrored_roi_layout = []
        self.image.multichannel_combined_rois = False
        self.image_title.hide()
        self._hide_redundant_details_2()
        previous_combine_control = self.combine_rois_checkbox
        previous_combine_control.blockSignals(True)
        previous_combine_control.hide()
        previous_combine_control.setParent(None)
        self.combine_rois_checkbox = QPushButton(
            "Combine all ROIs", self.histogram
        )
        self.combine_rois_checkbox.setObjectName("combineRoisButton")
        self.combine_rois_checkbox.setCheckable(True)
        self.combine_rois_checkbox.setChecked(False)
        self.combine_rois_checkbox.setToolTip(
            "Pool activated ROIs; overlapping pixels are counted once"
        )
        self.combine_rois_checkbox.setFont(self.clear_roi_button.font())
        self.combine_rois_checkbox.setStyleSheet(
            self.clear_roi_button.styleSheet()
        )
        connect_signal(
            self.combine_rois_checkbox.toggled, self._refresh_roi_histogram
        )
        self.histogram.combine_rois_button = self.combine_rois_checkbox
        for button in (
            self.histogram.separate_tiles_button,
            self.histogram.log_scale_button,
            self.histogram.reflection.detect_button,
            self.histogram.reflection.manual_button,
            self.histogram.reflection.clear_button,
        ):
            button.setFont(self.combine_rois_checkbox.font())
            button.setStyleSheet(self.combine_rois_checkbox.styleSheet())
        self.clear_roi_button.setText("Clear all ROIs")
        self.histogram.position_combine_rois_button()
        self._update_roi_controls_2()
        parent = self.plane_controls.parentWidget()
        self.pair_selector = RecordedPairSelector(parent)
        parent_layout = widget_box_layout(self.plane_controls)
        parent_layout.insertWidget(
            parent_layout.indexOf(self.plane_controls), self.pair_selector
        )
        self.pair_selector.hide()
        connect_signal(
            self.pair_selector.selection_changed, self.change_recorded_pairs
        )

    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(12, 10, 12, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_column = QWidget()
        left_column_layout = QVBoxLayout(left_column)
        left_column_layout.setContentsMargins(0, 0, 0, 0)
        title = _application_wordmark()
        left_column_layout.addWidget(title)
        left_column_layout.addWidget(self._build_data_panel(), 1)
        splitter.addWidget(left_column)

        details_button = QPushButton("Details")
        details_button.setObjectName("datasetDetailsToggle")
        details_button.setAccessibleName("Dataset details")
        details_button.setCheckable(True)
        details_button.setChecked(True)
        details_button.setToolTip("Show or hide dataset details and controls")
        toolbar = self._build_toolbar(details_button)
        title.setMinimumHeight(toolbar.sizeHint().height())
        right_column = QWidget()
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.addWidget(toolbar)
        right = QFrame()
        right.setFrameShape(QFrame.Shape.StyledPanel)
        right_column_layout.addWidget(right, 1)
        right_layout = QVBoxLayout(right)
        self.placeholder = QLabel(
            "Drop LIF files here or click Open LIF files\nThen "
            "select a compressed data block to decode its pixel "
            "histograms"
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("color:#6b7280;font-size:15px")
        right_layout.addWidget(self.placeholder, 1)
        self.workspace = self._build_preview(details_button)
        right_layout.addWidget(self.workspace, 1)
        splitter.addWidget(right_column)
        splitter.setSizes([340, 1120])
        outer.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self._build_status_bar()
        self.timer = QTimer(self)
        connect_signal(self.timer.timeout, self._update_elapsed)
        connect_signal(self.image.hovered, self.show_pixel)
        connect_signal(self.image.hover_ended, self._refresh_roi_histogram)
        connect_signal(self.image.roi_selected, self.show_roi)

    def _build_preview(self, details_button: QPushButton) -> QScrollArea:
        """Put a resizable image and plot in a scrollable preview."""
        preview = QSplitter(Qt.Orientation.Vertical)
        preview.setChildrenCollapsible(False)
        top_split = QSplitter(Qt.Orientation.Horizontal)
        top_split.setChildrenCollapsible(False)
        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_title = QLabel("Summed photon image")
        image_layout.addWidget(self.image_title)
        self.image = ImageCanvas()
        self.image.setMinimumWidth(328)
        self.image.setMinimumHeight(240)
        image_layout.addLayout(_image_view_row(self.image), 1)
        top_split.addWidget(image_panel)
        summary_scroll = QScrollArea()
        summary_scroll.setObjectName("datasetDetailsScroll")
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        summary_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        summary_scroll.setMinimumWidth(270)
        summary_scroll.setWidget(self._build_summary_panel())
        top_split.addWidget(summary_scroll)
        top_split.setSizes([650, 410])
        connect_signal(details_button.toggled, summary_scroll.setVisible)
        preview.addWidget(top_split)
        self.histogram = HistogramPlot()
        preview.addWidget(self.histogram)
        preview.setSizes([450, 300])
        scroll = QScrollArea()
        scroll.setObjectName("previewScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(preview)
        return scroll

    def _build_status_bar(self) -> None:
        """Keep status and cancellation controls below the preview."""
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_label = _StatusLabel("Ready")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        status.addWidget(self.status_label, 1)
        self.backend_label = QLabel("Decoder: not loaded")
        status.addPermanentWidget(self.backend_label)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setRange(0, 100)
        status.addPermanentWidget(self.progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        connect_signal(self.cancel_button.clicked, self.cancel_active)
        status.addPermanentWidget(self.cancel_button)

    @abstractmethod
    def _components_ready(self) -> bool:
        """Require a concrete workspace with all application
        components.
        """
        raise NotImplementedError

    def _build_data_panel(self) -> QFrame:
        """Construct the source list and its file controls."""
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel_layout = QVBoxLayout(panel)
        header = QWidget(panel)
        header.setObjectName("dataListHeader")
        header_layout = _wrapping_row(header)
        heading = QLabel("Compressed data blocks")
        heading.setWordWrap(True)
        self.open_button = QPushButton("Open LIF files")
        connect_signal(self.open_button.clicked, self.open_files)
        self.clear_button = QPushButton("Clear all data")
        self.clear_button.setObjectName("clearAllDataButton")
        self.clear_button.setToolTip("Clear all loaded LIF files")
        connect_signal(self.clear_button.clicked, self.clear_data)
        file_controls = QWidget()
        _wrapping_row(file_controls).addRow(
            self.open_button, self.clear_button
        )
        header_layout.addRow(heading, file_controls)
        panel_layout.addWidget(header)
        self.block_list = QListWidget()
        self.block_list.setWordWrap(True)
        self.block_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.block_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.block_list.setItemDelegate(DatasetItemDelegate(self.block_list))
        self.block_list.setIconSize(QPixmap(88, 88).size())
        connect_signal(self.block_list.itemClicked, self.select_block)
        panel_layout.addWidget(self.block_list)
        return panel

    def _build_toolbar(self, details_button: QPushButton) -> QWidget:
        """Construct the viewer toolbar and group attribution."""
        toolbar = QWidget()
        toolbar_layout = _wrapping_row(toolbar)
        export_controls = QWidget()
        export_layout = QHBoxLayout(export_controls)
        export_layout.setContentsMargins(0, 0, 0, 0)
        export_layout.setSpacing(4)
        self.ptu_export_button = QPushButton("Export PTU")
        self.ptu_export_button.setEnabled(False)
        connect_signal(self.ptu_export_button.clicked, self.export_ptu)
        export_layout.addWidget(self.ptu_export_button)
        self.export_button = QPushButton("Export ICS")
        self.export_button.setEnabled(False)
        connect_signal(self.export_button.clicked, self.export_ics)
        export_layout.addWidget(self.export_button)

        viewer_controls = QWidget()
        view_layout = QHBoxLayout(viewer_controls)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(4)
        thread_label = QLabel("Threads")
        view_layout.addWidget(thread_label)
        self.thread_spin = QSpinBox()
        self.thread_spin.setAccessibleName(thread_label.text())
        self.thread_spin.setRange(1, max(1, os.cpu_count() or 1))
        self.thread_spin.setValue(min(16, max(1, os.cpu_count() or 1)))
        self.thread_spin.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        view_layout.addWidget(self.thread_spin)
        self.thread_spin.setToolTip(
            "Applies to native compressed and LMSRAW histograms. "
            "PTU and Python fallback use one worker."
        )
        view_layout.addWidget(details_button)
        view_layout.addStretch()
        controls = QWidget()
        controls.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        controls_layout = _wrapping_row(controls)
        controls_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        controls_layout.addRow(export_controls, viewer_controls)
        toolbar_layout.addRow(controls, self._build_attribution())
        return toolbar

    @staticmethod
    def _build_attribution() -> QWidget:
        """Keep the affiliation together when the toolbar wraps."""
        branding = QWidget()
        layout = QHBoxLayout(branding)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addStretch()
        attribution = QLabel("Advanced Image Group")
        attribution.setFont(QFont("Arial", 16, QFont.Weight.DemiBold))
        attribution.setWordWrap(True)
        attribution.setStyleSheet("color: #666666")
        layout.addWidget(attribution, alignment=Qt.AlignmentFlag.AlignVCenter)
        logo = QLabel()
        logo.setAccessibleName("King’s College London")
        logo.setPixmap(QPixmap(str(Path(__file__).with_name("kcl_logo.png"))))
        logo.setFixedSize(63, 48)
        logo.setScaledContents(True)
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignVCenter)
        return branding

    def _build_summary_panel(self) -> QWidget:
        """Construct calibrated dataset details and synchronized plane
        controls.
        """
        summary_panel = QWidget()
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.block_title = QLabel()
        self.block_title.setWordWrap(True)
        self.block_title.setTextFormat(Qt.TextFormat.RichText)
        self.block_title.setFont(QFont("Arial", 11))
        summary_layout.addWidget(self.block_title)
        form = QFormLayout()
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.fields = {
            name: QLabel("-")
            for name in (
                "Dimensions",
                "Rows",
                "Photons",
                "Memory block",
                "Histogram cube",
                "Repetition rate",
                "Decoder",
                "Threads",
                "Decode time",
                "Event flags",
            )
        }
        for name, label in self.fields.items():
            label.setWordWrap(True)
            if name == "Repetition rate":
                label.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            form.addRow(name, label)
        self.event_flags = EventFlagSelector(vertical=True)
        connect_signal(self.event_flags.changed, self._event_flags_changed)
        form.addRow("Event selection", self.event_flags)
        self.reflection_filter = ReflectionPhotonFilter()
        form.addRow("Filter reflection", self.reflection_filter)
        summary_layout.addLayout(form)
        self.plane_controls = QWidget()
        plane_layout = QHBoxLayout(self.plane_controls)
        plane_layout.setContentsMargins(0, 4, 0, 4)
        self.previous_plane = QPushButton("<")
        self.previous_plane.setToolTip("Previous frame or z-plane")
        self.previous_plane.setFixedWidth(34)
        self.plane_combo = QComboBox()
        self.plane_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.next_plane = QPushButton(">")
        self.next_plane.setToolTip("Next frame or z-plane")
        self.next_plane.setFixedWidth(34)
        plane_layout.addWidget(self.previous_plane)
        plane_layout.addWidget(self.plane_combo, 1)
        plane_layout.addWidget(self.next_plane)
        connect_signal(
            self.previous_plane.clicked, lambda: self._step_plane(-1)
        )
        connect_signal(self.next_plane.clicked, lambda: self._step_plane(1))
        connect_signal(
            self.plane_combo.currentIndexChanged, self._plane_changed
        )
        summary_layout.addWidget(self.plane_controls)
        summary_layout.addStretch()
        self.clear_roi_button = QPushButton("Clear ROI")
        connect_signal(self.clear_roi_button.clicked, self.clear_roi)
        summary_layout.addWidget(self.clear_roi_button)
        return summary_panel
