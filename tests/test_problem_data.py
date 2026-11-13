"""Regress compressed images and all supplied timelapse PTU exports."""

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.decay import native_period_bins
from leica_flim_converter.export_inspection import inspect_ptu
from leica_flim_converter.gui import MainWindow
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import PtuExportOptions, write_dataset_ptu
from tests.test_reference_science import example_path


@pytest.fixture(scope="module", name="problem_catalogues")
def problem_catalogues_fixture() -> dict[str, list[DatasetInfo]]:
    """Index the supplied examples once, without packaging user data."""
    return {
        name: scan_lif(path)
        for name in ("No 2.lif", "HCC_mScr-pyr+mTFP-lact.lif")
        if (path := example_path(name)) is not None
    }


def _dataset(catalogues: dict, filename: str, acquisition: str) -> DatasetInfo:
    if filename not in catalogues:
        pytest.skip("Optional problem LIF is unavailable")
    return next(
        item
        for item in catalogues[filename]
        if item.acquisition_name == acquisition
    )


def _timelapse_companion(dataset: DatasetInfo, plane: int) -> Path:
    return (
        dataset.source.parent
        / "HCC_mScr-pyr+mTFP-lact.sptw/Timelapse Examples/PTU/Series011"
        / f"Series011_t{plane + 1}.ptu"
    )


@pytest.mark.real_data
def test_compressed_detector_and_ptu(
    problem_catalogues: dict, tmp_path: Path
) -> None:
    """No 2's PTU is Image002; compare every native arrival bin."""
    dataset = _dataset(problem_catalogues, "No 2.lif", "Image002")
    for item in problem_catalogues["No 2.lif"]:
        assert item.channel_count == 1
        assert item.detector_name == "HyD S 2"
        assert item.detector_identifier == "2"
        assert item.emission_filter_band == "496 - 802 nm"
        assert item.excitation_wavelengths_nm == pytest.approx((488,))
    companion = dataset.source.with_suffix(".ptu")
    if not companion.exists():
        pytest.skip("Optional No 2 PTU is unavailable")
    target = tmp_path / "image002.ptu"
    write_dataset_ptu(
        dataset,
        0,
        target,
        PtuExportOptions(),
        progress=lambda _message: None,
        cancelled=lambda: False,
    )
    actual, expected = inspect_ptu(target), inspect_ptu(companion)
    assert actual.photons == expected.photons == 25351913
    assert np.array_equal(actual.microtime, expected.microtime)


@pytest.mark.real_data
@pytest.mark.parametrize("plane", range(20))
def test_every_timelapse_ptu(
    problem_catalogues: dict, tmp_path: Path, plane: int
) -> None:
    """Check photons, native arrivals and decays at every time."""
    dataset = _dataset(
        problem_catalogues, "HCC_mScr-pyr+mTFP-lact.lif", "Series011"
    )
    companion = _timelapse_companion(dataset, plane)
    if not companion.exists():
        pytest.skip("Optional timelapse PTU is unavailable")
    assert dataset.t_count == 20
    assert dataset.excitation_wavelengths_nm == (1040,)
    expected = inspect_ptu(companion)
    target = tmp_path / "timepoint.ptu"
    write_dataset_ptu(
        dataset,
        plane,
        target,
        PtuExportOptions(),
        progress=lambda _message: None,
        cancelled=lambda: False,
    )
    actual = inspect_ptu(target)
    assert actual.photons == expected.photons
    assert np.array_equal(actual.microtime, expected.microtime)
    bins = native_period_bins(
        dataset.clock_period_s, dataset.laser_frequency_hz
    )
    cube = decode_histogram_plane(dataset, plane, bins=bins, threads=4)
    decay = expected.microtime[:bins].copy()
    decay[-1] += expected.microtime[bins:].sum(dtype=np.uint64)
    assert cube.events == expected.photons
    assert np.array_equal(cube.counts.sum(axis=(1, 2), dtype=np.uint64), decay)


@pytest.mark.real_data
@pytest.mark.parametrize(
    ("filename", "acquisition"),
    [
        ("No 2.lif", "Image001"),
        ("No 2.lif", "Image002"),
        ("HCC_mScr-pyr+mTFP-lact.lif", "Series011"),
    ],
)
def test_gui_decodes_without_preview_counts(
    problem_catalogues: dict,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    acquisition: str,
) -> None:
    """Use real workers and confirm timepoint changes replace images."""
    dataset = _dataset(problem_catalogues, filename, acquisition)
    assert dataset.total_photons is None
    assert dataset.excitation_sources == (
        "WLL" if filename == "No 2.lif" else "MP2",
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *args: ([str(dataset.source)], "LIF files (*.lif)"),
    )
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_button.click()
    qtbot.waitUntil(lambda: window.scan_worker is None, timeout=20000)
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            found := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and found.key == dataset.key
    )
    assert dataset.thumbnail is not None
    assert not item.icon().isNull()
    window.select_block(item)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert window.cube is not None
    assert window.status_label.text().startswith("Ready:")
    assert "valid counts" in window.fields["Photons"].text()
    assert "raw counts unavailable" in window.fields["Photons"].text()
    if dataset.t_count == 1:
        return
    previous = window.cube.intensity.copy()
    for plane in (2, 19):
        window.plane_combo.setCurrentIndex(plane + 1)
        qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
        assert window.cube is not None
        assert window.current_plane == plane
        assert window.plane_combo.currentText() == f"t{plane + 1:03d}"
        assert not np.array_equal(previous, window.cube.intensity)
        companion = _timelapse_companion(dataset, plane)
        if companion.exists():
            reference = inspect_ptu(companion)
            bins = window.cube.counts.shape[0]
            assert window.cube.time_grid is not None
            assert window.cube.time_grid.mode == "native"
            assert (
                window.cube.events + window.cube.overflow_events
                == reference.photons
            )
            np.testing.assert_array_equal(
                window.cube.counts.sum(axis=(1, 2), dtype=np.uint64),
                reference.microtime[:bins],
            )
        previous = window.cube.intensity.copy()
    window.plane_combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: window.decode_worker is None, timeout=20000)
    assert window.current_plane is None
    assert window.cube is not None
    companions = [
        _timelapse_companion(dataset, plane)
        for plane in range(dataset.plane_count)
    ]
    if all(path.exists() for path in companions):
        assert window.cube.events + window.cube.overflow_events == sum(
            inspect_ptu(path).photons for path in companions
        )
