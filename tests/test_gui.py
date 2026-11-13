"""Observable desktop regressions for ROI and workspace interactions."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from leica_flim_converter import gui_plot, gui_workspace, gui_workspace_preview
from leica_flim_converter.catalog import DatasetInfo, scan_lif
from leica_flim_converter.gui import (
    DecodeWorker,
    IcsExportDialog,
    MainWindow,
    PtuExportDialog,
    ScanWorker,
)
from leica_flim_converter.gui_helpers import _draw_histogram_curves
from leica_flim_converter.histogram import HistogramCube
from leica_flim_converter.version import APPLICATION_VERSION
from tests.test_reference_science import example_path


class ImmediatePreview(DecodeWorker):
    """Complete deterministic cubes through the real Qt worker
    lifecycle.
    """

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        counts = np.arange(256, dtype=np.uint32).reshape(16, 4, 4)
        counts += self.dataset.channel_index
        cube = HistogramCube(
            counts=counts,
            events=int(counts.sum(dtype=np.uint64)),
            overflow_events=0,
            period_bins=16,
            backend="gui-fixture",
            thread_count=1,
            decoded_rows=4,
            elapsed_seconds=0.0,
            event_flag_mask=self.event_flag_mask,
        )
        self._complete(cube, "")


class ImmediateIndex(ScanWorker):
    """Exercise normal grouped import completion with deterministic
    data.
    """

    fixture_datasets: list[DatasetInfo] = []

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        self._complete(self.fixture_datasets, 0.0, "")


class FailedPreview(DecodeWorker):
    """Publish a failure through the actual worker lifecycle."""

    def run(self) -> None:
        """Simulate invalid photon data after successful indexing."""
        self._complete(None, "Invalid photon data")


@pytest.fixture(name="workspace")
def workspace_fixture(
    qtbot: QtBot, raw_dataset: DatasetInfo, monkeypatch: pytest.MonkeyPatch
) -> MainWindow:
    """Set up a visible scientific workspace using normal completion
    signals.
    """
    monkeypatch.setattr(
        gui_workspace_preview, "DecodeWorker", ImmediatePreview
    )
    dataset = replace(
        raw_dataset,
        width=4,
        height=4,
        decoded_rows=4,
        total_photons=32640,
        channel_count=2,
        detector_name="Detector 1",
        channel_index=0,
        emission_filter_band="440 - 500 nm",
    )
    second = replace(dataset, channel_index=1, detector_name="Detector 2")
    ImmediateIndex.fixture_datasets = [dataset, second]
    monkeypatch.setattr(gui_workspace, "ScanWorker", ImmediateIndex)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(dataset.source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=10000)
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            window.block_list.item(row).data(Qt.ItemDataRole.UserRole),
            DatasetInfo,
        )
    )
    window.select_block(item)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    return window


def switch_to_single(window: MainWindow, qtbot: QtBot) -> None:
    """Choose one detector through its visible selector."""
    window.pair_selector.set_selection([window.datasets[0].key])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.cube is not None


def test_filter_labels_align_in_narrow_windows(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Stack event choices and keep details aligned when narrowed."""
    assert workspace.windowTitle() == (
        "Leica Image Files Translated into Open File Formats "
        f"(LIFTOFF) {APPLICATION_VERSION}"
    )
    assert any(
        label.text() == "LIFTOFF Application"
        for label in workspace.findChildren(QLabel)
    )
    scroll = workspace.findChild(QScrollArea, "datasetDetailsScroll")
    assert isinstance(scroll, QScrollArea)
    assert workspace.width() == 1500
    assert workspace.clear_button.text() == "Clear all data"
    assert not scroll.horizontalScrollBar().isVisible()
    buttons = (
        workspace.event_flags.raw_all,
        workspace.event_flags.raw_first,
        workspace.event_flags.raw_standard,
    )
    panel = workspace.event_flags.parentWidget()
    assert panel is not None
    labels = panel.findChildren(QLabel)
    event_label = next(
        label for label in labels if label.text() == "Event selection"
    )
    photon_label = next(label for label in labels if label.text() == "Photons")
    assert workspace.fields["Photons"].y() == photon_label.y()
    assert workspace.fields["Photons"].minimumHeight() == 0
    first = buttons[0].mapTo(panel, buttons[0].rect().center())
    assert abs(first.y() - event_label.geometry().center().y()) <= 4
    assert buttons[0].x() == buttons[1].x() == buttons[2].x()
    assert buttons[0].geometry().bottom() < buttons[1].y()
    assert buttons[1].geometry().bottom() < buttons[2].y()
    assert isinstance(workspace.reflection_filter.checkbox, QRadioButton)
    assert not workspace.reflection_filter.checkbox.autoExclusive()
    for button in buttons:
        assert button.width() >= button.sizeHint().width()
        parent = button.parentWidget()
        assert parent is not None
        assert parent.rect().contains(button.geometry())
    workspace.resize(1000, 900)
    qtbot.wait(10)
    assert not scroll.horizontalScrollBar().isVisible()
    for button in buttons:
        assert button.width() >= button.sizeHint().width()
    last = buttons[-1]
    scroll.ensureWidgetVisible(last)
    qtbot.wait(10)
    assert (
        scroll.viewport()
        .rect()
        .contains(last.mapTo(scroll.viewport(), last.rect().center()))
    )
    workspace.resize(1500, 900)
    qtbot.waitUntil(lambda: not scroll.horizontalScrollBar().isVisible())


def test_details_heading_clears_unselected_wavelengths(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Remove the optical summary when no channels are displayed."""
    assert workspace.block_title.text() == (
        "<b>Synthetic</b> | Ex. unavailable / Em. 440-500 nm"
    )
    workspace.pair_selector.set_selection([])
    assert workspace.block_title.text() == "<b>Synthetic</b>"
    workspace.pair_selector.set_selection([workspace.datasets[0].key])
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.block_title.text() == (
        "<b>Synthetic</b> | Ex. unavailable / Em. 440-500 nm"
    )


def test_failure_without_preview_counts(
    workspace: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing preview counts cannot hide an actual decoding failure."""
    datasets = [
        replace(dataset, total_photons=None) for dataset in workspace.datasets
    ]
    workspace.remove_source_data(datasets[0].source)
    ImmediateIndex.fixture_datasets = datasets
    workspace.open_button.click()
    qtbot.waitUntil(lambda: workspace.scan_worker is None, timeout=10000)
    monkeypatch.setattr(gui_workspace_preview, "DecodeWorker", FailedPreview)
    workspace.select_block(workspace.block_list.item(1))
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.cube is None
    assert workspace.fields["Histogram cube"].text() == "Not loaded"
    assert workspace.fields["Decoder"].text() == "Failed: Invalid photon data"
    assert "decode failed" in workspace.fields["Photons"].text()
    assert "raw counts unavailable" in workspace.fields["Photons"].text()


def activate_overlap(window: MainWindow, qtbot: QtBot) -> None:
    """Activate both overlapping outlines with one user click."""
    canvas = window.image
    canvas.rois = [(0, 0, 2, 2), (1, 1, 3, 3)]
    canvas.roi_colors = [QColor("#00a6fb"), QColor("#ff8c42")]
    canvas.activated_rois = set()
    canvas.update()
    qtbot.wait(30)
    rect = canvas.image_rect
    point = QPoint(
        int(rect.left() + rect.width() * 0.375),
        int(rect.top() + rect.height() * 0.375),
    )
    QTest.mouseClick(
        canvas,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        point,
    )
    assert canvas.activated_rois == {0, 1}


def test_combined_overlap_counts_once(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Orange combined curves count the union of pixels once."""
    switch_to_single(workspace, qtbot)
    activate_overlap(workspace, qtbot)
    workspace.combine_rois_checkbox.click()
    series = workspace.histogram.series
    assert len(series) == 1
    _label, counts, color = series[0]
    pixels = {(x, y) for y in range(3) for x in range(3)} | {
        (x, y) for y in range(1, 4) for x in range(1, 4)
    }
    expected = [
        sum((bin_index * 16 + y * 4 + x for x, y in pixels))
        for bin_index in range(16)
    ]
    assert counts.tolist() == expected
    assert QColor(color).name() == "#d28a00"
    assert "100.00 ps/bin" in workspace.histogram.histogram_x_axis_label()
    assert workspace.image.activated_rois == {0, 1}
    workspace.clear_roi_button.click()
    assert workspace.image.rois == []
    assert workspace.image.activated_rois == set()


@pytest.mark.parametrize("single_channel", [False, True])
def test_photon_count_scale_controls(
    workspace: MainWindow,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    single_channel: bool,
) -> None:
    """Scale toggles persist through ROI updates without decoding."""
    if single_channel:
        switch_to_single(workspace, qtbot)
    plot = workspace.histogram
    log = plot.log_scale_button
    assert not plot.findChildren(QPushButton, "linearScaleButton")
    assert log.text() == "Log scale" and not log.isChecked()
    for width in (1000, 1650):
        workspace.resize(width, 900)
        qtbot.wait(10)
        for button in (log,):
            assert button.isVisible() and button.isEnabled()
            assert (
                button.geometry().bottom() < plot.reflection.detect_button.y()
            )
            assert plot.rect().contains(button.geometry())
        automatic = plot.reflection.detect_button
        clear = plot.reflection.clear_button
        combine = workspace.combine_rois_checkbox
        assert clear.x() > automatic.geometry().right()
        assert clear.y() == automatic.y()
        assert combine.y() > automatic.geometry().bottom()
        assert combine.geometry().right() == clear.geometry().right()
    original_x_axis = plot.histogram_x_axis_label()
    plot.grab()
    titles = [
        panel["title"]
        for panel in getattr(plot, "_last_histogram_layout", {})["panels"]
    ]
    assert (
        titles == [""]
        if single_channel
        else all(title and "\n" not in title for title in titles)
    )
    original_panels = plot.multichannel_panels
    original_series = plot.series
    draw_curves = Mock(wraps=_draw_histogram_curves)
    monkeypatch.setattr(gui_plot, "_draw_histogram_curves", draw_curves)
    log.click()
    assert log.isChecked()
    log.click()
    assert not log.isChecked() and not plot.logarithmic_scale
    log.click()
    assert log.isChecked()
    assert plot.logarithmic_scale
    assert plot.multichannel_panels is original_panels
    assert plot.series is original_series
    assert workspace.decode_worker is None
    plot.repaint()
    assert draw_curves.call_count == (1 if single_channel else 2)
    assert all(call.args[-1] for call in draw_curves.call_args_list)
    if single_channel:
        activate_overlap(workspace, qtbot)
    else:
        canvas = workspace.image
        layout = canvas.multichannel_mirror_layout[0]
        x, y = layout["x"], layout["header"]
        canvas.rois = [(x, y, x + 2, y + 2), (x + 1, y + 1, x + 3, y + 3)]
        canvas.roi_colors = [QColor("#00a6fb"), QColor("#ff8c42")]
        canvas.activated_rois = {0, 1}
        canvas.hover_ended.emit()
    workspace.combine_rois_checkbox.click()
    assert log.isChecked() and plot.logarithmic_scale
    plot.repaint()
    log.click()
    draw_curves.reset_mock()
    plot.repaint()
    assert not any(call.args[-1] for call in draw_curves.call_args_list)
    assert not log.isChecked()
    assert not plot.logarithmic_scale
    assert plot.histogram_x_axis_label() == original_x_axis
    assert workspace.decode_worker is None


def test_channel_retention_and_mirrors(
    workspace: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain active ROI identities and mirror outlines across
    detectors.
    """
    switch_to_single(workspace, qtbot)
    activate_overlap(workspace, qtbot)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    workspace.pair_selector.set_selection(
        dataset.key for dataset in workspace.datasets
    )
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    qtbot.wait(30)
    assert len(workspace.image.rois) == 2
    assert workspace.image.activated_rois == {0, 1}
    assert workspace.cube is None
    image = workspace.image.grab()
    assert not image.isNull()
    assert len(workspace.image.last_mirrored_roi_layout) == 2
    workspace.combine_rois_checkbox.click()
    qtbot.wait(30)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No
    )
    workspace.pair_selector.set_selection([workspace.datasets[1].key])
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.image.rois == []


def test_inactive_roi_delete_and_zoom(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Right-click removes inactive outlines while zoom preserves data
    ROI.
    """
    switch_to_single(workspace, qtbot)
    canvas = workspace.image
    canvas.rois = [(0, 0, 3, 3), (3, 3, 4, 4)]
    canvas.roi_colors = [QColor("#00a6fb"), QColor("#ff8c42")]
    canvas.activated_rois = {0}
    canvas.update()
    qtbot.wait(30)
    rect = canvas.image_rect
    point = QPoint(
        int(rect.left() + rect.width() * 0.875),
        int(rect.top() + rect.height() * 0.875),
    )
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
    assert canvas.rois == [(0, 0, 3, 3)]
    assert canvas.activated_rois == {0}
    workspace.zoom_in_button.click()
    point = QPoint(int(rect.center().x()), int(rect.center().y()))
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    assert canvas.view_zoom > 1.0
    assert canvas.rois == [(0, 0, 3, 3)]


class CancellableIndex(ScanWorker):
    """Exercise cancellation while a real QThread is still running."""

    started_work = threading.Event()

    def run(self) -> None:
        """Wait for user cancellation before publishing completion."""
        self.started_work.set()
        self.cancel_event.wait(timeout=10)
        self._complete([], 0.0, "Cancelled")


@pytest.mark.parametrize("close", [False, True])
def test_cancel_and_close_during_work(
    qtbot: QtBot,
    raw_dataset: DatasetInfo,
    monkeypatch: pytest.MonkeyPatch,
    close: bool,
) -> None:
    """A window remains alive until its cancelled indexing thread
    ends.
    """
    CancellableIndex.started_work.clear()
    monkeypatch.setattr(gui_workspace, "ScanWorker", CancellableIndex)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(raw_dataset.source)], "LIF files (*.lif)"),
    )
    window.open_button.click()
    qtbot.waitUntil(CancellableIndex.started_work.is_set)
    worker = window.scan_worker
    assert worker is not None and worker.isRunning()
    if close:
        window.close()
    else:
        window.cancel_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=10000)
    assert not worker.isRunning()
    assert worker.cancel_event.is_set()
    assert not window.datasets
    if close:
        qtbot.waitUntil(lambda: not window.isVisible())
    else:
        assert window.status_label.text() == "Indexing cancelled"
        assert window.open_button.isEnabled()


def test_repeated_import_and_source_removal(
    workspace: MainWindow,
    qtbot: QtBot,
) -> None:
    """Repeated imports do not duplicate groups and removal clears
    data.
    """
    original_count = workspace.block_list.count()
    workspace.open_button.click()
    workspace.open_button.click()
    assert workspace.scan_worker is None
    assert workspace.block_list.count() == original_count
    assert "already open" in workspace.status_label.text()
    source = workspace.datasets[0].source
    assert workspace.remove_source_data(source)
    qtbot.wait(30)
    assert not workspace.loaded_sources
    assert not workspace.datasets
    assert workspace.cube is None
    assert workspace.block_list.count() == 0
    assert not workspace.export_button.isEnabled()


def test_filter_preserves_active_roi(
    workspace: MainWindow,
    qtbot: QtBot,
) -> None:
    """A photon-filter transition retains active outlines and
    numbering.
    """
    switch_to_single(workspace, qtbot)
    activate_overlap(workspace, qtbot)
    original = list(workspace.image.rois)
    workspace.event_flags.raw_first.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.image.rois == original
    assert workspace.image.activated_rois == {0, 1}
    assert workspace.cube is not None
    assert workspace.cube.event_flag_mask == 512


@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
def test_export_preflight_failure(
    qtbot: QtBot,
    raw_dataset: DatasetInfo,
    dialog_type: type[IcsExportDialog] | type[PtuExportDialog],
) -> None:
    """Both formats reject unavailable sources with diagnostic
    tooltips.
    """
    missing = replace(raw_dataset, source=Path("missing-source.lif"))
    dialog = dialog_type([raw_dataset, missing], {})
    qtbot.addWidget(dialog)
    dialog.show()
    rows = [
        (row, target)
        for row, target in enumerate(dialog.row_targets)
        if target is not None
    ]
    statuses = {}
    for row, target in rows:
        dataset, _plane = target
        state = dialog.table.item(row, 9)
        check = dialog.table.item(row, 0)
        assert state is not None and check is not None
        statuses[dataset.key] = state.text()
        if dataset.source == missing.source:
            assert state.toolTip()
            assert not check.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert statuses[raw_dataset.key] == "Ready"
    assert statuses[missing.key] == "Failed"


@pytest.mark.real_data
@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
def test_export_plane_menu(
    qtbot: QtBot, dialog_type: type[IcsExportDialog] | type[PtuExportDialog]
) -> None:
    """Compact rows expand through their menu without losing
    selection.
    """
    path = example_path("Sample2_HCC_mTFP1_12days.lif")
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    dataset = scan_lif(path)[0]
    dialog = dialog_type([dataset], {})
    qtbot.addWidget(dialog)
    dialog.show()
    next(
        button
        for button in dialog.findChildren(QPushButton)
        if button.text() == "Select All"
    ).click()

    def visible() -> list[int]:
        return [
            row
            for row, target in enumerate(dialog.row_targets)
            if target is not None and not dialog.table.isRowHidden(row)
        ]

    assert len(visible()) == 1
    first_row = visible()[0]
    output = dialog.table.item(first_row, dialog.table.columnCount() - 1)
    assert output is not None and "9 plane-specific" in output.text()
    button = dialog.table.cellWidget(first_row, 7)
    assert isinstance(button, QToolButton)
    menu = button.menu()
    assert menu is not None
    next(
        action
        for action in menu.actions()
        if action.text() == "Select Z-planes"
    ).trigger()
    assert len(visible()) == 9
    assert dialog.selected_datasets() == [dataset]
    planes = (
        dialog.selected_plane_selection()
        if isinstance(dialog, IcsExportDialog)
        else dialog.selected_planes()
    )
    assert set(planes[dataset.key]) == set(range(9))
    if isinstance(dialog, IcsExportDialog):
        for row in visible():
            item = dialog.table.item(row, 10)
            assert item is not None and item.text() == "1"


@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
def test_selector_presentation(
    qtbot: QtBot,
    raw_dataset: DatasetInfo,
    dialog_type: type[IcsExportDialog] | type[PtuExportDialog],
) -> None:
    """Radio buttons identify the selection without a second status
    line.
    """
    dialog = dialog_type([raw_dataset], {})
    qtbot.addWidget(dialog)
    dialog.show()
    selector = dialog.event_flags
    for button in (
        selector.raw_first,
        selector.raw_standard,
        selector.raw_all,
    ):
        button.click()
        assert selector.selection_label.isHidden()
        assert selector.selection_label.maximumHeight() == 0
        assert selector.selection_label.text() == ""


def test_pan_and_active_roi_protection(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Navigation leaves active ROI coordinates and numbering intact."""
    switch_to_single(workspace, qtbot)
    activate_overlap(workspace, qtbot)
    canvas = workspace.image
    original = list(canvas.rois)
    numbers = list(canvas.roi_number_snapshot)
    rect = canvas.image_rect
    point = QPoint(int(rect.center().x()), int(rect.center().y()))
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, pos=point)
    assert canvas.rois == original
    workspace.zoom_in_button.click()
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)
    qtbot.wait(30)
    before = (canvas.view_center_x, canvas.view_center_y)
    workspace.pan_button.click()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(canvas, point + QPoint(40, 20), delay=20)
    QTest.mouseRelease(
        canvas, Qt.MouseButton.LeftButton, pos=point + QPoint(40, 20)
    )
    assert (canvas.view_center_x, canvas.view_center_y) != before
    assert canvas.rois == original
    assert numbers == canvas.roi_number_snapshot
    canvas.reset_view()
    assert canvas.view_zoom == 1.0
    assert (canvas.view_center_x, canvas.view_center_y) == (0.5, 0.5)


def test_synchronized_plane_navigation(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Two detector previews follow the same T/Z selection and
    arrows.
    """
    group = [
        replace(
            dataset,
            t_count=2,
            z_count=3,
            dimension_order=("T", "Z"),
            decoded_rows=24,
            t_stride=3,
            z_stride=1,
        )
        for dataset in workspace.datasets
    ]
    workspace.remove_source_data(group[0].source)
    ImmediateIndex.fixture_datasets = group
    workspace.open_button.click()
    qtbot.waitUntil(lambda: workspace.scan_worker is None, timeout=10000)
    item = next(
        workspace.block_list.item(row)
        for row in range(workspace.block_list.count())
        if isinstance(
            workspace.block_list.item(row).data(Qt.ItemDataRole.UserRole),
            DatasetInfo,
        )
    )
    workspace.select_block(item)
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.current_plane == 0
    assert workspace.plane_combo.currentData() == 0
    workspace.next_plane.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.current_plane == 1
    assert workspace.plane_combo.currentData() == 1
    panels = workspace.histogram.multichannel_panels
    assert panels is not None
    assert not workspace.histogram.separate_tiles_button.isVisible()
    assert workspace.histogram.graph_panels() == panels
    assert [panel["title"] for panel in panels] == [
        "Ex. unavailable /\nEm. 440 - 500 nm (Detector 1)",
        "Ex. unavailable /\nEm. 440 - 500 nm (Detector 2)",
    ]
    assert [panel["photons"] for panel in panels] == [32640, 32896]
    workspace.plane_combo.setCurrentIndex(6)
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.current_plane == 5
    assert workspace.plane_combo.currentData() == 5
    workspace.previous_plane.click()
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert workspace.current_plane == 4


@pytest.mark.real_data
@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
def test_series006_preflight(
    qtbot: QtBot, dialog_type: type[IcsExportDialog] | type[PtuExportDialog]
) -> None:
    """Unresolved Series006 stays failed while partial indexes are
    ready.
    """
    path = example_path("Autofluorescence.lif")
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    dialog = dialog_type(scan_lif(path), {})
    qtbot.addWidget(dialog)
    states = []
    for row, target in enumerate(dialog.row_targets):
        if target is None:
            continue
        dataset, _plane = target
        status = dialog.table.item(row, 9)
        assert status is not None
        if dataset.acquisition_name == "Series006":
            assert status.text() == "Failed"
            assert status.toolTip()
        else:
            assert status.text() == "Ready", dataset.display_name
        states.append(status.text())
    assert states.count("Failed") == 2


@pytest.mark.real_data
@pytest.mark.parametrize("close", [False, True])
def test_cancel_and_close_during_native_decode(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, close: bool
) -> None:
    """Cancel an actual large compressed preview before thread
    teardown.
    """
    path = example_path("PL109 R72C CC CCCP NH4Cl.lif")
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(path)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.thread_spin.setValue(1)
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=10000)
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            dataset := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and dataset.memory_id == "MemBlock_9267"
    )
    window.select_block(item)
    qtbot.wait(100)
    worker = window.decode_worker
    assert worker is not None and worker.isRunning()
    if close:
        window.close()
    else:
        window.cancel_button.click()
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert not worker.isRunning()
    assert worker.cancel_event.is_set()
    assert window.cube is None
    if close:
        qtbot.waitUntil(lambda: not window.isVisible())
    else:
        assert window.status_label.text() == "Cancelled"
        assert window.open_button.isEnabled()
