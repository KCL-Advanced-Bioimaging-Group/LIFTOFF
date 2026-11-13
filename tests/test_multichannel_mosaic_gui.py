"""Channel/tile interactions in the production Qt workspace."""

# Inspect decoded scientific arrays and dispatch native canvas events.
# pylint: disable=protected-access

from itertools import product

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMessageBox

from tests.multichannel_mosaic_fixture import (
    MosaicSpec,
    expected_cube,
    multichannel_mosaic_lif,
)
from tests.test_mosaic_gui import _open_mosaic
from tests.test_mosaic_hover import _move_cursor, _move_to_image
from tests.test_pair_selector import click_checkbox


def _open_matrix(tmp_path, qtbot, monkeypatch, mode="SequentialFrame"):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes
    )
    window = _open_mosaic(
        multichannel_mosaic_lif(
            tmp_path / "matrix.lif", MosaicSpec(mode=mode)
        ),
        "Synthetic multichannel mosaic",
        qtbot,
        monkeypatch,
    )
    window.pair_selector.set_selection(d.key for d in window.datasets)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    return window


def _assert_defaults(window):
    assert window.histogram.multichannel_scope == "All Pixels"
    panels = window._multichannel_channel_panels
    assert panels is not None
    graphs = window.histogram.graph_panels()
    if window.histogram.separate_tiles_button.isChecked():
        expected = [panel["values"] for panel in panels]
    else:
        keys = list(dict.fromkeys(p["dataset"].pair_key for p in panels))
        expected = [
            np.sum(
                [p["values"] for p in panels if p["dataset"].pair_key == key],
                axis=0,
                dtype=np.uint64,
            )
            for key in keys
        ]
    assert len(graphs) == len(expected)
    for graph, values in zip(graphs, expected, strict=True):
        actual = (
            graph["series"][0][1] if "series" in graph else graph["values"]
        )
        np.testing.assert_array_equal(actual, values)


def _assert_pixel(window, target):
    x, y = _move_to_image(
        window,
        target["composite_x"] + 2.5,
        target["composite_y"] + target["header_height"] + 1.5,
    )
    local_x = x - target["composite_x"]
    local_y = y - target["composite_y"] - target["header_height"]
    assert "pixel (" in window.histogram.multichannel_scope
    panels = window._multichannel_channel_panels
    assert panels is not None
    graphs = window.histogram.graph_panels()
    separate = window.histogram.separate_tiles_button.isChecked()
    expected = [
        panel["cube"].pixel(local_x, local_y)
        if panel["dataset"].tile_index == target["dataset"].tile_index
        else panel["values"]
        if separate
        else np.zeros_like(panel["values"])
        for panel in panels
    ]
    if not separate:
        keys = list(dict.fromkeys(p["dataset"].pair_key for p in panels))
        expected = [
            np.sum(
                [
                    values
                    for source, values in zip(panels, expected, strict=True)
                    if source["dataset"].pair_key == key
                ],
                axis=0,
                dtype=np.uint64,
            )
            for key in keys
        ]
    for graph, values in zip(graphs, expected, strict=True):
        np.testing.assert_array_equal(graph["series"][0][1], values)


@pytest.mark.parametrize("mode", ["SequentialFrame", "SequentialStack"])
def test_matrix_channels_planes_and_hover(tmp_path, qtbot, monkeypatch, mode):
    """Inspect channels/tiles, navigate T/Z and restore defaults."""
    window = _open_matrix(tmp_path, qtbot, monkeypatch, mode)
    assert window.plane_combo.count() == 5
    for plane, mask in product((None, 0, 1, 2, 3), (256, 512, 1024)):
        window.plane_combo.setCurrentIndex(window.plane_combo.findData(plane))
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
        window.event_flags.set_mask(mask, emit=True)
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
        panels = window._multichannel_channel_panels
        assert panels is not None and len(panels) == 16
        for panel in panels:
            dataset = panel["dataset"]
            sequence, route = divmod(dataset.channel_index, 2)
            identities = (
                product(range(2), range(2))
                if plane is None
                else [dataset.plane_indices(plane)]
            )
            expected = sum(
                (
                    expected_cube(
                        MosaicSpec(),
                        (t, dataset.tile_index, z, sequence, route),
                        mask,
                    )
                    for t, z in identities
                )
            )
            np.testing.assert_array_equal(panel["cube"].counts, expected)
        for separate in (False, True):
            window.histogram.separate_tiles_button.setChecked(separate)
            _assert_defaults(window)
            for target in panels:
                _assert_pixel(window, target)
                _move_to_image(
                    window,
                    target["composite_x"] + 2.5,
                    target["composite_y"] + 0.5,
                )
                _assert_defaults(window)
            _assert_pixel(window, panels[-1])
            QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
            _assert_defaults(window)
    # The same coordinate path must work after zooming and panning.
    window.image.view_zoom = 2
    window.image.view_center_x = 0.75
    window.image.view_center_y = 0.7
    panels = window._multichannel_channel_panels
    assert panels is not None
    _assert_pixel(window, panels[-1])
    _move_cursor(window.image, QPoint(1, 1))
    _assert_defaults(window)


def _activate(window, rectangles):
    window.image.rois = rectangles
    window.image.roi_colors = [QColor("#38bdf8")] * len(rectangles)
    window.image.activated_rois = set(range(len(rectangles)))
    window._refresh_roi_histogram()


def test_matrix_channel_controls(tmp_path, qtbot, monkeypatch):
    """Change channel choices without losing T/Z or hover."""
    window = _open_matrix(tmp_path, qtbot, monkeypatch)
    tree = window.pair_selector
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(3))
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    click_checkbox(tree, tree.excitation_items[0], 0, qtbot)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert len(window._multichannel_channel_panels or ()) == 8
    assert window.current_plane == 3
    _assert_defaults(window)
    panels = window._multichannel_channel_panels
    assert panels is not None
    _assert_pixel(window, panels[-1])
    click_checkbox(tree, tree.emission_items[window.datasets[3].key], 1, qtbot)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert len(window._multichannel_channel_panels or ()) == 4
    _assert_defaults(window)
    for separate in (False, True):
        window.histogram.separate_tiles_button.setChecked(separate)
        panels = window._multichannel_channel_panels
        assert panels is not None
        _assert_pixel(window, panels[-1])
        QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
    click_checkbox(tree, tree.excitation_items[1], 0, qtbot)
    assert window.image.image is None
    assert not window.histogram.multichannel_panels
    click_checkbox(tree, tree.excitation_items[0], 0, qtbot)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert len(window._multichannel_channel_panels or ()) == 8
    assert window.current_plane == 3
    _assert_defaults(window)


@pytest.mark.parametrize("region", ["pixel", "row", "column", "matrix"])
def test_matrix_roi_retention(tmp_path, qtbot, monkeypatch, region):
    """Retain exactly the same bottom-row pixels when headers change."""
    window = _open_matrix(tmp_path, qtbot, monkeypatch)
    panels = window._multichannel_channel_panels
    assert panels is not None
    target = panels[2]
    x, y = (
        target["composite_x"],
        target["composite_y"] + target["header_height"],
    )
    first = panels[0]
    rectangles = {
        "pixel": (x + 1, y + 1, x + 4, y + 3),
        "row": (x + 1, y + 1, panels[3]["composite_x"] + 4, y + 3),
        "column": (x + 1, first["header_height"] + 2, x + 4, y + 3),
        "matrix": (
            x + 1,
            first["header_height"] + 2,
            panels[3]["composite_x"] + 4,
            y + 3,
        ),
    }
    _activate(window, [rectangles[region]])
    expected = [
        p["series"][0][1].copy() for p in window.histogram.graph_panels()
    ]
    assert all(int(values.sum()) > 0 for values in expected)
    window.pair_selector.set_selection([window.datasets[3].key])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.image.activated_rois == {0}
    np.testing.assert_array_equal(
        window.histogram.graph_panels()[0]["series"][0][1], expected[3]
    )
    window.pair_selector.set_selection(d.key for d in window.datasets)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    for graph, values in zip(
        window.histogram.graph_panels(), expected, strict=True
    ):
        np.testing.assert_array_equal(graph["series"][0][1], values)
    _assert_pixel_roi_priority(window)


def _assert_pixel_roi_priority(window):
    values = [
        g["series"][0][1].copy() for g in window.histogram.graph_panels()
    ]
    target = window._multichannel_channel_panels[-1]
    _move_to_image(
        window,
        target["composite_x"] + 2.5,
        target["composite_y"] + target["header_height"] + 1.5,
    )
    assert window.histogram.multichannel_scope == "Activated ROIs"
    for graph, expected in zip(
        window.histogram.graph_panels(), values, strict=True
    ):
        np.testing.assert_array_equal(graph["series"][0][1], expected)


def test_matrix_cross_tile_roi_mirroring(tmp_path, qtbot, monkeypatch):
    """Mirror each selected tile piece to the other channels."""
    window = _open_matrix(tmp_path, qtbot, monkeypatch)
    panels = window._multichannel_channel_panels
    assert panels is not None
    target, next_tile = panels[0], panels[1]
    x, y = target["composite_x"], target["header_height"]
    roi = (x + 2, y + 1, next_tile["composite_x"] + 3, y + 4)
    _activate(window, [roi, (x + 3, y + 2, x + 5, y + 3)])
    owner, mirrors = window.image.mirrored_roi_rectangles(roi)
    assert owner in (0, 1)
    assert {index for index, _rect in mirrors} == {4, 5, 8, 9, 12, 13}
    window.combine_rois_checkbox.click()
    for pair, graph in enumerate(window.histogram.graph_panels()):
        first, second = panels[pair * 4], panels[pair * 4 + 1]
        expected = first["cube"].counts[:, 1:4, 2:].sum(axis=(1, 2)) + second[
            "cube"
        ].counts[:, 1:4, :3].sum(axis=(1, 2))
        np.testing.assert_array_equal(graph["series"][0][1], expected)
