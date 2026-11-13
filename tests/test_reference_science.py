"""Source-run scientific regressions against retained 2.4 evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import DatasetInfo, scan_lif
from leica_flim_converter.native_decoder import decode_histogram_plane

FIXTURE = Path(__file__).parent / "fixtures" / "reference_240_science.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))["files"]
METADATA_CORRECTIONS = json.loads(
    (FIXTURE.parent / "catalogue_metadata_corrections.json").read_text(
        encoding="utf-8"
    )
)
CASES = [
    (file["file"], index, plane)
    for file in REFERENCE
    for index, dataset in enumerate(file["datasets"])
    for plane in dataset["planes"]
]


def example_path(filename: str) -> Path | None:
    """Find optional external data without making it a runtime
    dependency.
    """
    configured = os.environ.get("LEICA_EXAMPLE_DATA_DIR")
    roots = (
        [Path(configured)]
        if configured
        else [
            Path.home()
            / "Documents"
            / "Leica_Interrogator_2.2.0_Windows_x86_64",
            Path.home()
            / "Documents"
            / "Leica_Interrogator_2.3.0_Windows_x86_64",
            Path.home()
            / "Documents"
            / "Leica_Interrogator_2.4.0_Windows_x86_64",
        ]
    )
    return next(
        (
            path
            for root in roots
            if root.is_dir()
            for path in root.rglob(filename)
        ),
        None,
    )


@pytest.fixture(scope="module", name="catalogues")
def catalogues_fixture() -> dict[str, list[DatasetInfo]]:
    """Index each available file once while retaining channel order."""
    return {
        item["file"]: scan_lif(path)
        for item in REFERENCE
        if (path := example_path(item["file"])) is not None
    }


@pytest.mark.real_data
@pytest.mark.parametrize(
    "reference", REFERENCE, ids=[item["file"] for item in REFERENCE]
)
def test_catalogue_metadata(
    catalogues: dict[str, list[DatasetInfo]], reference: dict
) -> None:
    """Keep calibration, dimensions, detectors, and partial indexes
    stable.
    """
    if reference["file"] not in catalogues:
        pytest.skip("Optional example LIF is unavailable")
    datasets = catalogues[reference["file"]]
    assert len(datasets) == len(reference["datasets"])
    for dataset, expected in zip(datasets, reference["datasets"], strict=True):
        corrections = METADATA_CORRECTIONS.get(reference["file"], {}).get(
            dataset.memory_id, {}
        )
        for key, value in expected["metadata"].items():
            actual = getattr(dataset, key)
            assert json.loads(json.dumps(actual)) == corrections.get(
                key, value
            ), key


@pytest.mark.real_data
@pytest.mark.parametrize("threads", [1, 4, 16])
@pytest.mark.parametrize(
    ("filename", "index", "expected"),
    CASES,
    ids=[
        f"{name}:{index}:p{plane['plane']}:m{plane['mask']}"
        for name, index, plane in CASES
    ],
)
def test_complete_histogram_parity(
    catalogues: dict[str, list[DatasetInfo]],
    filename: str,
    index: int,
    expected: dict,
    threads: int,
) -> None:
    """Compare every photon bin and pixel, not only aggregate totals."""
    if filename not in catalogues:
        pytest.skip("Optional example LIF is unavailable")
    dataset = catalogues[filename][index]
    options = {"event_flag_mask": expected["mask"], "threads": threads}
    if "error" in expected:
        with pytest.raises(RuntimeError) as error:
            decode_histogram_plane(dataset, expected["plane"], **options)
        assert str(error.value) == expected["error"]
        return
    cube = decode_histogram_plane(
        dataset, expected["plane"], bins=expected["shape"][0], **options
    )
    assert cube.events == expected["events"]
    assert cube.overflow_events == expected["overflow"]
    assert list(cube.counts.shape) == expected["shape"]
    assert (
        hashlib.sha256(cube.counts.astype("<u4").tobytes()).hexdigest()
        == expected["sha256"]
    )
    assert (
        cube.counts.sum(axis=(1, 2), dtype=np.uint64).tolist()
        == expected["microtime"]
    )
    assert [
        cube.spatial_transform,
        cube.spatial_alignment_confirmed,
    ] == expected["alignment"]
