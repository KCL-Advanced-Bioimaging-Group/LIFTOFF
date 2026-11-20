"""Trim numeric ICS output to 128 native bins, then sum exact groups."""

import json
import math
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.histogram_core import HistogramCube
from leica_flim_converter.ics import ALLOWED_BINS
from leica_flim_converter.ics_export import (
    IcsExportOptions,
    export_ics_blocks,
    rebin_cube,
)
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.reflection_export import ReflectionWindow
from leica_flim_converter.timing import TimeGrid, time_grid

CLOCK = 9.696969697e-11
STANDARD_BINS = tuple(bins for bins in ALLOWED_BINS if bins <= 128)


def quantized_dataset(
    template: DatasetInfo, directory: Path, frequency: float, profile: str
) -> tuple[DatasetInfo, np.ndarray]:
    """Encode all 256 arrival values with known per-pixel counts."""
    arrivals = np.arange(256)
    weights = (
        np.full(256, 7, dtype=np.uint32)
        if profile == "flat"
        else np.rint(500 * np.exp(-arrivals * CLOCK / 3e-9)).astype(np.uint32)
    )
    counts = weights[:, None, None] * np.array([[1, 2], [3, 4]], np.uint32)
    rows = []
    for y in range(2):
        pixels = [
            np.repeat(arrivals | 0x1000, counts[:, y, x]).astype(">u2")
            for x in range(2)
        ]
        rows.append(
            pixels[0].tobytes()
            + np.array([0xA004, 0xA008], dtype=">u2").tobytes()
            + pixels[1].tobytes()
        )
    prefix = template.source.read_bytes()[: template.block_start]
    payload = b"".join(rows)
    table = struct.pack("<9Q", 1, 2, len(payload), 0, 0, len(rows[0]), 0, 0, 0)
    source = directory / "quantized.lif"
    source.write_bytes(prefix + payload + table)
    dataset = replace(
        template,
        source=source,
        block_end=len(prefix) + len(payload),
        compressed_bytes=len(payload),
        line_offsets_start=len(prefix) + len(payload),
        line_offsets_end=source.stat().st_size,
        clock_period_s=CLOCK,
        laser_frequency_hz=frequency,
    )
    return dataset, counts


def physical_histogram(
    counts: np.ndarray, frequency: float, bins: int | None
) -> np.ndarray:
    """Trim and reshape independently of the production lookup."""
    if bins is None:
        return counts[: math.ceil(1 / frequency / CLOCK)].astype(np.uint64)
    window = 16 if frequency == 625e6 else 128
    return (
        counts[:window]
        .reshape(bins, window // bins, *counts.shape[1:])
        .sum(axis=1, dtype=np.uint64)
    )


@pytest.mark.parametrize("frequency", [78.02e6, 80e6])
@pytest.mark.parametrize("bins", [None, *STANDARD_BINS])
@pytest.mark.parametrize("profile", ["flat", "exponential"])
def test_quantized_export_and_backends(
    raw_dataset: DatasetInfo,
    tmp_path: Path,
    frequency: float,
    bins: int | None,
    profile: str,
) -> None:
    """Check every count, both backends, cache use and ICS readback."""
    dataset, counts = quantized_dataset(
        raw_dataset, tmp_path, frequency, profile
    )
    expected = physical_histogram(counts, frequency, bins)
    grid = time_grid(dataset, bins)
    for prefer_native, threads in ((False, 1), (True, 1), (True, 4)):
        cube = decode_histogram_plane(
            dataset,
            0,
            bins=grid.bins,
            grid=grid,
            event_flag_mask=256,
            prefer_native=prefer_native,
            threads=threads,
        )
        np.testing.assert_array_equal(cube.counts, expected)
        assert cube.events + cube.overflow_events == int(counts.sum())
        if prefer_native:
            assert cube.backend.startswith("lmsraw-native")
    native_grid = time_grid(dataset, None)
    native = decode_histogram_plane(
        dataset,
        0,
        bins=native_grid.bins,
        grid=native_grid,
        event_flag_mask=256,
    )
    original = native.counts.copy()
    for name, cache in (("fresh", {}), ("cached", {dataset.key: native})):
        result = export_ics_blocks(
            [dataset],
            tmp_path / name,
            IcsExportOptions(bins=bins, event_flag_mask=256),
            cached_cubes=cache,
            plane_selection={dataset.key: [0]},
        )[0]
        assert result["status"] == "exported", result
        image = read_ics(Path(result["path"]))
        np.testing.assert_array_equal(image.counts, expected)
        assert float(image.header["parameter/scale"][-1]) == grid.step_s
        accounting = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )["photonAccounting"]
        assert accounting["selectedPhotons"] == int(counts.sum())
        assert accounting["exportedPhotons"] == int(expected.sum())
        assert accounting["excludedOutsideTimeWindow"] == int(
            counts.sum() - expected.sum()
        )
    np.testing.assert_array_equal(native.counts, original)


def test_physical_edges_are_half_open() -> None:
    """Include an exact left edge; exclude the exact window end."""
    grid = TimeGrid(4, 0.5, 1.0, 2.0, "rebinned")
    np.testing.assert_array_equal(
        grid.indices(np.arange(10)), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    )
    np.testing.assert_array_equal(grid.lookup(), [0, 0, 1, 1, 2, 2, 3, 3, -1])


@pytest.mark.parametrize("frequency", [78.02e6, 80e6])
@pytest.mark.parametrize("bins", STANDARD_BINS)
def test_fixed_native_grid_has_no_beats(
    raw_dataset: DatasetInfo, frequency: float, bins: int
) -> None:
    """Give every output bin the same number of native values."""
    dataset = replace(
        raw_dataset, clock_period_s=CLOCK, laser_frequency_hz=frequency
    )
    grid = time_grid(dataset, bins)
    factor = 128 // bins
    np.testing.assert_array_equal(
        grid.indices(np.arange(256)), np.arange(256) // factor
    )
    np.testing.assert_array_equal(
        grid.lookup(), np.r_[np.repeat(np.arange(bins), factor), -1]
    )
    assert grid.step_s == CLOCK * factor
    assert grid.extent_s == 128 * CLOCK
    assert grid.metadata()["nativeWindowBins"] == 128


@pytest.mark.parametrize("bins", [0, 8, 129, 65536])
def test_unsupported_bin_choices_fail(raw_dataset: DatasetInfo, bins: int):
    """Reject obsolete upsampling choices through both entry points."""
    with pytest.raises(ValueError, match="ICS bins must be one of"):
        time_grid(raw_dataset, bins)
    with pytest.raises(ValueError, match="ICS bins must be one of"):
        IcsExportOptions(bins=bins).validate()


@pytest.mark.parametrize("frequency", [80e6, 625e6])
@pytest.mark.parametrize("bins", STANDARD_BINS)
def test_reflection_filter_preserves_the_fixed_native_window(
    raw_dataset: DatasetInfo, tmp_path: Path, frequency: float, bins: int
) -> None:
    """Filtering cannot shorten output to a smaller laser period."""
    dataset, counts = quantized_dataset(
        raw_dataset, tmp_path, frequency, "flat"
    )
    if frequency == 625e6 and bins > 16:
        with pytest.raises(ValueError, match="upsampling is unavailable"):
            time_grid(dataset, bins)
        return
    selected = int(counts.sum())
    removed = int(counts[10:13].sum())
    counts[10:13] = 0
    expected = physical_histogram(counts, frequency, bins)
    result = export_ics_blocks(
        [dataset],
        tmp_path / "filtered",
        IcsExportOptions(
            bins=bins,
            event_flag_mask=256,
            reflection_windows=(ReflectionWindow(dataset.key, 9.5, 12.5),),
        ),
        plane_selection={dataset.key: [0]},
    )[0]
    assert result["status"] == "exported", result
    image = read_ics(Path(result["path"]))
    np.testing.assert_array_equal(image.counts, expected)
    accounting = json.loads(
        Path(result["sidecar"]).read_text(encoding="utf-8")
    )["photonAccounting"]
    assert accounting["selectedPhotons"] == selected
    assert accounting["excludedReflectionPhotons"] == removed
    assert accounting["exportedPhotons"] == int(expected.sum())
    end = 16 if frequency == 625e6 else 128
    assert accounting["excludedOutsideTimeWindow"] == int(counts[end:].sum())


@pytest.mark.parametrize("overflow", [False, True])
def test_grouped_cache_checks_integer_width(raw_dataset, overflow):
    """Promote grouped counts and reject uint32 overflow."""
    dtype = np.uint32 if overflow else np.uint16
    dataset = replace(raw_dataset, laser_frequency_hz=78_125_000.0)
    counts = np.full((128, 1, 1), np.iinfo(dtype).max, dtype=dtype)
    cube = HistogramCube(
        counts=counts,
        events=int(counts.sum(dtype=np.uint64)),
        overflow_events=0,
        period_bins=128,
        decoded_rows=1,
        time_grid=time_grid(dataset, 128),
    )
    output = time_grid(dataset, 16)
    if overflow:
        with pytest.raises(OverflowError, match="exceeds uint32"):
            rebin_cube(cube, 16, output)
    else:
        grouped = rebin_cube(cube, 16, output)
        assert grouped is not None
        assert grouped.counts.dtype == np.uint32
        np.testing.assert_array_equal(
            grouped.counts, np.full((16, 1, 1), 524280)
        )
        assert int(grouped.counts.sum(dtype=np.uint64)) == cube.events
