"""All supplied acquisitions through real preview and export workers."""

# Verify the scientific arrays behind the rendered workspace.
# pylint: disable=protected-access

import json

import numpy as np
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMessageBox,
    QPushButton,
)

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from leica_flim_converter.gui_ptu_dialog import PtuExportDialog
from tests.multichannel_mosaic_fixture import multichannel_mosaic_lif
from tests.test_mosaic_gui import _open_mosaic
from tests.test_mosaic_hover import _move_to_image
from tests.test_reference_science import example_path
from tests.test_timing_real import FILES


def _assert_hover(window):
    panels = window._multichannel_channel_panels
    if not panels:
        cube = window.cube
        assert cube is not None
        x, y = _move_to_image(window, 10.5, 12.5)
        np.testing.assert_array_equal(
            window.histogram.values, cube.pixel(x, y)
        )
        return
    for target in panels:
        x, y = _move_to_image(
            window,
            target["composite_x"] + target["dataset"].width / 2,
            target.get("composite_y", 0)
            + target["header_height"]
            + target["dataset"].height / 2,
        )
        local_x = x - target["composite_x"]
        local_y = y - target.get("composite_y", 0) - target["header_height"]
        assert "pixel (" in window.histogram.multichannel_scope
        for source, graph in zip(
            panels, window.histogram.multichannel_panels, strict=True
        ):
            same_tile = (
                source["dataset"].tile_index == target["dataset"].tile_index
            )
            sx = int(
                (local_x + 0.5)
                / target["dataset"].width
                * source["dataset"].width
            )
            sy = int(
                (local_y + 0.5)
                / target["dataset"].height
                * source["dataset"].height
            )
            expected = (
                source["cube"].pixel(sx, sy)
                if same_tile
                else np.zeros_like(source["values"])
            )
            np.testing.assert_array_equal(graph["series"][0][1], expected)


def _exercise_regions(window):
    panels = window._multichannel_channel_panels
    first = panels[0] if panels else None
    x = first["composite_x"] if first else 0
    y = first.get("composite_y", 0) + first["header_height"] if first else 0
    window.image.rois = [
        (x + 1, y + 1, x + 6, y + 5),
        (x + 3, y + 2, x + 8, y + 7),
    ]
    window.image.roi_colors = [QColor("#38bdf8"), QColor("#ff8c42")]
    window.image.activated_rois = {0, 1}
    window._refresh_roi_histogram()
    window.combine_rois_checkbox.click()
    assert window.combine_rois_checkbox.isChecked()
    window.image.repaint()
    window.histogram.repaint()
    assert window.image.activated_rois == {0, 1}
    window.clear_roi_button.click()
    assert not window.image.rois
    assert not window.image.activated_rois


def _exercise_view(window, qtbot):
    _assert_hover(window)
    QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
    _exercise_regions(window)
    window.image._zoom_at(window.image.rect().center(), 2)
    assert window.image.view_zoom == 2
    window.image.reset_image_view()
    window.image.repaint()
    window.histogram.repaint()
    assert window.histogram._last_histogram_layout
    if window.selected.preview_plane_count > 1:
        for plane in (0, window.selected.preview_plane_count - 1):
            window.plane_combo.setCurrentIndex(
                window.plane_combo.findData(plane)
            )
            qtbot.waitUntil(
                lambda: window.decode_worker is None, timeout=180000
            )
            assert window.current_plane == plane
            _assert_hover(window)
            QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))


@pytest.mark.real_data
@pytest.mark.parametrize("filename", FILES)
def test_every_supplied_acquisition(tmp_path, qtbot, monkeypatch, filename):
    """Render every acquisition, every channel and both ends of T/Z."""
    source = example_path(filename)
    if source is None:
        pytest.skip("Optional supplied acquisition is unavailable")
    catalogue = scan_lif(source)
    name = catalogue[0].acquisition_name
    assert name is not None
    window = _open_mosaic(source, name, qtbot, monkeypatch)
    groups = list(window._channel_groups_by_first_key.values())
    evidence = tmp_path / "viewer-results.jsonl"
    for group in groups:
        item = next(
            window.block_list.item(row)
            for row in range(window.block_list.count())
            if isinstance(
                d := window.block_list.item(row).data(
                    Qt.ItemDataRole.UserRole
                ),
                DatasetInfo,
            )
            and d.key == group[0].key
        )
        window.select_block(item)
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=180000)
        invalid = any(
            d.repetition_storage_model == "unresolved" for d in group
        )
        if invalid:
            assert window.cube is None
            assert not window._multichannel_channel_panels
            assert any(d.key in window.decode_failures for d in group)
        else:
            window.pair_selector.set_selection(d.key for d in group)
            qtbot.waitUntil(
                lambda: window.decode_worker is None, timeout=180000
            )
            assert window.status_label.text().startswith("Ready:")
            assert window.image.image is not None
            _exercise_view(window, qtbot)
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "datasetKeys": [d.key for d in group],
                        "handledInvalid": invalid,
                        "passed": True,
                    }
                )
                + "\n"
            )
    window.clear_data()
    assert not window.datasets
    assert not window.loaded_sources
    assert window.image.image is None


@pytest.mark.parametrize("format_name", ["ics", "ptu"])
def test_gui_export_workers(tmp_path, qtbot, monkeypatch, format_name):
    """Export synthetic tile/channel/T/Z data through the GUI worker."""
    source = multichannel_mosaic_lif(tmp_path / "matrix.lif")
    window = _open_mosaic(
        source, "Synthetic multichannel mosaic", qtbot, monkeypatch
    )
    dialog_type = IcsExportDialog if format_name == "ics" else PtuExportDialog
    destination = tmp_path / "output"
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args: messages.append(args[2])
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args: messages.append(args[2])
    )

    def accept(dialog):
        dialog.destination.setText(str(destination))
        next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "Select All"
        ).click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dialog_type, "exec", accept)
    if format_name == "ics":
        window.export_ics()
    else:
        window.export_ptu()
    qtbot.waitUntil(lambda: window.export_worker is None, timeout=30000)
    assert "64 exported, 0 skipped, 0 failed" in window.status_label.text()
    assert len(messages) == 1 and "Failed: 0" in messages[0]
    outputs = list(destination.rglob(f"*.{format_name}"))
    assert len(outputs) == 64
    for path in outputs:
        if format_name == "ics":
            assert read_ics(path).counts.sum() > 0
        else:
            assert inspect_ptu(path).photons > 0
    assert window.open_button.isEnabled()
    assert not window.cancel_button.isEnabled()


@pytest.mark.real_data
def test_all_sources_share_workspace(qtbot, monkeypatch):
    """Import all examples together and preflight every export row."""
    paths = [
        path for name in FILES if (path := example_path(name)) is not None
    ]
    if len(paths) != 9:
        pytest.skip("The complete optional example set is unavailable")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(path) for path in paths], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1650, 1080)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=60000)
    assert len(window.loaded_sources) == 9
    assert len(window.datasets) == len({d.key for d in window.datasets}) == 121
    window.open_button.click()
    assert window.scan_worker is None
    assert len(window.datasets) == 121
    assert "already open" in window.status_label.text()
    for dialog_type in (IcsExportDialog, PtuExportDialog):
        dialog = dialog_type(window.datasets, {})
        qtbot.addWidget(dialog)
        dialog.resize(1500, 900)
        dialog.show()
        seen = set()
        for row, target in enumerate(dialog.row_targets):
            if target is None:
                continue
            dataset, _plane = target
            seen.add(dataset.key)
            expected = (
                "Failed"
                if dataset.repetition_storage_model == "unresolved"
                else "Ready"
            )
            assert required_table_item(dialog.table, row, 9).text() == expected
        assert len(seen) == 121
        dialog.close()
    window.clear_data()
    assert not window.loaded_sources and not window.datasets
