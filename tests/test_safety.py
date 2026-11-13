"""Validate bounded parsing, overflow protection and calibrated
exports.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import patent_guided_deflate_attack as codec
from leica_flim_converter.catalog import DatasetInfo, IndexCancelled, scan_lif
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.histogram_core import (
    DecodeCancelled,
    HistogramAccumulator,
)
from leica_flim_converter.ics import IcsExportCancelled, write_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.version import (
    APPLICATION_VERSION,
    application_metadata,
)


@pytest.mark.parametrize("level", [0, 6, 9])
@pytest.mark.parametrize("strategy", [zlib.Z_DEFAULT_STRATEGY, zlib.Z_FIXED])
def test_deflate_reference_expansion(level: int, strategy: int) -> None:
    """Stored and Huffman streams agree with the independent zlib
    codec.
    """
    payload = bytes(range(256)) * 30 + b"AAAAABBBBB" * 300
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15, 8, strategy)
    encoded = compressor.compress(payload) + compressor.flush()
    parsed = codec.parse_deflate(encoded, 0)
    assert parsed["error"] is None
    assert parsed["final"]
    assert parsed["output"] == zlib.decompress(encoded, -15) == payload
    limited = codec.parse_deflate(encoded, 0, max_output=100)
    assert limited["error"]["message"] == "output limit"
    assert len(limited["output"]) <= 101
    truncated = codec.parse_deflate(encoded[:-5], 0)
    assert truncated["error"] is not None
    assert not truncated["final"]


def test_uint32_promotion_and_overflow() -> None:
    """Repeated photons promote counts before narrow integer
    overflow.
    """
    accumulator = HistogramAccumulator(1, 1, 1, 1)
    accumulator.add_row({"line": 0, "tokens": b"\xa8" + b"\x00" * 70000})
    cube = accumulator.finish()
    assert cube.counts.dtype == np.uint32
    assert cube.events == cube.counts[0, 0, 0] == 70000
    accumulator.counts[0, 0, 0] = np.iinfo(np.uint32).max - 1
    with pytest.raises(OverflowError, match="uint32"):
        accumulator.add_row({"line": 0, "tokens": b"\xa8\x00\x00\x00"})
    assert accumulator.counts[0, 0, 0] == np.iinfo(np.uint32).max - 1


@pytest.mark.parametrize("compression", ["gzip", "uncompressed"])
@pytest.mark.parametrize("dtype", [np.uint16, np.uint32])
def test_ics_axes_and_calibration(
    raw_dataset: DatasetInfo,
    tmp_path: Path,
    compression: str,
    dtype: type,
) -> None:
    """Non-square ICS data retains axes, integer width and physical
    units.
    """
    dataset = replace(raw_dataset, width=3)
    counts = np.arange(96, dtype=dtype).reshape(16, 2, 3)
    target = tmp_path / "calibrated.ics"
    write_ics(target, counts, dataset, compression=compression)
    decoded = read_ics(target)
    assert np.array_equal(decoded.counts, counts)
    assert decoded.header["parameter/units"] == ["relative", "m", "m", "s"]
    scales = list(map(float, decoded.header["parameter/scale"]))
    assert scales[1:3] == pytest.approx([1e-6, 1e-6])
    assert scales[3] == pytest.approx(1e-10, rel=1e-12, abs=0)


def test_ics_cancellation_cleanup(raw_dataset: DatasetInfo, tmp_path: Path):
    """Cancelled ICS payloads are never published."""
    target = tmp_path / "cancelled.ics"
    with pytest.raises(IcsExportCancelled):
        write_ics(
            target,
            np.zeros((16, 2, 2), dtype=np.uint16),
            raw_dataset,
            cancelled=lambda: True,
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


@pytest.mark.parametrize("native", [False, True])
def test_decode_cancellation(raw_dataset: DatasetInfo, native: bool) -> None:
    """Both decoding backends stop at their bounded cancellation
    boundary.
    """
    with pytest.raises(DecodeCancelled):
        decode_histogram_plane(
            raw_dataset,
            0,
            bins=16,
            event_flag_mask=256,
            prefer_native=native,
            cancelled=lambda: True,
        )


def test_cached_selection_is_checked(
    raw_dataset: DatasetInfo,
    tmp_path: Path,
) -> None:
    """A preview for another photon mode cannot contaminate an
    export.
    """
    cube = decode_histogram_plane(
        raw_dataset, 0, bins=128, event_flag_mask=256
    )
    results = export_ics_blocks(
        [raw_dataset],
        tmp_path,
        IcsExportOptions(event_flag_mask=512),
        cached_cubes={raw_dataset.key: cube},
    )
    assert results[0]["status"] == "exported", results
    counts = read_ics(Path(results[0]["path"])).counts
    assert int(counts.sum(dtype=np.uint64)) == 4
    assert cube.events == 6


def test_partial_indexed_timelapse_ics(raw_dataset, tmp_path):
    """Export partial planes and preserve their provenance."""
    dataset = replace(
        raw_dataset,
        t_count=2,
        t_stride=1,
        frame_count=2,
        plane_row_starts=(0, 1),
        dimension_status=(
            "partial indexed acquisition: 2/4 frame rows; "
            "frame/line indexes confirmed"
        ),
    )
    results = export_ics_blocks([dataset], tmp_path, IcsExportOptions(bins=32))
    assert len(results) == 2
    for plane, result in enumerate(results):
        assert result["status"] == "exported", result
        cube = decode_histogram_plane(
            dataset, plane, bins=32, event_flag_mask=256
        )
        image = read_ics(Path(result["path"]))
        np.testing.assert_array_equal(image.counts, cube.counts)
        metadata = json.loads(
            Path(result["sidecar"]).read_text(encoding="utf-8")
        )
        assert metadata["plane"]["encodedRowCount"] == 1
        assert metadata["plane"]["tIndexZeroBased"] == plane
        assert metadata["dimensions"]["dimensionStatus"].startswith("partial")


def test_filename_collision_and_provenance(
    raw_dataset: DatasetInfo,
    tmp_path: Path,
) -> None:
    """Batch names retain selection suffixes and source
    reconstruction.
    """
    options = PtuExportOptions(event_flag_mask=512)
    first = export_ptu_blocks([raw_dataset], tmp_path, options)[0]
    second = export_ptu_blocks([raw_dataset], tmp_path, options)[0]
    assert first["status"] == second["status"] == "exported"
    assert "first-photons" in Path(first["path"]).stem.lower()
    assert Path(second["path"]).stem == Path(first["path"]).stem + "_2"
    information = json.loads(
        Path(first["sidecar"]).read_text(encoding="utf-8")
    )
    assert information["application"] == application_metadata()
    assert information["application"]["version"] == APPLICATION_VERSION
    assert "synthetic raster macrotime" in information["inferred"]
    skipped = export_ptu_blocks(
        [raw_dataset],
        tmp_path,
        replace(options, collision="skip"),
    )[0]
    assert skipped["status"] == "skipped"


def test_malformed_index_and_cancel(tmp_path: Path) -> None:
    """Malformed inputs fail explicitly while cancellation stays
    distinct.
    """
    path = tmp_path / "bad.lif"
    path.write_bytes(b"invalid Leica data")
    with pytest.raises((ValueError, RuntimeError)):
        scan_lif(path)
    with pytest.raises(IndexCancelled):
        scan_lif(path, cancelled=lambda: True)


def test_ics_mid_write_cancellation(
    raw_dataset: DatasetInfo, tmp_path: Path
) -> None:
    """A partially written ICS is removed after progress triggers
    cancel.
    """
    target = tmp_path / "interrupted.ics"
    steps: list[int] = []
    with pytest.raises(IcsExportCancelled):
        write_ics(
            target,
            np.zeros((128, 2, 2), dtype=np.uint16),
            raw_dataset,
            cancelled=lambda: bool(steps),
            progress=lambda done, _total: steps.append(done),
        )
    assert steps and 0 < steps[0] < 128
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()
