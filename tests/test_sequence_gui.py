"""Choice B presentation with production workers and scoped ROIs."""

# These component regressions inspect the decoded workspace state.
# pylint: disable=protected-access

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui import MainWindow
from tests.sequence_fixture import mixed_lif
from tests.test_reference_science import example_path


def test_excitation_emission_time_z_and_roi(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Navigation and comparison keep separate calibrated pair cubes."""
    source = mixed_lif(tmp_path / "mixed.lif")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(source)], "LIF files (*.lif)"),
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=10000)
    entries = [
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            window.block_list.item(row).data(Qt.ItemDataRole.UserRole),
            DatasetInfo,
        )
    ]
    assert len(entries) == 1
    window.select_block(entries[0])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.pair_selector.isVisible()
    assert window.pair_selector.headerItem().text(0) == "Excitation"
    assert window.pair_selector.headerItem().text(1) == "Emission"
    assert len(window.current_channel_group()) == 2
    assert window.pair_selector.topLevelItemCount() == 2
    assert (
        window.pair_selector.excitation_items[0].checkState(0)
        == Qt.CheckState.Checked
    )
    assert (
        window.pair_selector.excitation_items[1].checkState(0)
        == Qt.CheckState.Unchecked
    )
    assert all(
        not window.pair_selector.emission_enabled(key)
        for key in window.pair_selector.emission_items
        if "|s1|" in key
    )
    assert window._multichannel_channel_panels is not None
    assert {
        panel["dataset"].sequence_index
        for panel in window._multichannel_channel_panels
    } == {0}
    # Retain the selected T/Z plane across excitation changes.
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(3))
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.current_plane == 3
    window.pair_selector.set_selection(
        dataset.key
        for dataset in window.datasets
        if dataset.sequence_index == 1
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.current_plane == 3
    assert window.plane_combo.currentText() == "t002_z002"
    panels = window._multichannel_channel_panels
    assert panels is not None
    assert [panel["events"] for panel in panels] == [4, 8]
    assert {panel["dataset"].sequence_index for panel in panels} == {1}
    assert {panel["cube"].source_dataset_key for panel in panels} == {
        dataset.key for dataset in window.current_channel_group()
    }
    histogram_panels = list(
        getattr(window.histogram, "multichannel_panels", ()) or ()
    )
    assert histogram_panels
    assert all(
        "200.00 ps/bin" in panel["x_axis_label"] for panel in histogram_panels
    )
    window.pair_selector.set_selection([window.datasets[3].key])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.selected is not None
    assert window.selected.sequence_index == 1
    assert window.selected.detector_route == 1
    assert window.cube is not None and window.cube.events == 8
    assert window._multichannel_channel_panels is None
    window.pair_selector.set_selection(
        dataset.key for dataset in window.datasets
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) == 4
    assert [panel["events"] for panel in panels] == [24, 8, 4, 8]
    assert len({panel["cube"].source_dataset_key for panel in panels}) == 4
    # Mirrored ROI coordinates are applied to each pair's own counts.
    target = window.image.multichannel_mirror_layout[0]
    window.image.rois = [
        (
            target["x"],
            target["header"],
            target["x"] + target["width"] / 2,
            target["header"] + target["height"],
        )
    ]
    window.image.roi_colors = [QColor("#38bdf8")]
    window.image.activated_rois = {0}
    window._refresh_roi_histogram()
    histogram_panels = list(
        getattr(window.histogram, "multichannel_panels", ()) or ()
    )
    assert histogram_panels
    values = [panel["series"][0][1] for panel in histogram_panels]
    assert [int(value.sum()) for value in values] == [16, 8, 2, 4]
    assert all(
        np.array_equal(value, panel["cube"].counts[:, :, 0].sum(axis=1))
        for value, panel in zip(values, panels, strict=True)
    )
    snapshot = window._capture_active_roi_snapshot_2()
    assert snapshot is not None
    assert snapshot["items"][0]["sourceKey"] == panels[0]["dataset"].key
    # A retained ROI uses newly decoded counts in the next sequence.
    window.pair_selector.set_selection(
        dataset.key
        for dataset in window.datasets
        if dataset.sequence_index == 1
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.image.activated_rois == {0}
    histogram_panels = list(
        getattr(window.histogram, "multichannel_panels", ()) or ()
    )
    assert histogram_panels
    assert [
        int(panel["series"][0][1].sum()) for panel in histogram_panels
    ] == [2, 4]
    window.event_flags.raw_first.click()
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.image.activated_rois == {0}
    histogram_panels = list(
        getattr(window.histogram, "multichannel_panels", ()) or ()
    )
    assert [
        int(panel["series"][0][1].sum()) for panel in histogram_panels
    ] == [2, 2]
    window.clear_data()
    assert not window.pair_selector.isVisible()


@pytest.mark.real_data
@pytest.mark.parametrize("suffix", ["LACT+PYR1", "LACT+PYR2"])
def test_supplied_mixed_acquisition_gui(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    """Both supplied acquisitions open and switch excitation."""
    source = example_path("HCC_mScr-pyr+mTFP-lact.lif")
    if source is None:
        pytest.skip("Optional mixed-excitation LIF is unavailable")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1600, 1040)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=20000)
    entries = [
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            dataset := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and (dataset.acquisition_name or "").endswith(suffix)
    ]
    assert len(entries) == 1
    window.select_block(entries[0])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    totals = (
        [7058116, 1679644] if suffix == "LACT+PYR1" else [15994608, 108134341]
    )
    assert window.cube is not None
    assert window.cube.events + window.cube.overflow_events == totals[0]
    assert window.selected is not None and window.selected.sequence_index == 0
    assert (
        window.pair_selector.excitation_items[0].checkState(0)
        == Qt.CheckState.Checked
    )
    assert len(window.current_channel_group()) == 1
    screenshots = Path("validation_artifacts/screenshots")
    screenshots.mkdir(parents=True, exist_ok=True)
    qtbot.wait(50)
    assert window.grab().save(str(screenshots / f"sequence-{suffix}-1040.png"))
    window.pair_selector.excitation_items[0].setCheckState(
        0, Qt.CheckState.Unchecked
    )
    window.pair_selector.excitation_items[1].setCheckState(
        0, Qt.CheckState.Checked
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert window.cube is not None
    assert window.cube.events + window.cube.overflow_events == totals[1]
    assert window.selected is not None and window.selected.detector_route == 0
    assert window.selected.sequence_index == 1
    if suffix == "LACT+PYR1":
        window.pair_selector.excitation_items[0].setCheckState(
            0, Qt.CheckState.Checked
        )
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
        panels = window._multichannel_channel_panels
        assert panels is not None
        assert [
            panel["events"] + panel["cube"].overflow_events for panel in panels
        ] == totals
        assert len(window.histogram.multichannel_panels or ()) == 2
        assert all(
            "Ex." in panel["title"] and "Em." in panel["title"]
            for panel in window.histogram.multichannel_panels or ()
        )
        qtbot.wait(50)
        assert window.grab().save(
            str(screenshots / "pair-table-LACT+PYR1-comparison.png")
        )
        assert window.pair_selector.grab().save(
            str(screenshots / "aligned-excitation-emission-table.png")
        )


def test_arbitrary_pairs_and_empty_selection(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compare a subset across sequences and clear unselected data."""
    source = mixed_lif(tmp_path / "mixed.lif")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=10000)
    item = window.block_list.item(1)
    window.select_block(item)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(3))
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    window.pair_selector.set_selection(
        [window.datasets[0].key, window.datasets[3].key]
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    panels = window._multichannel_channel_panels
    assert panels is not None
    assert [panel["events"] for panel in panels] == [24, 8]
    assert [panel["dataset"].channel_index for panel in panels] == [0, 3]
    assert window.current_plane == 3
    histogram_panels = list(
        getattr(window.histogram, "multichannel_panels", ()) or ()
    )
    assert all(
        "Ex." in panel["title"]
        and "Em." in panel["title"]
        and "repeat" not in panel["title"]
        and "Seq." not in panel["title"]
        for panel in histogram_panels
    )
    window.pair_selector.set_selection(())
    assert window.decode_worker is None
    assert window.cube is None and window.image.image is None
    assert window.histogram.multichannel_panels is None
    assert "No recorded pairs" in window.fields["Photons"].text()
    window.event_flags.raw_first.click()
    assert window.decode_worker is None and window.image.image is None
    window.select_block(item)
    assert (
        window.decode_worker is None and window.current_channel_group() == ()
    )
    window.pair_selector.excitation_items[0].setCheckState(
        0, Qt.CheckState.Checked
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=10000)
    assert window.cube is not None and window.cube.events == 16
    assert window.current_plane == 3


@pytest.mark.real_data
def test_partial_series013_thumbnail(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Show available preview images from a partial timelapse."""
    source = example_path("HCC_mScr-pyr+mTFP-lact.lif")
    if source is None:
        pytest.skip("Optional partial timelapse is unavailable")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1380, 930)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=20000)
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            dataset := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and dataset.acquisition_name == "Series013"
    )
    dataset = item.data(Qt.ItemDataRole.UserRole)
    assert dataset.t_count == 32
    assert dataset.thumbnail is not None and not item.icon().isNull()
    assert dataset.total_photons is dataset.intensity_start is None
    assert np.count_nonzero(np.asarray(dataset.thumbnail)) > 100
    window.block_list.scrollToItem(item)
    window.select_block(item)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert window.cube is not None and window.cube.events > 0
    assert window.cube.reference_events is None
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(31))
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert window.cube is not None and window.cube.events > 0
    assert window.cube.decoded_rows == 2328
    assert window.plane_combo.currentText() == "t032"
    assert not item.icon().isNull()
    qtbot.wait(50)
    output = Path("validation_artifacts/screenshots")
    output.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(
        str(output / "pair-table-Series013-thumbnail.png")
    )
