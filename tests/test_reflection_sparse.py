"""Regression for the sparse Series003 bead acquisition."""

# Verify source ownership, summed curves and dashed overlays.
# pylint: disable=protected-access

import os
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import Qt

from leica_flim_converter import gui_reflection
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.reflection_processing import corrected_counts
from tests.test_reflection_gui import _rectangle, open_example_workspace


def _assert_repair_visible(plot, monkeypatch, bounds, mode):
    """Check the repair style and pixels inside the interval."""
    renderer = (
        "_draw_simulated_counts"
        if mode == "simulate"
        else "_draw_histogram_curves"
    )
    draw = Mock(wraps=getattr(gui_reflection, renderer))
    monkeypatch.setattr(gui_reflection, renderer, draw)
    plot.log_scale_button.setChecked(True)
    image = plot.grab().toImage()
    draw.assert_called()
    if mode == "simulate":
        assert draw.call_args.args[-1] == bounds
    else:
        assert draw.call_args.kwargs["line_style"] == Qt.PenStyle.DashLine
    left, top, right, bottom = _rectangle(plot)
    x0 = round(left + bounds[0] / 132 * (right - left)) + 2
    x1 = round(left + bounds[1] / 132 * (right - left)) - 2
    colors = [
        image.pixelColor(x, y)
        for x in range(x0, x1)
        for y in range(round(top) + 2, round(bottom) - 2)
    ]
    assert any(color.blue() > color.red() + 30 for color in colors)


@pytest.mark.real_data
@pytest.mark.parametrize("mode,index", [("interpolate", 1), ("simulate", 2)])
def test_sparse_beads_graph_and_ics(qtbot, monkeypatch, tmp_path, mode, index):
    """The supplied sparse image shows the same repair stored in ICS."""
    configured = os.environ.get("LEICA_REFLECTION_SPARSE_LIF")
    if not configured or not Path(configured).is_file():
        pytest.skip("Set LEICA_REFLECTION_SPARSE_LIF to N1Tau1.7ns.lif")
    window = open_example_workspace(
        qtbot,
        monkeypatch,
        source=Path(configured),
        acquisition_name="Series003",
        single_event=False,
    )
    original = window.cube
    assert original is not None and original.events == 718543
    plot = window.histogram
    plot.reflection.detect_button.click()
    bounds = next(iter(plot.reflection.regions.values()))
    assert bounds == (76, 83)
    window.reflection_filter.mode.setCurrentIndex(index)
    window.reflection_filter.checkbox.click()
    derived = window.cube
    assert derived is not None and derived is not original
    assert np.isfinite(derived.counts).all()
    raw_total = original.counts.sum((1, 2), dtype=np.uint64)
    expected = corrected_counts(raw_total, bounds, "interpolate")
    if mode == "interpolate":
        np.testing.assert_allclose(plot.series[0][1], expected, rtol=1e-12)
    else:
        mean = expected[76:84].sum()
        assert abs(derived.counts[76:84].sum() - mean) < 6 * np.sqrt(mean)
        np.testing.assert_array_equal(derived.counts, np.floor(derived.counts))
    np.testing.assert_array_equal(
        plot.series[0][1], derived.counts.sum((1, 2))
    )
    _assert_repair_visible(plot, monkeypatch, bounds, mode)
    artifact = Path(
        f"validation_artifacts/reflection-sparse/Series003-{mode}.png"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(artifact))
    dataset = window.selected
    assert dataset is not None
    result = export_ics_blocks(
        [dataset],
        tmp_path,
        IcsExportOptions(
            bins=None,
            compression="gzip",
            event_flag_mask=7,
            reflection_windows=window.reflection_filter.export_windows(),
        ),
        cached_cubes={dataset.key: original},
        plane_selection={dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    output = read_ics(Path(result["path"])).counts
    if mode == "interpolate":
        assert output.dtype == np.float32
        np.testing.assert_array_equal(
            output, derived.counts.astype(np.float32)
        )
    else:
        assert output.dtype.kind == "u"
        np.testing.assert_array_equal(output, derived.counts)
    window.reflection_filter.checkbox.click()
    assert window.cube is original
