"""Sequence identities, mixed T/Z row ownership and export isolation."""

import json
import struct
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import lif_flim_forensics as lif
from leica_flim_converter.catalog import load_intensity_movie, scan_lif
from leica_flim_converter.event_flags import (
    RAW_ALL_PHOTONS,
    RAW_FIRST_PHOTONS,
    RAW_SINGLE_EVENT,
)
from leica_flim_converter.export_inspection import inspect_ptu
from leica_flim_converter.histogram import decode_histogram_cube
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.photon_selection import dead_time_info
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.raw_decoder import RawPreparedDecoder
from tests.sequence_fixture import mixed_lif


@pytest.mark.parametrize("mode", ["SequentialFrame", "SequentialStack"])
@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("time_fast", [True, False])
def test_mixed_time_z_sequences(
    tmp_path: Path, mode: str, native: bool, time_fast: bool
) -> None:
    """Distinct rows, detectors and calibration survive both orders."""
    datasets = scan_lif(
        mixed_lif(tmp_path / "mixed.lif", mode, time_fast=time_fast)
    )
    assert len(datasets) == len({dataset.key for dataset in datasets}) == 4
    for index, dataset in enumerate(datasets):
        sequence, route = divmod(index, 2)
        assert dataset.sequence_index == sequence
        assert dataset.detector_route == route
        assert dataset.channel_index == index
        assert dataset.detector_route_count == dataset.sequence_count == 2
        assert dataset.t_count == dataset.z_count == 2
        assert dataset.plane_count == 4
        assert dataset.sequence_name == f"Setting {sequence + 1}"
        assert dataset.emission_filter_band == (
            f"{470 + sequence * 10 + route * 50} - "
            f"{510 + sequence * 10 + route * 50} nm"
        )
        assert dataset.pixel_size_x_m == pytest.approx((sequence + 1) * 1e-6)
        assert dataset.clock_period_s == pytest.approx((sequence + 1) * 1e-10)
        threshold = [2, 6, 5, 1][index]
        assert (
            dead_time_info(dataset)["minimumSubsequentArrivalDeltaBins"]
            == threshold
        )
        expected_events = [32, 16, 4, 8][index]
        intensity = load_intensity_movie(dataset)
        assert intensity is not None
        assert np.array_equal(
            intensity.sum(axis=(1, 2)), [expected_events] * 4
        )
        cubes = []
        for plane in range(4):
            time, z = (
                (plane % 2, plane // 2)
                if time_fast
                else (plane // 2, plane % 2)
            )
            assert dataset.plane_indices(plane) == (time, z)
            assert (
                dataset.plane_label(plane) == f"t{time + 1:03d}_z{z + 1:03d}"
            )
            cube = decode_histogram_plane(
                dataset,
                plane,
                bins=32,
                threads=4,
                prefer_native=native,
                event_flag_mask=RAW_ALL_PHOTONS,
            )
            assert cube.events == cube.reference_events == expected_events
            assert cube.source_dataset_key == dataset.key
            assert cube.linear_plane == plane
            assert cube.decoded_rows == (8 if sequence == 0 else 2)
            assert np.array_equal(cube.intensity, intensity[plane])
            # Check arrival locations independently of decoder output.
            expected = np.zeros_like(cube.counts)
            base = 1 + time * 2 + z + route
            period = 10 if sequence == 0 else 20
            repeats = 4 if sequence == 0 else 1
            for pixel in range(2):
                arrivals = [base + pixel * 5]
                if threshold <= 3:
                    arrivals.append(base + pixel * 5 + 3)
                for arrival in arrivals:
                    expected[min(31, arrival * 32 // period), :, pixel] += (
                        repeats
                    )
            assert np.array_equal(cube.counts, expected)
            cubes.append(cube.counts)
        overview = decode_histogram_cube(
            dataset,
            bins=32,
            prefer_native=native,
            event_flag_mask=RAW_ALL_PHOTONS,
        )
        assert (
            overview.events == overview.reference_events == expected_events * 4
        )
        assert overview.decoded_rows == dataset.indexed_rows
        assert overview.linear_plane is None
        assert np.array_equal(overview.counts, np.sum(cubes, axis=0))


@pytest.mark.parametrize("mode", [RAW_FIRST_PHOTONS, RAW_SINGLE_EVENT])
def test_sequence_photon_modes(tmp_path: Path, mode: int) -> None:
    """Native and Python selection agree on sequence-local routes."""
    for dataset in scan_lif(mixed_lif(tmp_path / "mixed.lif")):
        for plane in range(4):
            native = decode_histogram_plane(
                dataset, plane, bins=32, event_flag_mask=mode
            )
            python = decode_histogram_plane(
                dataset,
                plane,
                bins=32,
                event_flag_mask=mode,
                prefer_native=False,
            )
            assert np.array_equal(native.counts, python.counts)
            assert (
                native.events
                == python.events
                == (
                    (16 if dataset.sequence_index == 0 else 4)
                    if mode == RAW_FIRST_PHOTONS
                    else 0
                )
            )


def test_six_display_channels_reuse_two_routes(tmp_path: Path) -> None:
    """The hardware four-route limit applies within each sequence."""
    datasets = scan_lif(mixed_lif(tmp_path / "mixed.lif", sequences=3))
    assert len(datasets) == len({dataset.key for dataset in datasets}) == 6
    for dataset in datasets:
        cube = decode_histogram_plane(
            dataset, 3, bins=1, event_flag_mask=RAW_ALL_PHOTONS
        )
        assert cube.events == [32, 16, 4, 8, 32, 16][dataset.channel_index]


def test_invalid_sequence_index_fails_before_decoding(tmp_path: Path) -> None:
    """Never repair malformed sequence boundaries by guessing rows."""
    for dataset in scan_lif(
        mixed_lif(tmp_path / "mixed.lif", invalid_frames=True)
    ):
        assert dataset.repetition_storage_model == "unresolved"
        with pytest.raises(RuntimeError, match="FrameOffsets"):
            decode_histogram_plane(dataset, 0, bins=1)


def _rewrite_header(
    source: Path, root: ET.Element, payload: bytes, end: int
) -> None:
    xml_payload = ET.tostring(root, encoding="unicode").encode("utf-16le")
    source.write_bytes(
        struct.pack(
            "<IIBI", 112, 5 + len(xml_payload), 42, len(xml_payload) // 2
        )
        + xml_payload
        + payload[end:]
    )


@pytest.mark.parametrize("axis", ["detector", "z"])
def test_ambiguous_intensity_does_not_borrow_another_pair(
    tmp_path: Path, axis: str
) -> None:
    """Decline overlapping references while still decoding photons."""
    source = mixed_lif(tmp_path / "mixed.lif")
    payload = source.read_bytes()
    xml, end = lif.parse_lif_header(payload)
    root = ET.fromstring(xml)
    intensity = root.find(".//Element[@Name='Intensity']")
    assert intensity is not None
    if axis == "detector":
        intensity.findall(".//ChannelDescription")[1].set("BytesInc", "0")
    else:
        z_dimension = intensity.find(".//DimensionDescription[@DimID='3']")
        assert z_dimension is not None
        z_dimension.set("BytesInc", "16")
    _rewrite_header(source, root, payload, end)
    for dataset in scan_lif(source):
        assert dataset.intensity_start is dataset.total_photons is None
        assert dataset.thumbnail is None
        cube = decode_histogram_plane(
            dataset, 0, bins=1, event_flag_mask=RAW_ALL_PHOTONS
        )
        assert cube.events == [32, 16, 4, 8][dataset.channel_index]
        assert (
            cube.reference_events is cube.spatial_alignment_correlation is None
        )


def test_detector_calibration_overrides_its_sequence(tmp_path: Path) -> None:
    """Timing and spatial calibration do not leak between detectors."""
    source = mixed_lif(tmp_path / "mixed.lif")
    payload = source.read_bytes()
    xml, end = lif.parse_lif_header(payload)
    root = ET.fromstring(xml)
    raw = root.find(".//RawData")
    assert raw is not None
    detector = raw.findall("Sequence/SequenceItem/Detectors/Detectors")[1]
    ET.SubElement(detector, "ClockPeriod").text = "2e-10"
    ET.SubElement(detector, "VoxelSizeX").text = "1.5e-6"
    frequency = detector.find("LaserPulseFrequency")
    assert frequency is not None
    frequency.text = "1e8"
    _rewrite_header(source, root, payload, end)
    datasets = scan_lif(source)
    assert datasets[0].clock_period_s == 1e-10
    assert datasets[1].clock_period_s == 2e-10
    assert datasets[1].laser_frequency_hz == 1e8
    assert datasets[1].pixel_size_x_m == 1.5e-6
    assert (
        dead_time_info(datasets[1])["minimumSubsequentArrivalDeltaBins"] == 3
    )
    cube = decode_histogram_plane(
        datasets[1], 0, bins=50, event_flag_mask=RAW_ALL_PHOTONS
    )
    assert cube.period_bins == 50
    assert cube.events == 32
    with RawPreparedDecoder(datasets[0]) as prepared:
        with pytest.raises(ValueError, match="another recorded pair"):
            decode_histogram_plane(datasets[1], 0, bins=1, prepared=prepared)


def test_sequence_exports_and_wrong_cache(tmp_path: Path) -> None:
    """Export each pair/T/Z plane, rejecting foreign or plane caches."""
    datasets = scan_lif(mixed_lif(tmp_path / "mixed.lif"))
    options = IcsExportOptions(bins=32, event_flag_mask=RAW_ALL_PHOTONS)
    results = export_ics_blocks(datasets, tmp_path / "ics", options)
    assert len(results) == 16
    for result in results:
        assert result["status"] == "exported", result
        metadata = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )
        identity = metadata["sequence"]
        dataset = next(
            item for item in datasets if item.key == metadata["datasetKey"]
        )
        assert (
            f"seq{dataset.sequence_index + 1:02d}" in Path(result["path"]).name
        )
        assert identity["localDetectorRoute"] == dataset.detector_route
        assert (
            metadata["photonAccounting"]["selectedPhotons"]
            == [32, 16, 4, 8][dataset.channel_index]
        )
        assert (
            metadata["calibration"]["clockPeriodSeconds"]
            == dataset.clock_period_s
        )
    ptus = export_ptu_blocks(
        datasets,
        tmp_path / "ptu",
        PtuExportOptions(event_flag_mask=RAW_ALL_PHOTONS),
    )
    assert len(ptus) == 16
    for result in ptus:
        assert result["status"] == "exported", result
        metadata = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )
        dataset = next(
            item for item in datasets if item.key == metadata["datasetKey"]
        )
        assert (
            inspect_ptu(Path(result["path"])).photons
            == [32, 16, 4, 8][dataset.channel_index]
        )
        assert (
            metadata["sequence"]["sequenceIndexZeroBased"]
            == dataset.sequence_index
        )
    foreign = decode_histogram_cube(
        datasets[0], bins=32, event_flag_mask=RAW_ALL_PHOTONS
    )
    for cache in (
        foreign,
        replace(foreign, source_dataset_key=datasets[2].key, linear_plane=0),
        replace(foreign, source_dataset_key=None),
    ):
        result = export_ics_blocks(
            [datasets[2]],
            tmp_path / "cached",
            replace(options, dimension_mode="integrate"),
            cached_cubes={datasets[2].key: cache},
        )[0]
        metadata = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )
        assert metadata["totalPhotonCount"] == 16
