"""The supplied interrupted WLL/MP Z-stack must remain recoverable."""

# Inspect the scientific arrays behind the production Qt viewer.
# pylint: disable=protected-access

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from leica_flim_converter.gui_ptu_dialog import PtuExportDialog
from leica_flim_converter.native_decoder import NativePreparedDecoder
from tests.test_mosaic_gui import _open_mosaic
from tests.test_reference_science import example_path
from tests.test_stress_workspace import _assert_hover, _exercise_regions

SOURCE_NAME = "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"


@pytest.mark.real_data
def test_real_partial_stack_planes():
    """Read every recorded plane and verify its reference identity."""
    source = example_path(SOURCE_NAME)
    if source is None:
        pytest.skip("Optional collaborator LIF is unavailable")
    datasets = [
        d for d in scan_lif(source) if d.acquisition_name == "paneth_ctx555_5"
    ]
    assert len(datasets) == 2
    for dataset in datasets:
        assert dataset.z_count == dataset.declared_plane_count == 12
        assert dataset.plane_count == dataset.frame_count == 10
        assert dataset.repetition_storage_model == "in-row-line-accumulation"
        with NativePreparedDecoder(dataset) as prepared:
            for plane in range(10):
                cube = prepared.decode_plane(
                    plane, bins=32, threads=4, event_flag_mask=15
                )
                assert dataset.plane_row_range(plane) == (plane * 512, 512)
                assert dataset.plane_indices(plane) == (0, plane)
                assert cube.reference_events is not None
                assert cube.reference_events > 0
                assert cube.spatial_alignment_correlation is not None
                assert cube.spatial_alignment_correlation > 0.99
                assert cube.spatial_transform == "identity"
        with pytest.raises(IndexError):
            dataset.plane_row_range(10)


@pytest.mark.real_data
def test_real_partial_stack_viewer(tmp_path, qtbot, monkeypatch):
    """Navigate all depths in both channels, hover and draw regions."""
    source = example_path(SOURCE_NAME)
    if source is None:
        pytest.skip("Optional collaborator LIF is unavailable")
    window = _open_mosaic(source, "paneth_ctx555_5", qtbot, monkeypatch)
    assert "10 of 12 planes recorded" in window.fields["Dimensions"].text()
    assert window.cube is not None
    assert window.plane_combo.count() == 11  # Overview plus ten real planes.
    group = list(window.current_acquisition_group())
    assert len(group) == 2
    window.pair_selector.set_selection(d.key for d in group)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) == 2
    for mask in (7, 3, 1):
        window.event_flags.set_mask(mask, emit=True)
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=120000)
        for plane in range(10):
            window.plane_combo.setCurrentIndex(
                window.plane_combo.findData(plane)
            )
            qtbot.waitUntil(
                lambda: window.decode_worker is None, timeout=120000
            )
            assert window.current_plane == plane
            assert window.status_label.text().startswith("Ready:")
            panels = window._multichannel_channel_panels
            assert panels is not None and len(panels) == 2
            assert all(
                panel["cube"].linear_plane == plane
                and panel["cube"].events > 0
                for panel in panels
            )
            _assert_hover(window)
    _exercise_regions(window)
    assert window.grab().save(str(tmp_path / "partial-stack-viewer.png"))
    for dialog_type in (IcsExportDialog, PtuExportDialog):
        dialog = dialog_type(group, {})
        qtbot.addWidget(dialog)
        for dataset in group:
            dialog.set_axis_mode(dataset, "z", True)
        represented = set()
        for row, target in enumerate(dialog.row_targets):
            if target is not None:
                dataset, plane = target
                represented.add((dataset.key, plane))
                assert required_table_item(dialog.table, row, 9).text() == (
                    "Ready"
                )
        assert represented == {
            (dataset.key, plane) for dataset in group for plane in range(10)
        }
        dialog.close()
    assert not window.decode_failures
    assert np.all(panels[0]["values"] >= 0)
