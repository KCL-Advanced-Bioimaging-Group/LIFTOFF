"""Compare full exports with frozen 2.4 and independent LAS X PTUs."""

from __future__ import annotations

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
from leica_flim_converter.ptu_export import PtuExportOptions, write_dataset_ptu
from leica_flim_converter.version import APPLICATION_VERSION
from tests.test_reference_science import example_path

FIXTURE = Path(__file__).parent / "fixtures/reference_240_exports.json"
REFERENCE = json.loads(FIXTURE.read_text(encoding="utf-8"))


def find_companion(lif: Path, expected: dict) -> Path:
    """Select the LAS X mode and first Z plane."""
    token = {7: "all_photons", 3: "first_photons", 1: "standard"}[
        expected["mask"]
    ]
    candidates = [
        path
        for path in lif.parent.rglob(expected["lasXFilename"])
        if token in str(path).lower().replace(" ", "_")
    ]
    if len(candidates) != 1:
        pytest.fail(f"Expected one LAS X companion: {candidates}")
    return candidates[0]


@pytest.mark.real_data
@pytest.mark.parametrize(
    "expected",
    REFERENCE,
    ids=[f"{case['sample']}:m{case['mask']}" for case in REFERENCE],
)
def test_complete_exports(tmp_path: Path, expected: dict) -> None:
    """Check records, microtimes, markers, overflows and ICS axes."""
    lif = example_path(expected["sample"] + ".lif")
    if lif is None:
        pytest.skip("Optional example LIF is unavailable")
    datasets = scan_lif(lif)
    dataset = next(
        (item for item in datasets if item.memory_id == expected["memory"]),
        datasets[0],
    )
    mask = (
        expected["mask"]
        if dataset.storage_format == "compressed"
        else {7: 256, 3: 512, 1: 1024}[expected["mask"]]
    )
    target = tmp_path / "probe.ptu"
    metadata = write_dataset_ptu(
        dataset,
        0,
        target,
        PtuExportOptions(event_flag_mask=mask),
        progress=lambda _message: None,
        cancelled=lambda: False,
    )
    actual = inspect_ptu(target)
    assert json.loads(json.dumps(actual.metadata())) == expected["ptu"]
    assert metadata["macrotimeInterpretation"] == "synthetic raster clock"
    assert metadata["microtimeInterpretation"] == (
        "native decoded Leica arrival value"
    )
    companion = inspect_ptu(find_companion(lif, expected))
    assert json.loads(json.dumps(companion.metadata())) == expected["lasX"]
    assert actual.photons == companion.photons
    assert np.array_equal(actual.microtime, companion.microtime)
    target.unlink()
    for bins in (128, 256):
        results = export_ics_blocks(
            [dataset],
            tmp_path,
            IcsExportOptions(bins=bins, event_flag_mask=mask, threads=4),
            plane_selection={dataset.key: [0]},
        )
        assert results[0]["status"] == "exported", results
        path = Path(results[0]["path"])
        image = read_ics(path)
        golden = expected[f"ics{bins}"]
        assert list(image.counts.shape) == golden["shape"]
        assert dataset.clock_period_s is not None
        rebinned, excluded = rehistogram_arrivals(
            actual, image, dataset.clock_period_s
        )
        assert np.array_equal(
            image.counts.sum(axis=(1, 2), dtype=np.uint64), rebinned
        )
        assert int(rebinned.sum()) + excluded == actual.photons
        assert image.header["parameter/units"] == ["relative", "m", "m", "s"]
        scales = list(map(float, image.header["parameter/scale"][:3]))
        if dataset.storage_format == "compressed":
            # Legacy golden counts remain valid; spatial calibration
            # now follows Leica's centre-to-centre convention.
            assert scales == pytest.approx(
                [1, 4.814710371819961e-7, 4.814710371819961e-7]
            )
        else:
            assert scales == pytest.approx(
                list(map(float, golden["header"]["parameter/scale"][:3]))
            )
        sidecar = Path(str(path) + ".json")
        information = json.loads(sidecar.read_text(encoding="utf-8"))
        assert information["application"]["version"] == APPLICATION_VERSION
        assert (
            information["photonAccounting"]["selectedPhotons"]
            == actual.photons
        )
        assert (
            information["photonAccounting"]["excludedOutsideTimeWindow"]
            == excluded
        )
        path.unlink()
        sidecar.unlink()
