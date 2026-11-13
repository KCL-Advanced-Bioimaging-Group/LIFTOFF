"""Navigator matrices through production preview workers."""

# Tests inspect the panel data behind the matrix viewer.
# pylint: disable=protected-access

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pytestqt.qtbot import QtBot

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from tests.mosaic_fixture import mosaic_lif
from tests.test_reference_science import example_path


def _open_mosaic(
    source: Path, name: str, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> MainWindow:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1650, 1080)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=30000)
    items = [
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            d := window.block_list.item(row).data(Qt.ItemDataRole.UserRole),
            DatasetInfo,
        )
        and d.acquisition_name == name
    ]
    assert len(items) == 1
    window.select_block(items[0])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    return window


def _check_graph_toggle(window: MainWindow) -> None:
    """The default pools bins; separation only changes presentation."""
    plot = window.histogram
    button = plot.separate_tiles_button
    panels = list(plot.multichannel_panels or ())
    assert button.isVisible() and button.isEnabled()
    assert not button.isChecked()
    assert button.text() == "Separate graphs by tile"
    assert not button.geometry().intersects(
        window.combine_rois_checkbox.geometry()
    )
    graphs = plot.graph_panels()
    assert len(graphs) == 1
    expected = np.sum(
        [panel["values"] for panel in panels], axis=0, dtype=np.uint64
    )
    np.testing.assert_array_equal(graphs[0]["series"][0][1], expected)
    assert graphs[0]["photons"] == int(expected.sum())
    plot.repaint()
    assert len(plot._last_histogram_layout["panels"]) == 1
    plot.log_scale_button.click()
    assert plot.logarithmic_scale
    np.testing.assert_array_equal(
        plot.graph_panels()[0]["series"][0][1], expected
    )
    button.click()
    plot.repaint()
    assert len(plot._last_histogram_layout["panels"]) == 4
    assert plot.logarithmic_scale
    assert plot.graph_panels() == panels
    assert window.decode_worker is None
    button.click()
    plot.repaint()
    assert len(plot._last_histogram_layout["panels"]) == 1
    assert plot.logarithmic_scale
    plot.log_scale_button.setChecked(False)


@pytest.mark.parametrize(
    "real", [False, pytest.param(True, marks=pytest.mark.real_data)]
)
def test_mosaic_matrix(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch, real: bool
) -> None:
    """Show correct cells and keep a bottom-row ROI on its own tile."""
    source = (
        example_path("HCC1954 mS3-mitoPyr-ShadowR.lif")
        if real
        else mosaic_lif(tmp_path / "tiles.lif")
    )
    if source is None:
        pytest.skip("Optional Navigator mosaic is unavailable")
    window = _open_mosaic(
        source, "R1 (4)" if real else "Mosaic", qtbot, monkeypatch
    )
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) == 4
    assert [panel["dataset"].tile_index for panel in panels] == [0, 1, 3, 2]
    assert len({panel["cube"].source_dataset_key for panel in panels}) == 4
    assert len({panel["composite_x"] for panel in panels}) == 2
    assert len({panel["composite_y"] for panel in panels}) == 2
    assert "2 x 2 tiles" in window.fields["Dimensions"].text()
    assert not window.plane_controls.isVisible()
    _check_graph_toggle(window)
    if real:
        assert [
            panel["events"] + panel["cube"].overflow_events for panel in panels
        ] == [
            9167961,
            16303227,
            12144951,
            10354944,
        ]
        target = Path("validation_artifacts/screenshots/mosaic-R1-4.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        qtbot.wait(100)
        assert window.grab().save(str(target))
        window.histogram.separate_tiles_button.click()
        assert window.grab().save(
            str(target.with_name("mosaic-R1-4-separate-graphs.png"))
        )
        window.histogram.separate_tiles_button.click()
    else:
        layout = window.image.multichannel_mirror_layout[2]
        window.show_pixel(layout["x"], layout["header"])
        rendered = list(window.histogram.multichannel_panels or ())
        assert [
            int(np.asarray(panel["series"][0][1]).sum()) for panel in rendered
        ] == [0, 0, 24, 0]
        assert (
            int(window.histogram.graph_panels()[0]["series"][0][1].sum()) == 24
        )
        window.image.rois = [
            (
                layout["x"],
                layout["header"],
                layout["x"] + layout["width"],
                layout["header"] + layout["height"],
            )
        ]
        window.image.roi_colors = [QColor("#38bdf8")]
        window.image.activated_rois = {0}
        window._refresh_roi_histogram()
        rendered = list(window.histogram.multichannel_panels or ())
        sums = [
            int(np.asarray(panel["series"][0][1]).sum()) for panel in rendered
        ]
        assert sums == [0, 0, 144, 0]
        assert (
            int(window.histogram.graph_panels()[0]["series"][0][1].sum())
            == 144
        )
        assert (
            window.image.mirrored_roi_rectangles(window.image.rois[0])[0] == 2
        )
        assert not window.image.mirrored_roi_rectangles(window.image.rois[0])[
            1
        ]
        # Keep a region spanning multiple tiles on filter changes.
        assert window.image.image is not None
        window.image.rois = [
            (0, 0, window.image.image.width(), window.image.image.height())
        ]
        original = window.image.rois[0]
        window._refresh_roi_histogram()
        window.event_flags.raw_first.click()
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
        np.testing.assert_allclose(window.image.rois[0], original)
        rendered = list(window.histogram.multichannel_panels or ())
        assert [
            int(np.asarray(panel["series"][0][1]).sum()) for panel in rendered
        ] == [36, 72, 144, 108]
        assert (
            int(window.histogram.graph_panels()[0]["series"][0][1].sum())
            == 360
        )


def test_matrix_time_depth_detectors_and_rois(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Navigate T/Z and mirror ROIs only to the same spatial tile."""
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    window = _open_mosaic(
        mosaic_lif(tmp_path / "tiles.lif", times=2, depths=2, channels=2),
        "Mosaic",
        qtbot,
        monkeypatch,
    )
    window.pair_selector.set_selection(
        dataset.key for dataset in window.datasets
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.plane_controls.isVisible()
    assert window.plane_combo.count() == 5  # Four T/Z planes and overview.
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(3))
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.plane_combo.currentText() == "t002_z002"
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) == 8
    assert len({panel["composite_x"] for panel in panels}) == 4
    assert len({panel["composite_y"] for panel in panels}) == 2
    assert len(window.histogram.graph_panels()) == 2
    for graph, start in zip(
        window.histogram.graph_panels(), (0, 4), strict=True
    ):
        np.testing.assert_array_equal(
            graph["values"],
            np.sum(
                [panel["values"] for panel in panels[start : start + 4]],
                axis=0,
                dtype=np.uint64,
            ),
        )
    for panel in panels:
        dataset = panel["dataset"]
        assert dataset.tile_index is not None
        assert panel["events"] == 36 * (
            dataset.tile_index + 3 + dataset.channel_index
        )
    layout = window.image.multichannel_mirror_layout[2]
    window.image.rois = [
        (
            layout["x"],
            layout["header"],
            layout["x"] + layout["width"],
            layout["header"] + layout["height"],
        )
    ]
    window.image.roi_colors = [QColor("#38bdf8")]
    window.image.activated_rois = {0}
    window._refresh_roi_histogram()
    rendered = list(window.histogram.multichannel_panels or ())
    assert [int(np.asarray(p["series"][0][1]).sum()) for p in rendered] == [
        0,
        0,
        216,
        0,
        0,
        0,
        252,
        0,
    ]
    assert [
        int(graph["series"][0][1].sum())
        for graph in window.histogram.graph_panels()
    ] == [216, 252]
    window.histogram.separate_tiles_button.click()
    assert len(window.histogram.graph_panels()) == 8
    assert [
        index
        for index, _roi in window.image.mirrored_roi_rectangles(
            window.image.rois[0]
        )[1]
    ] == [6]
    window.pair_selector.set_selection([window.datasets[1].key])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.current_plane == 3
    assert window.image.activated_rois == {0}
    assert window.histogram.separate_tiles_button.isChecked()
    assert len(window.histogram.graph_panels()) == 4
    rendered = list(window.histogram.multichannel_panels or ())
    assert [int(np.asarray(p["series"][0][1]).sum()) for p in rendered] == [
        0,
        0,
        252,
        0,
    ]
    window.clear_data()
    assert not window.histogram.separate_tiles_button.isVisible()


def test_combined_graph_roi_union(
    tmp_path: Path, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pool ROIs across cells, counting shared pixels once."""
    window = _open_mosaic(
        mosaic_lif(tmp_path / "tiles.lif"), "Mosaic", qtbot, monkeypatch
    )
    first = window.image.multichannel_mirror_layout[0]
    assert window.image.image is not None
    window.image.rois = [
        (
            first["x"],
            first["header"],
            first["x"] + first["width"],
            first["header"] + first["height"],
        ),
        (0, 0, window.image.image.width(), window.image.image.height()),
    ]
    window.image.roi_colors = [QColor("#38bdf8"), QColor("#ff00ff")]
    window.image.activated_rois = {0, 1}
    window._refresh_roi_histogram()
    assert [
        int(values.sum())
        for _label, values, _color in window.histogram.graph_panels()[0][
            "series"
        ]
    ] == [36, 360]
    window.combine_rois_checkbox.click()
    graphs = window.histogram.graph_panels()
    assert len(graphs) == 1 and len(graphs[0]["series"]) == 1
    assert int(graphs[0]["series"][0][1].sum()) == 360
    window.histogram.separate_tiles_button.click()
    assert [
        int(graph["series"][0][1].sum())
        for graph in window.histogram.graph_panels()
    ] == [36, 72, 144, 108]
    window.histogram.separate_tiles_button.click()
    assert window.combine_rois_checkbox.isChecked()
    assert int(window.histogram.graph_panels()[0]["series"][0][1].sum()) == 360


def test_mosaic_export_preflight(tmp_path: Path, qtbot: QtBot) -> None:
    """Split export stays available when integration is declined."""
    dataset = scan_lif(mosaic_lif(tmp_path / "tiles.lif"))[0]
    dialog = IcsExportDialog([dataset], {})
    qtbot.addWidget(dialog)
    assert required_table_item(dialog.table, 1, 9).text() == "Ready"
    dialog.dimension_mode.setCurrentIndex(
        dialog.dimension_mode.findData("integrate")
    )
    assert required_table_item(dialog.table, 1, 9).text() == "Failed"
    assert (
        "keep tiles separate"
        in required_table_item(dialog.table, 1, 9).toolTip()
    )
    assert not (
        required_table_item(dialog.table, 1, 0).flags()
        & Qt.ItemFlag.ItemIsUserCheckable
    )
    dialog.dimension_mode.setCurrentIndex(
        dialog.dimension_mode.findData("split")
    )
    assert required_table_item(dialog.table, 1, 9).text() == "Ready"
    assert (
        required_table_item(dialog.table, 1, 0).flags()
        & Qt.ItemFlag.ItemIsUserCheckable
    )
