"""Mixed-source selection through production GUI workers."""

# Component assertions inspect the decoded comparison panels.
# pylint: disable=protected-access

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.gui import MainWindow
from tests.compressed_fixture import mixed_compressed_lif
from tests.test_reference_science import example_path


@pytest.mark.parametrize(
    "real", [False, pytest.param(True, marks=pytest.mark.real_data)]
)
def test_mixed_source_comparison(
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    real: bool,
) -> None:
    """Select both sources with separate images and decays."""
    if real:
        source = example_path(
            "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"
        )
        if source is None:
            pytest.skip("Optional mixed-source LIF is unavailable")
    else:
        source = mixed_compressed_lif(tmp_path / "mixed.lif")
    name = "paneth_ctx555_1" if real else "Mixed compressed"
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
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=30000)
    entries = [
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            dataset := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and dataset.acquisition_name == name
    ]
    assert len(entries) == 1
    window.select_block(entries[0])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.pair_selector.topLevelItemCount() == 2
    pairs = [d for d in window.datasets if d.acquisition_name == name]
    assert [d.excitation_label for d in pairs] == [
        "555 nm (WLL)",
        "740 nm (MP)",
    ]
    window.pair_selector.set_selection([pairs[1].key])
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    assert window.selected is not None
    assert window.selected.detector_name == "HyD NDD 2"
    assert window.cube is not None and window.cube.events > 0
    window.pair_selector.set_selection(d.key for d in pairs)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=30000)
    panels = window._multichannel_channel_panels
    assert panels is not None and len(panels) == 2
    assert [p["dataset"].detector_name for p in panels] == [
        "HyD X 3",
        "HyD NDD 2",
    ]
    assert len({p["cube"].source_dataset_key for p in panels}) == 2
    assert all(p["events"] > 0 for p in panels)
    if real:
        assert [d.emission_filter_band for d in pairs] == [
            "566 - 630 nm",
            "410 - 490 nm",
        ]
        assert "566 - 630 nm" in window.pair_selector.emission_items[
            pairs[0].key
        ].text(1)
        assert "565.5957" not in entries[0].text()
        screenshot = Path(
            "validation_artifacts/screenshots/mixed-light-sources-paneth.png"
        )
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        qtbot.wait(100)
        assert window.grab().save(str(screenshot))
