"""Regression tests for event semantics and native/Python
consistency.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import DatasetInfo
from leica_flim_converter.event_flags import (
    filename_suffix,
    markers_from_mask,
    normalize_selection,
)
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import (
    PtuExportCancelled,
    PtuExportOptions,
    write_dataset_ptu,
)


@pytest.mark.parametrize(
    ("mask", "expected"),
    [
        (256, ((2, 10, 13), (5, 8, 12))),
        (512, ((2, 10), (8, 12))),
        (1024, ((), (8,))),
    ],
)
@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("threads", [1, 4])
def test_selection_vectors(
    raw_dataset: DatasetInfo,
    mask: int,
    expected: tuple[tuple[int, ...], tuple[int, ...]],
    native: bool,
    threads: int,
) -> None:
    """Reject short deltas and terminal cycles without losing row
    state.
    """
    cube = decode_histogram_plane(
        raw_dataset,
        0,
        bins=16,
        threads=threads,
        event_flag_mask=mask,
        prefer_native=native,
    )
    expected_cube = np.zeros((16, 2, 2), dtype=np.uint32)
    for row, arrivals in enumerate(expected):
        expected_cube[list(arrivals), row, 0] = 1
    np.testing.assert_array_equal(cube.counts, expected_cube)
    assert cube.events == sum(map(len, expected))
    assert cube.event_flag_mask == mask


def test_shared_named_modes() -> None:
    """Names retain their meaning when switching storage grammars."""
    for compressed, raw in zip((7, 3, 1), (256, 512, 1024), strict=True):
        assert normalize_selection(compressed, "lmsraw") == raw
        assert normalize_selection(raw, "compressed") == compressed
        assert filename_suffix(compressed) == filename_suffix(raw)
    assert markers_from_mask(7) == (168, 160, 176)
    assert markers_from_mask(3) == (168, 160)
    assert markers_from_mask(1) == (168,)


def test_ptu_vector_records(raw_dataset: DatasetInfo, tmp_path: Path) -> None:
    """Large raster ticks produce valid overflow and marker records."""
    target = tmp_path / "overflow.ptu"
    result = write_dataset_ptu(
        raw_dataset,
        0,
        target,
        PtuExportOptions(pixel_ticks=1024, event_flag_mask=256),
        progress=lambda _message: None,
        cancelled=lambda: False,
    )
    parsed = parse_ptu(target, parse_records=True)
    assert result["photons"] == parsed["records"]["photons"] == 6
    assert parsed["records"]["markerBits"] == {4: 1, 1: 2, 2: 2}
    assert parsed["records"]["channels"] == {0: 6}
    assert parsed["records"]["overflowWraps"] == 4


def test_ptu_cancellation_cleanup(
    raw_dataset: DatasetInfo, tmp_path: Path
) -> None:
    """Cancellation never publishes a partial output."""
    target = tmp_path / "cancelled.ptu"
    with pytest.raises(PtuExportCancelled):
        write_dataset_ptu(
            raw_dataset,
            0,
            target,
            PtuExportOptions(event_flag_mask=256),
            progress=lambda _message: None,
            cancelled=lambda: True,
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()
