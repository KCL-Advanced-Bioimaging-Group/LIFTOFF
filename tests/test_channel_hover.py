"""Pixel inspection through real mouse events in channel comparisons."""

# Exercise the decoded panel state and production image coordinates.
# pylint: disable=protected-access

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.compressed_fixture import mixed_compressed_lif
from tests.sequence_fixture import mixed_lif
from tests.test_mosaic_gui import _open_mosaic
from tests.test_mosaic_hover import _move_to_image
from tests.test_reference_science import example_path


@pytest.mark.parametrize("storage", ["compressed", "lmsraw"])
def test_comparison_pixel_hover(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    storage: str,
) -> None:
    """Inspect matching pixels and restore defaults in both formats."""
    make = mixed_compressed_lif if storage == "compressed" else mixed_lif
    window = _open_mosaic(
        make(tmp_path / "comparison.lif"),
        "Mixed compressed" if storage == "compressed" else "Mixed",
        qtbot,
        monkeypatch,
    )
    window.pair_selector.set_selection(d.key for d in window.datasets)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) >= 2
    assert window.cube is None
    excluded = sum(panel["cube"].overflow_events for panel in panels)
    assert (
        f"excludes {excluded:,} selected photons"
        in window.fields["Histogram cube"].toolTip()
    )
    if excluded:
        assert (
            f"{excluded:,} outside arrival window"
            in window.status_label.text()
        )
    for target in panels:
        x = target["composite_x"] + 0.5
        y = target["header_height"] + 0.5
        _move_to_image(window, x, y)
        assert "pixel (" in window.histogram.multichannel_scope.lower()
        for source, graph in zip(
            panels, window.histogram.graph_panels(), strict=True
        ):
            np.testing.assert_array_equal(
                graph["series"][0][1], source["cube"].pixel(0, 0)
            )
        _move_to_image(window, x, 0.5)
        assert window.histogram.multichannel_scope == "All Pixels"
        for source, graph in zip(
            panels, window.histogram.graph_panels(), strict=True
        ):
            np.testing.assert_array_equal(
                graph["series"][0][1], source["values"]
            )
    _move_to_image(
        window,
        panels[0]["composite_x"] + 0.5,
        panels[0]["header_height"] + 0.5,
    )
    QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
    assert window.histogram.multichannel_scope == "All Pixels"
    # Activated regions take priority over transient inspection.
    target = panels[0]
    window.image.rois = [
        (
            target["composite_x"],
            target["header_height"],
            target["composite_x"] + 1,
            target["header_height"] + 1,
        )
    ]
    window.image.roi_colors = [QColor("#38bdf8")]
    window.image.activated_rois = {0}
    window._refresh_roi_histogram()
    expected = [
        g["series"][0][1].copy() for g in window.histogram.graph_panels()
    ]
    _move_to_image(
        window, target["composite_x"] + 0.5, target["header_height"] + 0.5
    )
    assert window.histogram.multichannel_scope == "Activated ROIs"
    for graph, values in zip(
        window.histogram.graph_panels(), expected, strict=True
    ):
        np.testing.assert_array_equal(graph["series"][0][1], values)


@pytest.mark.real_data
def test_real_comparison_hover(tmp_path, qtbot, monkeypatch):
    """Inspect the collaborator's WLL/MP scan."""
    source = example_path(
        "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"
    )
    if source is None:
        pytest.skip("Optional collaborator data is unavailable")
    name = "paneth_ctx555_1"
    window = _open_mosaic(source, name, qtbot, monkeypatch)
    window.pair_selector.set_selection(
        d.key for d in window.datasets if d.acquisition_name == name
    )
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) >= 2
    for target in panels:
        point = _move_to_image(
            window,
            target["composite_x"] + target["dataset"].width / 2,
            target["header_height"] + target["dataset"].height / 2,
        )
        local_x = point[0] - target["composite_x"]
        local_y = point[1] - target["header_height"]
        for panel, graph in zip(
            panels, window.histogram.graph_panels(), strict=True
        ):
            x = int(
                (local_x + 0.5)
                / target["dataset"].width
                * panel["dataset"].width
            )
            y = int(
                (local_y + 0.5)
                / target["dataset"].height
                * panel["dataset"].height
            )
            np.testing.assert_array_equal(
                graph["series"][0][1], panel["cube"].pixel(x, y)
            )
    QApplication.sendEvent(window.image, QEvent(QEvent.Type.Leave))
    assert window.histogram.multichannel_scope == "All Pixels"
    screenshot = tmp_path / "comparison-hover.png"
    assert window.grab().save(str(screenshot))
