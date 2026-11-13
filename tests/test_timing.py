"""Independent physical-time checks across ICS and PTU exports."""

import json
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.calibrated_histogram import decode_calibrated
from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.catalog_sequences import attach_detector_metadata
from leica_flim_converter.catalog_timing import read_timing
from leica_flim_converter.event_flags import RAW_ALL_PHOTONS
from leica_flim_converter.export_inspection import (
    inspect_ptu,
    read_ics,
    rehistogram_arrivals,
)
from leica_flim_converter.gui_ics_dialog import IcsExportDialog
from leica_flim_converter.gui_models import required_table_item
from leica_flim_converter.gui_ptu_dialog import PtuExportDialog
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.timing import (
    AcquisitionTiming,
    TimingValue,
    time_grid,
)
from tests.compressed_fixture import mixed_compressed_lif
from tests.sequence_fixture import mixed_lif


def assert_cross_format(dataset, directory, bins, mask):
    """Re-histogram PTU arrivals using the written ICS calibration."""
    ptu = export_ptu_blocks(
        [dataset],
        directory / "ptu",
        PtuExportOptions(event_flag_mask=mask),
        plane_selection={dataset.key: [0]},
    )[0]
    ics = export_ics_blocks(
        [dataset],
        directory / "ics",
        IcsExportOptions(bins=bins, event_flag_mask=mask),
        plane_selection={dataset.key: [0]},
    )[0]
    assert ptu["status"] == ics["status"] == "exported", (ptu, ics)
    photons = inspect_ptu(Path(ptu["path"]))
    tags = {
        tag["ident"]: tag["value"]
        for tag in parse_ptu(Path(ptu["path"]))["tags"]
    }
    image = read_ics(Path(ics["path"]))
    step = float(image.header["parameter/scale"][-1])
    extent = float(image.header["history/extents"][-1].split()[-1])
    assert step * image.counts.shape[0] == pytest.approx(extent, rel=1e-15)
    expected, excluded = rehistogram_arrivals(
        photons, image, float(tags["MeasDesc_Resolution"])
    )
    assert np.array_equal(
        image.counts.sum(axis=(1, 2), dtype=np.uint64), expected
    )
    metadata = json.loads(Path(ics["sidecar"]).read_text(encoding="utf-8"))
    accounting = metadata["photonAccounting"]
    assert accounting["selectedPhotons"] == photons.photons
    assert accounting["exportedPhotons"] == int(expected.sum())
    assert accounting["excludedOutsideTimeWindow"] == excluded
    assert metadata["histogramTiming"]["mode"] == (
        "native" if bins is None else "rebinned"
    )
    return metadata


@pytest.mark.parametrize("bins", [None, 32, 128, 256])
@pytest.mark.parametrize(
    "clock,frequency",
    [
        (1e-10, 625e6),
        (9.696969697e-11, 78.02e6),
        (2.1e-10, 80e6),
        (1e-9, 80e6),
    ],
)
def test_physical_time_cross_format(
    raw_dataset, tmp_path, bins, clock, frequency
):
    """Cover both sides of rounded periods and different clocks."""
    dataset = replace(
        raw_dataset, clock_period_s=clock, laser_frequency_hz=frequency
    )
    assert_cross_format(dataset, tmp_path, bins, RAW_ALL_PHOTONS)


@pytest.mark.parametrize("grammar", ["raw", "compressed"])
def test_scoped_sequences_cross_format(tmp_path, grammar):
    """Keep calibration separate for each detector and plane."""
    fixture = mixed_lif if grammar == "raw" else mixed_compressed_lif
    datasets = scan_lif(fixture(tmp_path / "mixed.lif"))
    for index, dataset in enumerate(datasets):
        assert_cross_format(
            dataset,
            tmp_path / str(index),
            128,
            RAW_ALL_PHOTONS if grammar == "raw" else 7,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("clock_period_s", None),
        ("laser_frequency_hz", None),
        ("clock_period_s", float("nan")),
        ("laser_frequency_hz", 0),
    ],
)
def test_missing_calibration_fails(raw_dataset, tmp_path, field, value):
    """Both formats refuse fabricated temporal calibration."""
    dataset = replace(raw_dataset, **{field: value})
    for exporter in (export_ptu_blocks, export_ics_blocks):
        result = exporter([dataset], tmp_path / exporter.__name__)[0]
        assert result["status"] == "failed"
        assert "recorded positive arrival clock" in result["error"]
    assert not list(tmp_path.rglob("*.part"))


def test_timing_scope_and_invalid_field():
    """A detector's invalid calibration cannot borrow another source."""
    raw = ET.fromstring(
        "<RawData><ClockPeriod>1e-10</ClockPeriod>"
        "<PixelTime>2e-6</PixelTime></RawData>"
    )
    sequence = ET.fromstring(
        "<SequenceItem><LaserPulseFrequency>80000000</LaserPulseFrequency>"
        "</SequenceItem>"
    )
    detector = ET.fromstring(
        "<Detectors><ClockPeriod>0</ClockPeriod>"
        "<LaserPulseFrequency>78020000</LaserPulseFrequency></Detectors>"
    )
    timing = read_timing(raw, sequence, detector, "")
    assert timing.clock.value is None
    assert timing.clock.quality == "unavailable"
    assert timing.laser_frequency.value == 78020000
    assert timing.laser_frequency.source == "Detector/LaserPulseFrequency"
    assert timing.pixel_dwell.value == 2e-6


def scan_timing():
    """A complete, explicitly recorded nominal raster."""
    return AcquisitionTiming(
        pixel_dwell=TimingValue(
            1.45e-6, source="RawData/PixelTime", quality="recorded"
        ),
        line_period=TimingValue(
            4.3e-6, source="RawData/LineTime", quality="recorded"
        ),
        frame_period=TimingValue(
            12e-6, source="RawData/FrameTime", quality="recorded"
        ),
        timestamp_lists_xml=(
            '<TimeStampList NumberOfTimeStamps="1">'
            "uninterpreted</TimeStampList>",
        ),
    )


def test_reconstructed_timeline(raw_dataset, tmp_path):
    """Use recorded scan timing and round absolute marker times."""
    dataset = replace(
        raw_dataset,
        acquisition_timing=scan_timing(),
        laser_frequency_hz=78.02e6,
    )
    result = export_ptu_blocks(
        [dataset], tmp_path, PtuExportOptions(timing_mode="reconstructed")
    )[0]
    assert result["status"] == "exported", result
    metadata = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))[
        "export"
    ]
    assert metadata["timingQuality"] == "Reconstructed"
    assert metadata["pixelTicks"] == pytest.approx(1.45e-6 * 78.02e6)
    assert metadata["recordedTiming"]["timestampLists"]["rawXml"]
    assert metadata["rasterTiming"]["pixelSpacingSeconds"] == pytest.approx(
        1.45e-6
    )
    parsed = parse_ptu(Path(result["path"]))
    tags = {tag["ident"]: tag["value"] for tag in parsed["tags"]}
    assert tags["Leica_TimingQuality"] == "Reconstructed"
    assert "reconstructed" in str(tags["File_Comment"])
    # Check actual records independently of the writer's metadata.
    words = np.fromfile(
        result["path"], dtype="<u4", offset=parsed["dataOffset"]
    )
    special = words >> 31 != 0
    channels = words >> 25 & 63
    wraps = np.where(special & (channels == 63), words & 1023, 0).astype(
        np.uint64
    )
    sync = np.cumsum(wraps) * 1024 + (words & 1023)
    starts = sync[special & (channels == 1)]
    assert starts.tolist() == [0, round(4.3e-6 * 78.02e6)]
    assert inspect_ptu(Path(result["path"])).monotonic_macrotime


def test_explicit_fallback_and_gui(raw_dataset, tmp_path, qtbot):
    """Expose timing quality and disable incomplete reconstruction."""
    result = export_ptu_blocks([raw_dataset], tmp_path)[0]
    metadata = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))[
        "export"
    ]
    assert metadata["timingQuality"] == "Synthetic"
    assert metadata["rasterTiming"]["fallbackReason"]
    ptu = PtuExportDialog([raw_dataset], {})
    qtbot.addWidget(ptu)
    row = next(index for index, target in enumerate(ptu.row_targets) if target)
    assert (
        required_table_item(ptu.table, row, ptu.table.columnCount() - 2).text()
        == "Synthetic"
    )
    ptu.timing_mode.setCurrentIndex(2)
    assert required_table_item(ptu.table, row, 9).text() == "Failed"
    assert (
        required_table_item(ptu.table, row, ptu.table.columnCount() - 2).text()
        == "Unavailable"
    )
    ics = IcsExportDialog([raw_dataset], {})
    qtbot.addWidget(ics)
    assert ics.options(1).bins == 128
    ics.bins.setCurrentIndex(0)
    assert ics.options(1).bins is None
    assert time_grid(raw_dataset, None).step_s == raw_dataset.clock_period_s


@pytest.mark.parametrize("bins", [None, 32, 128])
@pytest.mark.parametrize("mask", [256, 512, 1024])
def test_native_raw_calibration_parity(raw_dataset, bins, mask):
    """Native and streaming paths agree at every pixel and bin."""
    dataset = replace(
        raw_dataset, clock_period_s=1e-9, laser_frequency_hz=80e6
    )
    grid = time_grid(dataset, bins)
    native = decode_histogram_plane(
        dataset, 0, bins=grid.bins, grid=grid, event_flag_mask=mask
    )
    python = decode_histogram_plane(
        dataset,
        0,
        bins=grid.bins,
        grid=grid,
        event_flag_mask=mask,
        prefer_native=False,
    )
    oracle = decode_calibrated(
        dataset, grid, 0, mask, lambda _m: None, lambda: False
    )
    assert native.backend.startswith("lmsraw-native")
    for candidate in (python, oracle):
        assert np.array_equal(native.counts, candidate.counts)
        assert (native.events, native.overflow_events) == (
            candidate.events,
            candidate.overflow_events,
        )


@pytest.mark.parametrize("bins", [None, 32, 128])
@pytest.mark.parametrize("mask", [1, 3, 7])
def test_native_compressed_calibration_parity(tmp_path, bins, mask):
    """Compare fast mapped decoding with the literal-stream oracle."""
    datasets = scan_lif(mixed_compressed_lif(tmp_path / "mixed.lif"))
    for dataset in datasets:
        grid = time_grid(dataset, bins)
        native = decode_histogram_plane(
            dataset,
            0,
            bins=grid.bins,
            grid=grid,
            event_flag_mask=mask,
            threads=4,
        )
        oracle = decode_calibrated(
            dataset, grid, 0, mask, lambda _m: None, lambda: False
        )
        assert native.backend == "native-range"
        assert np.array_equal(native.counts, oracle.counts)
        assert (native.events, native.overflow_events) == (
            oracle.events,
            oracle.overflow_events,
        )


@pytest.mark.parametrize("change", ["line", "frame", "repeats", "partial"])
def test_incomplete_reconstruction_is_explicit(raw_dataset, tmp_path, change):
    """Reject missing flyback and accumulated repeats explicitly."""
    timing = scan_timing()
    dataset = replace(raw_dataset, acquisition_timing=timing)
    if change == "line":
        dataset = replace(
            dataset,
            acquisition_timing=replace(timing, line_period=TimingValue(1e-9)),
        )
    elif change == "frame":
        dataset = replace(
            dataset,
            frame_repetitions=2,
            acquisition_timing=replace(timing, frame_period=TimingValue()),
        )
    elif change == "repeats":
        dataset = replace(dataset, line_repetitions=2)
    else:
        dataset = replace(dataset, dimension_status="partial indexed sequence")
    result = export_ptu_blocks(
        [dataset], tmp_path, PtuExportOptions(timing_mode="reconstructed")
    )[0]
    assert result["status"] == "failed"
    assert "Cannot reconstruct PTU timing" in result["error"]


def test_acquisition_timing_without_sequence(raw_dataset):
    """Retain dwell when older metadata omits sequence items."""
    dataset = attach_detector_metadata(
        raw_dataset, "<RawData><PixelTime>2e-6</PixelTime></RawData>"
    )
    assert dataset.acquisition_timing is not None
    assert dataset.acquisition_timing.pixel_dwell.value == 2e-6
    assert dataset.clock_period_s == raw_dataset.clock_period_s


def test_reconstructed_frame_repetitions(raw_dataset, tmp_path):
    """Reconstruct frame repeats using recorded frame periods."""
    dataset = replace(
        raw_dataset,
        height=1,
        frame_repetitions=2,
        laser_frequency_hz=78.02e6,
        acquisition_timing=scan_timing(),
    )
    result = export_ptu_blocks(
        [dataset], tmp_path, PtuExportOptions(timing_mode="reconstructed")
    )[0]
    assert result["status"] == "exported", result
    parsed = parse_ptu(Path(result["path"]))
    words = np.fromfile(
        result["path"], dtype="<u4", offset=parsed["dataOffset"]
    )
    special = words >> 31 != 0
    channels = words >> 25 & 63
    wraps = np.where(special & (channels == 63), words & 1023, 0).astype(
        np.uint64
    )
    sync = np.cumsum(wraps) * 1024 + (words & 1023)
    frames = sync[special & (channels == 4)]
    assert frames.tolist() == [0, round(12e-6 * 78.02e6)]
    assert inspect_ptu(Path(result["path"])).monotonic_macrotime
