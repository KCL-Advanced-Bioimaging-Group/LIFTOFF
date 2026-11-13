"""Validate exportable indexed acquisitions, including partial
repeats.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.export_inspection import (
    inspect_ptu,
    read_ics,
    rehistogram_arrivals,
)
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.version import APPLICATION_VERSION
from tests.test_reference_science import REFERENCE, example_path

AUTOFLORESCENCE = next(
    item for item in REFERENCE if item["file"] == "Autofluorescence.lif"
)
CASES = [
    (index, expected, plane)
    for index, expected in enumerate(AUTOFLORESCENCE["datasets"])
    for plane in expected["planes"]
    if expected["metadata"]["dimension_status"].startswith("partial")
    or (index in (0, 3) and plane["plane"] == 5)
]


@pytest.mark.real_data
@pytest.mark.parametrize(
    ("index", "expected", "plane"),
    CASES,
    ids=[
        f"{index}:p{plane['plane']}:m{plane['mask']}"
        for index, _expected, plane in CASES
    ],
)
def test_indexed_exports(
    tmp_path: Path,
    index: int,
    expected: dict,
    plane: dict,
) -> None:
    """Retain every indexed photon without inventing missing raster
    rows.
    """
    path = example_path("Autofluorescence.lif")
    if path is None:
        pytest.skip("Optional example LIF is unavailable")
    dataset = scan_lif(path)[index]
    output = export_ptu_blocks(
        [dataset],
        tmp_path,
        PtuExportOptions(event_flag_mask=plane["mask"]),
        plane_selection={dataset.key: [plane["plane"]]},
    )[0]
    assert output["status"] == "exported", output
    target = Path(output["path"])
    records = inspect_ptu(target)
    assert records.photons == plane["events"]
    period = plane["shape"][0]
    folded = records.microtime[:period].copy()
    folded[-1] += records.microtime[period:].sum(dtype=np.uint64)
    assert folded.tolist() == plane["microtime"]
    assert records.routes == {0: records.photons}
    assert records.monotonic_macrotime
    first, rows = dataset.plane_row_range(plane["plane"])
    assert first >= 0
    logical_lines = (
        rows + dataset.line_repetitions - 1
    ) // dataset.line_repetitions
    assert records.markers[1] == records.markers[2] == logical_lines
    assert (
        records.markers[4]
        == (logical_lines + dataset.height - 1) // dataset.height
    )
    tags = {tag["ident"]: tag["value"] for tag in parse_ptu(target)["tags"]}
    assert tags["CreatorSW_Version"] == APPLICATION_VERSION
    information = json.loads(
        Path(output["sidecar"]).read_text(encoding="utf-8")
    )
    assert information["export"]["indexedEncodedRows"] == rows
    assert (
        information["export"]["nominalEncodedRows"] == dataset.rows_per_plane
    )
    assert (
        information["sourceStorage"]["repetitionStorageModel"]
        == (expected["metadata"]["repetition_storage_model"])
    )
    target.unlink()
    Path(output["sidecar"]).unlink()
    output = export_ics_blocks(
        [dataset],
        tmp_path,
        IcsExportOptions(bins=128, threads=4, event_flag_mask=plane["mask"]),
        plane_selection={dataset.key: [plane["plane"]]},
    )[0]
    assert output["status"] == "exported", output
    target = Path(output["path"])
    image = read_ics(target)
    native = decode_histogram_plane(
        dataset,
        plane["plane"],
        bins=period,
        threads=4,
        event_flag_mask=plane["mask"],
    )
    assert (
        hashlib.sha256(native.counts.astype("<u4").tobytes()).hexdigest()
        == plane["sha256"]
    )
    # Legacy native cubes retain their frozen hash above. New calibrated
    # exports are reconciled with unmodified native PTU arrival values.
    assert dataset.clock_period_s is not None
    rebinned, excluded = rehistogram_arrivals(
        records, image, dataset.clock_period_s
    )
    assert np.array_equal(
        image.counts.sum(axis=(1, 2), dtype=np.uint64), rebinned
    )
    assert int(rebinned.sum()) + excluded == plane["events"]
    target.unlink()
    Path(output["sidecar"]).unlink()
