"""Export reflection checkboxes and immutable preview snapshots."""

# Exercise the compact table and source-backed workspace controls.
# pylint: disable=protected-access

import json
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox
from pytestqt.qtbot import QtBot

from leica_flim_converter import gui_reflection, gui_workspace
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from leica_flim_converter.gui_ptu_dialog import PtuExportDialog
from leica_flim_converter.reflection_export import (
    ReflectionWindow,
    reflection_window,
)
from tests.test_gui import ImmediateIndex, switch_to_single, workspace_fixture
from tests.test_multichannel_mosaic_gui import _open_matrix
from tests.test_reflection_filter import _place
from tests.test_reflection_gui import _drag_boundary, open_example_workspace

preview_fixture = workspace_fixture


@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
def test_export_reflection_checkbox(
    qtbot: QtBot, raw_dataset: DatasetInfo, dialog_type
) -> None:
    """Offer filtering for mixed selections and preserve opt-in."""
    second_path = raw_dataset.source.with_name("second.lif")
    second_path.write_bytes(raw_dataset.source.read_bytes())
    second = replace(raw_dataset, source=second_path)
    window = ReflectionWindow(raw_dataset.key, 9.5, 12.5)
    dialog = dialog_type(
        [raw_dataset, second], {}, reflection_windows=(window,)
    )
    qtbot.addWidget(dialog)
    dialog.show()
    dialog._set_all(Qt.CheckState.Unchecked)
    row = next(
        i for i, target in enumerate(dialog.row_targets) if target is not None
    )
    required_table_item(dialog.table, row, 0).setCheckState(
        Qt.CheckState.Checked
    )
    control = dialog.export_reflection
    labels = {label.text(): label for label in dialog.findChildren(QLabel)}
    event_label = labels["Event selection"]
    reflection_label = labels["Filter reflection photons where applicable"]
    assert event_label.x() == reflection_label.x()
    assert event_label.geometry().bottom() < reflection_label.y()
    event_button = dialog.event_flags.raw_all
    event_origin = event_button.mapTo(dialog, QPoint())
    checkbox_origin = control.checkbox.mapTo(dialog, QPoint())
    assert event_origin.x() == checkbox_origin.x()
    label_right = max(
        event_label.geometry().right(), reflection_label.geometry().right()
    )
    assert 0 < event_origin.x() - label_right < 15
    assert reflection_label.buddy() is control
    assert control.checkbox.accessibleName() == reflection_label.text()
    assert control.checkbox.isEnabled()
    assert not control.checkbox.isChecked()
    assert control.y() > dialog.event_flags.geometry().bottom()
    control.checkbox.click()
    options = (
        dialog.options(1)
        if isinstance(dialog, IcsExportDialog)
        else dialog.options()
    )
    assert options.reflection_windows == (window,)
    dialog._set_all(Qt.CheckState.Checked)
    assert len(dialog.selected_datasets()) == 2, [
        (target[0].key, required_table_item(dialog.table, i, 9).text())
        for i, target in enumerate(dialog.row_targets)
        if target is not None
    ]
    assert control.checkbox.isEnabled() and control.checkbox.isChecked()
    export = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert export.isEnabled()
    assert control.windows == (window,)
    assert "1 of 2 selected outputs" in control.status.text()
    required_table_item(dialog.table, row, 0).setCheckState(
        Qt.CheckState.Unchecked
    )
    assert not control.checkbox.isEnabled()
    assert not control.windows
    assert export.isEnabled()
    required_table_item(dialog.table, row, 0).setCheckState(
        Qt.CheckState.Checked
    )
    assert control.checkbox.isEnabled() and control.checkbox.isChecked()
    control.checkbox.click()
    assert not control.windows
    assert export.isEnabled()
    empty = dialog_type([raw_dataset], {})
    qtbot.addWidget(empty)
    empty._set_all(Qt.CheckState.Checked)
    assert not empty.export_reflection.checkbox.isEnabled()
    assert (
        empty.export_reflection.status.text()
        == "No reflection peak identified."
    )


def test_preview_boundaries_snapshot(
    workspace: MainWindow, qtbot: QtBot
) -> None:
    """Snapshot bounds independently of preview filtering."""
    switch_to_single(workspace, qtbot)
    _place(workspace, qtbot)
    windows = workspace.reflection_filter.export_windows()
    assert len(windows) == 1
    cube = workspace.cube
    assert cube is not None and workspace.selected is not None
    assert windows[0].dataset_key == workspace.selected.key
    bounds = next(iter(workspace.histogram.reflection.regions.values()))
    assert (windows[0].lower, windows[0].upper) == bounds
    workspace.reflection_filter.checkbox.click()
    assert workspace.reflection_filter.export_windows() == windows
    workspace.reflection_filter.checkbox.click()
    workspace.histogram.reflection.clear_button.click()
    assert not workspace.reflection_filter.export_windows()
    assert (windows[0].lower, windows[0].upper) == bounds


def test_restore_mixed_detector_filters(
    workspace: MainWindow, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restore each detector's edited bounds and toggle."""
    switch_to_single(workspace, qtbot)
    first, second = workspace.datasets
    control = workspace.reflection_filter
    markers = workspace.histogram.reflection
    monkeypatch.setattr(
        gui_reflection, "detect_reflection_peak", lambda _: (1.5, 3.5)
    )
    workspace.histogram.grab()
    markers.detect_button.click()
    _drag_boundary(qtbot, workspace.histogram, 0, 0.05)
    (first_window,) = control.export_windows()
    assert first_window.lower != 1.5
    control.checkbox.click()

    workspace.pair_selector.set_selection([second.key])
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert not markers.regions and not control.checkbox.isChecked()
    _place(workspace, qtbot)
    windows = control.export_windows()
    assert {item.dataset_key for item in windows} == {first.key, second.key}
    assert first_window in windows

    workspace.pair_selector.set_selection([first.key, second.key])
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
    assert control.checkbox.isChecked()
    assert len(markers.regions) == 2
    graphs = workspace.histogram.graph_panels()
    assert markers.omitted(markers.graph_key(graphs[0], 16)) == (
        first_window.lower,
        first_window.upper,
    )
    assert markers.omitted(markers.graph_key(graphs[1], 16, 1)) is None

    switch_to_single(workspace, qtbot)
    assert control.checkbox.isChecked()
    control.checkbox.click()
    markers.clear_button.click()
    assert [item.dataset_key for item in control.export_windows()] == [
        second.key
    ]
    workspace.clear_data()
    assert not control.export_windows()


@pytest.mark.parametrize("dialog_type", [IcsExportDialog, PtuExportDialog])
@pytest.mark.parametrize(
    "second_has_bounds", [True, False], ids=["all-covered", "partly-covered"]
)
def test_export_bounds_from_other_entries(
    raw_dataset: DatasetInfo,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    dialog_type: type[IcsExportDialog] | type[PtuExportDialog],
    second_has_bounds: bool,
) -> None:
    """Batch-export two LIF entries with optional bounds for each."""
    source = raw_dataset.source.with_name("second.lif")
    source.write_bytes(raw_dataset.source.read_bytes())
    second = replace(raw_dataset, source=source)
    monkeypatch.setattr(
        ImmediateIndex, "fixture_datasets", [raw_dataset, second]
    )
    monkeypatch.setattr(gui_workspace, "ScanWorker", ImmediateIndex)
    workspace = MainWindow()
    qtbot.addWidget(workspace)
    workspace.show()
    workspace._load_files([raw_dataset.source, source])
    qtbot.waitUntil(lambda: workspace.scan_worker is None, timeout=10000)

    bounds = iter([(9.5, 12.5), (4.5, 8.5)])
    monkeypatch.setattr(
        gui_reflection, "detect_reflection_peak", lambda _: next(bounds)
    )
    control = workspace.reflection_filter
    for row in (1, 3):
        workspace.select_block(workspace.block_list.item(row))
        qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=10000)
        assert workspace.cube is not None, workspace.status_label.text()
        if row == 3 and not second_has_bounds:
            continue
        workspace.histogram.grab()
        workspace.histogram.reflection.detect_button.click()
        assert (
            control.checkbox.isEnabled() and not control.checkbox.isChecked()
        )
        control.checkbox.click()
    windows = control.export_windows()
    assert len(windows) == (2 if second_has_bounds else 1)
    assert workspace.selected == second
    destination = source.parent / "export"

    def accept_export(dialog):
        dialog.destination.setText(str(destination))
        dialog._set_all(Qt.CheckState.Checked)
        dialog.event_flags.raw_all.click()
        assert {item.key for item in dialog.selected_datasets()} == {
            raw_dataset.key,
            second.key,
        }
        checkbox = dialog.export_reflection.checkbox
        assert checkbox.isEnabled() and not checkbox.isChecked()
        assert not dialog.export_reflection.windows
        checkbox.click()
        assert dialog.buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).isEnabled()
        assert dialog.export_reflection.windows == windows
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialog_type, "exec", accept_export)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    if dialog_type is IcsExportDialog:
        workspace.export_button.click()
        extension = "ics"
    else:
        workspace.ptu_export_button.click()
        extension = "ptu"
    qtbot.waitUntil(lambda: workspace.export_worker is None, timeout=30000)
    reports = {}
    for path in destination.glob(f"*.{extension}.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        reports[report["datasetKey"]] = report
    assert set(reports) == {raw_dataset.key, second.key}
    windows_by_key = {window.dataset_key: window for window in windows}
    for dataset_key, report in reports.items():
        metadata = report if extension == "ics" else report["export"]
        reflection = metadata["reflectionFilter"]
        accounting = metadata.get("photonAccounting", metadata)
        window = windows_by_key.get(dataset_key)
        if window is None:
            assert reflection == {"enabled": False}
            assert accounting["excludedReflectionPhotons"] == 0
            continue
        assert reflection["lowerNativeBin"] == window.lower
        assert reflection["upperNativeBin"] == window.upper
        assert accounting["excludedReflectionPhotons"] > 0

    assert workspace.remove_source_data(raw_dataset.source)
    assert control.export_windows() == tuple(
        window for window in windows if window.dataset_key == second.key
    )


def test_mosaic_export_boundaries(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map shared tile markers back to the original export dataset."""
    workspace = _open_matrix(tmp_path, qtbot, monkeypatch)
    _place(workspace, qtbot)
    windows = workspace.reflection_filter.export_windows()
    assert len(windows) == 1
    dataset = next(
        item
        for item in workspace.datasets
        if item.key == windows[0].dataset_key
    )
    assert dataset.mosaic is not None and dataset.tile_index is None
    assert windows[0].planes is not None
    assert len(windows[0].planes) == dataset.stage_count
    assert {dataset.plane_indices(plane) for plane in windows[0].planes} == {
        (0, 0)
    }
    plane = windows[0].planes[0]
    original_index = workspace.plane_combo.currentIndex()
    workspace.reflection_filter.checkbox.click()
    workspace.plane_combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=30000)
    assert not workspace.histogram.reflection.regions
    assert workspace.reflection_filter.export_windows() == windows
    _place(workspace, qtbot)
    _drag_boundary(qtbot, workspace.histogram, 0, 0.1)
    saved = workspace.reflection_filter.export_windows()
    assert reflection_window(saved, dataset, plane) == windows[0]
    overview = reflection_window(saved, dataset, None)
    assert overview is not None and overview.planes is None
    assert overview.lower != windows[0].lower
    other_plane = next(
        index
        for index in range(dataset.plane_count)
        if index not in windows[0].planes
    )
    assert reflection_window(saved, dataset, other_plane) == overview
    workspace.plane_combo.setCurrentIndex(original_index)
    qtbot.waitUntil(lambda: workspace.decode_worker is None, timeout=30000)
    assert workspace.reflection_filter.checkbox.isChecked()
    assert list(workspace.histogram.reflection.regions.values()) == [
        (windows[0].lower, windows[0].upper)
    ]


@pytest.mark.real_data
@pytest.mark.parametrize("format_name", ["ics", "ptu"])
def test_example_export_from_workspace(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    format_name: str,
) -> None:
    """Export the Leica example through both application windows."""
    workspace = open_example_workspace(qtbot, monkeypatch)
    # Refresh controls after decode even when the window is obscured.
    workspace.histogram.grab()
    assert workspace.histogram.reflection.detect_button.isEnabled()
    workspace.histogram.reflection.detect_button.click()
    cube = workspace.cube
    assert cube is not None and workspace.selected is not None
    selected_key = workspace.selected.key
    bounds = next(iter(workspace.histogram.reflection.regions.values()))
    removed = int(cube.counts[int(bounds[0]) : int(bounds[1]) + 1].sum())
    destination = tmp_path / format_name

    def accept_export(dialog):
        dialog._set_all(Qt.CheckState.Unchecked)
        for row, target in enumerate(dialog.row_targets):
            if (
                target is not None
                and target[0].key == selected_key
                and not dialog.table.isRowHidden(row)
            ):
                required_table_item(dialog.table, row, 0).setCheckState(
                    Qt.CheckState.Checked
                )
        dialog.destination.setText(str(destination))
        assert dialog.export_reflection.checkbox.isEnabled()
        dialog.export_reflection.checkbox.click()
        assert dialog.buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).isEnabled()
        dialog.show()
        qtbot.wait(10)
        output = Path("validation_artifacts/reflection-peak")
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"export-{format_name}-filter.png"
        assert dialog.grab().save(str(target))
        dialog.hide()
        return QDialog.DialogCode.Accepted

    dialog_type = IcsExportDialog if format_name == "ics" else PtuExportDialog
    monkeypatch.setattr(dialog_type, "exec", accept_export)
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: messages.append(args)
    )
    if format_name == "ics":
        workspace.export_button.click()
    else:
        workspace.ptu_export_button.click()
    qtbot.waitUntil(lambda: workspace.export_worker is None, timeout=120000)
    assert messages and "0 failed" in workspace.status_label.text()
    files = list(destination.glob(f"*.{format_name}"))
    assert len(files) == 1
    metadata = json.loads(
        Path(str(files[0]) + ".json").read_text(encoding="utf-8")
    )
    if format_name == "ics":
        information = metadata["photonAccounting"]
        assert information["excludedReflectionPhotons"] == removed
        assert int(read_ics(files[0]).counts.sum()) == cube.events - removed
    else:
        information = metadata["export"]
        assert information["excludedReflectionPhotons"] == removed
        photons = inspect_ptu(files[0])
        assert not photons.microtime[int(bounds[0]) : int(bounds[1]) + 1].any()
        assert photons.photons == cube.events + cube.overflow_events - removed
