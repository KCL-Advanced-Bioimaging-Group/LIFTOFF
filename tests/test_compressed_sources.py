"""Mixed WLL/MP acquisition metadata, photon isolation and exports."""

import json
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.histogram import decode_histogram_cube
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import (
    NativePreparedDecoder,
    decode_histogram_plane,
)
from leica_flim_converter.photon_selection import dataset_selection_metadata
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from tests.compressed_fixture import mixed_compressed_lif
from tests.test_reference_science import example_path


@pytest.mark.parametrize("route", [1, 7])
@pytest.mark.parametrize("mask", [7, 3, 1, 15])
def test_compressed_detector_isolation(
    tmp_path: Path, route: int, mask: int
) -> None:
    """Whole, prepared and Python readers agree on every bin."""
    datasets = scan_lif(mixed_compressed_lif(tmp_path / "mixed.lif", route))
    assert len(datasets) == len({d.key for d in datasets}) == 2
    for index, dataset in enumerate(datasets):
        assert dataset.channel_count == 2  # C=3 includes a non-FLIM detector.
        assert dataset.sequence_index == index
        assert dataset.detector_route == (route if index else 0)
        assert dataset.laser_frequency_hz == (5e8 if index else 1e9)
        assert dataset.excitation_label == (
            "740 nm (MP)" if index else "555 nm (WLL)"
        )
        assert dataset.emission_filter_band == (
            "410 - 490 nm" if index else "565 - 630 nm"
        )
        assert dataset.detector_dead_time_s == 1.3e-9
        expected = np.zeros((20, 2, 3), dtype=np.uint64)
        period = 20 if index else 10
        for y in range(2):
            for x in range(3):
                times = [2, 4, 6] if index else [1, 3]
                times += [times[-1]] * (x + y)
                times += [
                    arrival
                    for flag, arrival in ((2, 4), (4, 5), (8, 6))
                    if mask & flag
                ]
                for arrival in times:
                    expected[arrival * 20 // period, y, x] += 1
        cubes = [
            decode_histogram_cube(dataset, bins=20, event_flag_mask=mask),
            decode_histogram_cube(
                dataset, bins=20, event_flag_mask=mask, prefer_native=False
            ),
            decode_histogram_plane(dataset, 0, bins=20, event_flag_mask=mask),
        ]
        for cube in cubes:
            assert cube.events == int(expected.sum())
            np.testing.assert_array_equal(cube.counts, expected)
        metadata = dataset_selection_metadata(dataset, mask)
        assert metadata["includedEventFlags"] == list(
            cubes[0].included_event_flags
        )


@pytest.mark.parametrize("mask", [7, 3, 1])
def test_compressed_pair_exports(tmp_path: Path, mask: int) -> None:
    """Each exported pair retains only its own photons and timing."""
    datasets = scan_lif(mixed_compressed_lif(tmp_path / "mixed.lif"))
    ptus = export_ptu_blocks(
        datasets,
        tmp_path / "ptus",
        options=PtuExportOptions(event_flag_mask=mask),
    )
    images = export_ics_blocks(
        datasets,
        tmp_path / "images",
        options=IcsExportOptions(bins=32, event_flag_mask=mask),
    )
    for dataset, ptu_result, image_result in zip(
        datasets, ptus, images, strict=True
    ):
        assert ptu_result["status"] == image_result["status"] == "exported"
        cube = decode_histogram_cube(dataset, bins=32, event_flag_mask=mask)
        ptu = inspect_ptu(Path(ptu_result["path"]))
        assert ptu.photons == cube.events
        rebinned = np.bincount(
            np.minimum(
                31, np.arange(ptu.microtime.size) * 32 // cube.period_bins
            ),
            weights=ptu.microtime,
            minlength=32,
        )
        np.testing.assert_array_equal(
            rebinned, cube.counts.sum(axis=(1, 2), dtype=np.uint64)
        )
        header = parse_ptu(Path(ptu_result["path"]))
        resolution = next(
            tag["value"]
            for tag in header["tags"]
            if tag["ident"] == "MeasDesc_GlobalResolution"
        )
        assert dataset.laser_frequency_hz is not None
        assert resolution == pytest.approx(1 / dataset.laser_frequency_hz)
        image = read_ics(Path(image_result["path"]))
        np.testing.assert_array_equal(image.counts, cube.counts)
        sidecar = json.loads(
            Path(ptu_result["sidecar"]).read_text(encoding="utf-8")
        )
        assert (
            sidecar["sequence"]["localDetectorRoute"] == dataset.detector_route
        )


def test_prepared_compressed_pair_identity(tmp_path: Path) -> None:
    """A prepared channel cannot silently supply a different pair."""
    first, second = scan_lif(mixed_compressed_lif(tmp_path / "mixed.lif"))
    with NativePreparedDecoder(first) as prepared:
        with pytest.raises(ValueError, match="another recorded pair"):
            decode_histogram_plane(second, 0, bins=32, prepared=prepared)


@pytest.mark.real_data
def test_paneth_sources() -> None:
    """Read the supplied acquisition with native and Python decoders."""
    path = example_path(
        "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"
    )
    if path is None:
        pytest.skip("Optional mixed-source LIF is unavailable")
    datasets = [
        d for d in scan_lif(path) if d.acquisition_name == "paneth_ctx555_1"
    ]
    assert [d.detector_name for d in datasets] == ["HyD X 3", "HyD NDD 2"]
    assert [d.excitation_label for d in datasets] == [
        "555 nm (WLL)",
        "740 nm (MP)",
    ]
    assert [d.laser_frequency_hz for d in datasets] == [78020000, 80000000]
    assert [d.emission_filter_band for d in datasets] == [
        "566 - 630 nm",
        "410 - 490 nm",
    ]
    for dataset in datasets:
        assert dataset.emission_band_metadata is not None
        assert dataset.emission_band_metadata.source_fields == (
            "TargetWaveLengthBegin",
            "TargetWaveLengthEnd",
        )
    for dataset in datasets:
        native = decode_histogram_cube(dataset, bins=32, threads=4)
        python = decode_histogram_cube(dataset, bins=32, prefer_native=False)
        assert native.backend == "native"
        assert native.events > 0
        np.testing.assert_array_equal(native.counts, python.counts)
