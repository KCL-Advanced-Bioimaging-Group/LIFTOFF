"""Rate-dependent full-resolution windows and disabled upsampling."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel

from leica_flim_converter import ics_export
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.reflection_export import ReflectionWindow
from leica_flim_converter.timing import numeric_time_window, time_grid
from tests.compressed_fixture import (
    _container,  # pylint: disable=protected-access
)
from tests.test_repetition_rate import rate_dataset

CLOCK = 9.696969697e-11


def compressed_decay(template, directory, rate_mhz, native_bins, profile):
    """Store native times including the trim boundary and tail."""
    arrivals = np.arange(2 * native_bins + 1)
    weights = (
        np.full(arrivals.size, 7, np.uint32)
        if profile == "flat"
        else np.rint(500 * np.exp(-arrivals * CLOCK / 3e-9)).astype(np.uint32)
    )
    counts = weights[:, None, None] * np.array([[1, 2], [3, 4]], np.uint32)
    rows = []
    for y in range(2):
        row = bytearray()
        for x in range(2):
            row.append(0xA8)
            previous = 0
            for arrival in np.flatnonzero(counts[:, y, x]):
                delta = int(arrival) - previous
                if delta >= 128:
                    row.append(0xC0 | delta >> 7)
                row.append(delta & 127)
                row.extend(bytes(int(counts[arrival, y, x]) - 1))
                previous = int(arrival)
            row.append(0x81)
        rows.append(bytes(row))
    payload = _container(rows)
    source = directory / "decay.lif"
    source.write_bytes(payload)
    dataset = replace(
        rate_dataset(template, f"{rate_mhz:g}"),
        source=source,
        block_start=0,
        block_end=len(payload),
        compressed_bytes=len(payload),
        storage_format="compressed",
        sequence_count=1,
        clock_period_s=CLOCK,
        laser_frequency_hz=rate_mhz * 1e6 * 0.97525,
        line_offsets_start=None,
        line_offsets_end=None,
    )
    return dataset, counts


@pytest.mark.parametrize(
    "rate_mhz,native_bins", [(80, 128), (40, 256), (20, 512), (10, 1024)]
)
@pytest.mark.parametrize("output", [16, 64, "full"])
@pytest.mark.parametrize("profile", ["flat", "exponential"])
def test_export_keeps_fixed_clock_and_rate_window(
    raw_dataset, tmp_path, rate_mhz, native_bins, output, profile
):
    """Check both backends, cache paths and every exported count."""
    dataset, counts = compressed_decay(
        raw_dataset, tmp_path, rate_mhz, native_bins, profile
    )
    bins = native_bins if output == "full" else output
    expected = (
        counts[:native_bins]
        .reshape(bins, native_bins // bins, 2, 2)
        .sum(axis=1, dtype=np.uint64)
    )
    grid = time_grid(dataset, bins)
    assert grid.step_s == CLOCK * (native_bins // bins)
    assert grid.extent_s == native_bins * CLOCK
    for prefer_native, threads in ((False, 1), (True, 1), (True, 4)):
        cube = decode_histogram_plane(
            dataset,
            0,
            bins=bins,
            grid=grid,
            event_flag_mask=7,
            prefer_native=prefer_native,
            threads=threads,
        )
        np.testing.assert_array_equal(cube.counts, expected)
        assert cube.events + cube.overflow_events == int(counts.sum())
        if prefer_native:
            assert cube.backend == "native-range"
    native_grid = time_grid(dataset, None)
    native = decode_histogram_plane(
        dataset, 0, bins=native_grid.bins, grid=native_grid, event_flag_mask=7
    )
    for name, cached in (("fresh", {}), ("cached", {dataset.key: native})):
        report = export_ics_blocks(
            [dataset],
            tmp_path / name,
            IcsExportOptions(bins=bins),
            cached_cubes=cached,
            plane_selection={dataset.key: [0]},
        )[0]
        assert report["status"] == "exported", report
        image = read_ics(Path(report["path"]))
        np.testing.assert_array_equal(image.counts, expected)
        assert float(image.header["parameter/scale"][-1]) == grid.step_s
        metadata = json.loads(
            Path(report["sidecar"]).read_text(encoding="utf-8")
        )
        assert metadata["histogramTiming"]["windowFrequencyRole"] == "selected"
        assert metadata["histogramTiming"]["nativeWindowBins"] == native_bins
        accounting = metadata["photonAccounting"]
        assert accounting["selectedPhotons"] == int(counts.sum())
        assert accounting["exportedPhotons"] == int(expected.sum())
        assert accounting["excludedOutsideTimeWindow"] == int(
            counts[native_bins:].sum()
        )


@pytest.mark.parametrize(
    "rate_mhz,native_bins", [(80, 128), (40, 256), (20, 512), (10, 1024)]
)
def test_selected_rate_overrides_actual_and_rejects_upsampling(
    raw_dataset, rate_mhz, native_bins
):
    """Use the nominal selection even if actual calibration differs."""
    dataset = replace(
        rate_dataset(raw_dataset, str(rate_mhz)), clock_period_s=CLOCK
    )
    window = numeric_time_window(dataset)
    assert window.bins == native_bins
    assert window.frequency.value == rate_mhz * 1e6
    assert window.rate_role == "selected"
    grid = time_grid(dataset, native_bins)
    np.testing.assert_array_equal(
        grid.lookup()[:native_bins], np.arange(native_bins)
    )
    assert grid.lookup()[native_bins] == -1
    with pytest.raises(ValueError, match="upsampling is unavailable"):
        time_grid(dataset, native_bins * 2)


@pytest.mark.parametrize(
    "actual,native_bins", [(78.02e6, 128), (39.01e6, 256), (19.505e6, 512)]
)
def test_actual_rate_fallback_is_recorded(raw_dataset, actual, native_bins):
    """Record fallback rates in the metadata defining the grid."""
    dataset = replace(
        raw_dataset, clock_period_s=CLOCK, laser_frequency_hz=actual
    )
    window = numeric_time_window(dataset)
    assert window.bins == native_bins
    assert window.rate_role == "actual fallback; selected rate unavailable"
    grid = time_grid(dataset, native_bins)
    assert grid.metadata()["windowFrequency"]["value"] == actual
    assert "actual fallback" in grid.metadata()["windowFrequencyRole"]


@pytest.mark.parametrize(
    "native_period,expected", [(191, 128), (192, 128), (193, 256)]
)
def test_nearest_power_of_two_uses_absolute_distance(
    raw_dataset, native_period, expected
):
    """At a halfway tie, use the smaller power-of-two window."""
    dataset = replace(
        raw_dataset, clock_period_s=0.5, laser_frequency_hz=2 / native_period
    )
    assert numeric_time_window(dataset).bins == expected


@pytest.mark.parametrize(
    "rate_mhz,native_bins", [(80, 128), (40, 256), (20, 512), (10, 1024)]
)
def test_dialog_default_and_disabled_items(
    raw_dataset, qtbot, rate_mhz, native_bins
):
    """Only full resolution and downsampling can be selected."""
    dataset = replace(
        rate_dataset(raw_dataset, str(rate_mhz)), clock_period_s=CLOCK
    )
    dialog = IcsExportDialog([dataset], {})
    qtbot.addWidget(dialog)
    assert dialog.bins.currentData() == native_bins
    assert (
        dialog.bins.currentText()
        == f"{native_bins} (default for {rate_mhz}MHz)"
    )
    model = dialog.bins.model()
    assert isinstance(model, QStandardItemModel)
    for index in range(dialog.bins.count()):
        value = dialog.bins.itemData(index)
        item = model.item(index)
        assert item is not None
        assert item.isEnabled() == (value is None or value <= native_bins)
    assert dialog.options(1).bins == native_bins
    assert dialog.compression.currentData() == "gzip"


def test_dialog_fallback_tooltip(raw_dataset, qtbot):
    """Show fallback provenance in the default bin's tooltip."""
    dataset = replace(
        raw_dataset, clock_period_s=CLOCK, laser_frequency_hz=39.01e6
    )
    dialog = IcsExportDialog([dataset], {})
    qtbot.addWidget(dialog)
    assert dialog.bins.currentText() == "256 (default for 39.01MHz)"
    model = dialog.bins.model()
    assert isinstance(model, QStandardItemModel)
    item = model.item(dialog.bins.currentIndex())
    assert item is not None
    assert "actual fallback; selected rate unavailable" in item.toolTip()


def test_batch_selection_updates_default_without_upsampling(
    raw_dataset, tmp_path, qtbot
):
    """Preserve downsampling as the common window changes."""
    first = replace(rate_dataset(raw_dataset), clock_period_s=CLOCK)
    copied = tmp_path / "40MHz.lif"
    copied.write_bytes(raw_dataset.source.read_bytes())
    second = replace(
        rate_dataset(raw_dataset, "40"), source=copied, clock_period_s=CLOCK
    )
    dialog = IcsExportDialog([first, second], {})
    qtbot.addWidget(dialog)
    rows = {
        target[0].key: row
        for row, target in enumerate(dialog.row_targets)
        if target is not None
    }
    first_check = required_table_item(dialog.table, rows[first.key], 0)
    second_check = required_table_item(dialog.table, rows[second.key], 0)
    assert first_check.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert second_check.flags() & Qt.ItemFlag.ItemIsUserCheckable
    second_check.setCheckState(Qt.CheckState.Checked)
    assert dialog.bins.currentData() == 256
    first_check.setCheckState(Qt.CheckState.Checked)
    assert dialog.bins.currentData() == 128
    assert len(dialog.selected_datasets()) == 2
    first_check.setCheckState(Qt.CheckState.Unchecked)
    assert dialog.bins.currentData() == 256
    dialog.bins.setCurrentIndex(dialog.bins.findData(64))
    first_check.setCheckState(Qt.CheckState.Checked)
    assert dialog.bins.currentData() == 64
    assert (
        dialog.bins.itemText(dialog.bins.findData(128))
        == "128 (default for 80MHz)"
    )
    dialog.bins.setCurrentIndex(dialog.bins.findData(128))
    first_check.setCheckState(Qt.CheckState.Unchecked)
    assert dialog.bins.currentData() == 256
    dialog.dimension_mode.setCurrentIndex(1)
    assert dialog.bins.currentData() == 128
    assert all(
        required_table_item(dialog.table, row, 0).flags()
        & Qt.ItemFlag.ItemIsUserCheckable
        for row, target in enumerate(dialog.row_targets)
        if target is not None
    )
    dialog.bins.setCurrentIndex(0)
    dialog._set_all(Qt.CheckState.Checked)  # pylint: disable=protected-access
    assert dialog.bins.currentData() is None


def test_reflection_cannot_shorten_a_selected_rate_window(
    raw_dataset, tmp_path
):
    """Retain the selected window despite a shorter cache."""
    dataset, counts = compressed_decay(raw_dataset, tmp_path, 40, 256, "flat")
    dataset = replace(dataset, laser_frequency_hz=80e6)
    native_grid = time_grid(dataset, None)
    assert native_grid.bins < 256
    cached = decode_histogram_plane(
        dataset, 0, bins=native_grid.bins, grid=native_grid, event_flag_mask=7
    )
    original = cached.counts.copy()
    removed = int(counts[5:9].sum())
    counts[5:9] = 0
    expected = counts[:256].reshape(64, 4, 2, 2).sum(axis=1, dtype=np.uint64)
    result = export_ics_blocks(
        [dataset],
        tmp_path / "filtered",
        IcsExportOptions(
            bins=64,
            reflection_windows=(ReflectionWindow(dataset.key, 4.2, 8.5),),
        ),
        cached_cubes={dataset.key: cached},
        plane_selection={dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    np.testing.assert_array_equal(
        read_ics(Path(result["path"])).counts, expected
    )
    np.testing.assert_array_equal(cached.counts, original)
    metadata = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
    accounting = metadata["photonAccounting"]
    assert accounting["excludedReflectionPhotons"] == removed
    assert accounting["excludedOutsideTimeWindow"] == int(counts[256:].sum())


def test_same_size_native_cache_gets_requested_grid_metadata(
    raw_dataset, tmp_path, monkeypatch
):
    """Reuse counts with the requested window metadata."""
    dataset, _counts = compressed_decay(raw_dataset, tmp_path, 80, 128, "flat")
    dataset = replace(
        dataset, clock_period_s=1e-10, laser_frequency_hz=78_125_000.0
    )
    native_grid = time_grid(dataset, None)
    assert native_grid.bins == 128
    native = decode_histogram_plane(
        dataset, 0, bins=128, grid=native_grid, event_flag_mask=7
    )
    decoder = Mock(side_effect=AssertionError("Cache must be reused"))
    monkeypatch.setattr(ics_export, "decode_histogram_plane", decoder)
    result = export_ics_blocks(
        [dataset],
        tmp_path / "cached",
        IcsExportOptions(bins=128),
        cached_cubes={dataset.key: native},
        plane_selection={dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    metadata = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
    assert metadata["histogramTiming"] == time_grid(dataset, 128).metadata()
    assert native.time_grid is native_grid
    np.testing.assert_array_equal(
        read_ics(Path(result["path"])).counts, native.counts
    )
    decoder.assert_not_called()
