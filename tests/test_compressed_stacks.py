"""Complete and interrupted compressed multichannel T/Z acquisitions."""

import json
import struct
from itertools import permutations
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.histogram import decode_histogram_cube
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from tests.compressed_stack_fixture import (
    StackSpec,
    compressed_stack_lif,
    expected_stack_cube,
)


@pytest.mark.parametrize("order", list(permutations(("Z", "T", "C"))))
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("recorded", [5, 6])
def test_compressed_stack_layout(tmp_path, order, explicit, recorded):
    """Keep C/T/Z independent for complete and interrupted stacks."""
    spec = StackSpec(order=order, explicit=explicit, recorded=recorded)
    datasets = scan_lif(compressed_stack_lif(tmp_path / "stack.lif", spec))
    for channel, dataset in enumerate(datasets):
        assert dataset.plane_count == recorded
        assert dataset.declared_plane_count == 6
        assert dataset.preview_plane_count == recorded
        assert dataset.frame_count == recorded
        assert dataset.repetition_storage_model == (
            "explicit-line-repeat-rows"
            if explicit
            else "in-row-line-accumulation"
        )
        axes = tuple(axis for axis in order if axis != "C")
        for plane in range(recorded):
            t, z = dataset.plane_indices(plane)
            assert (t, z) == (
                (plane // 3, plane % 3)
                if axes[0] == "Z"
                else (plane % 2, plane // 2)
            )
            for mask in (7, 3, 1):
                native = decode_histogram_plane(
                    dataset, plane, bins=20, event_flag_mask=mask
                )
                np.testing.assert_array_equal(
                    native.counts,
                    expected_stack_cube(spec, plane, channel, mask),
                )
        overview = decode_histogram_cube(dataset, bins=20)
        python = decode_histogram_cube(dataset, bins=20, prefer_native=False)
        expected = sum(
            expected_stack_cube(spec, plane, channel, 7)
            for plane in range(recorded)
        )
        np.testing.assert_array_equal(overview.counts, expected)
        np.testing.assert_array_equal(python.counts, expected)
        with pytest.raises(IndexError):
            dataset.plane_row_range(recorded)


@pytest.mark.parametrize("mask", [7, 3, 1])
@pytest.mark.parametrize("explicit", [False, True])
def test_partial_stack_exports(tmp_path, mask, explicit):
    """Export recorded planes with exact bins and source coverage."""
    spec = StackSpec(order=("C", "T", "Z"), explicit=explicit)
    datasets = scan_lif(compressed_stack_lif(tmp_path / "stack.lif", spec))
    images = export_ics_blocks(
        datasets,
        tmp_path / "ics",
        options=IcsExportOptions(bins=32, event_flag_mask=mask),
    )
    ptus = export_ptu_blocks(
        datasets,
        tmp_path / "ptu",
        options=PtuExportOptions(event_flag_mask=mask),
    )
    assert len(images) == len(ptus) == 10
    for position, (image, ptu) in enumerate(zip(images, ptus, strict=True)):
        assert image["status"] == ptu["status"] == "exported"
        channel, plane = divmod(position, 5)
        expected = expected_stack_cube(spec, plane, channel, mask, bins=32)
        np.testing.assert_array_equal(
            read_ics(Path(image["path"])).counts, expected
        )
        photons = inspect_ptu(Path(ptu["path"]))
        assert photons.photons == int(expected.sum())
        assert photons.markers[4] == spec.frames
        for result in (image, ptu):
            sidecar = json.loads(
                Path(result["sidecar"]).read_text(encoding="utf-8")
            )
            # PTU export embeds the stream metadata in its sidecar.
            coverage = (
                sidecar.get("planeCoverage")
                or sidecar["export"]["planeCoverage"]
            )
            assert coverage["declaredPlaneCount"] == 6
            assert coverage["recordedPlaneCount"] == 5
            assert coverage["absentTrailingPlaneCount"] == 1


@pytest.mark.parametrize("damage", ["extra-plane", "nonfinite", "row-deficit"])
def test_partial_stack_requires_corroboration(tmp_path, damage):
    """Reject missing rows when reference evidence does not agree."""
    spec = StackSpec(row_deficit=int(damage == "row-deficit"))
    source = compressed_stack_lif(tmp_path / "stack.lif", spec)
    dataset = scan_lif(source)[1]
    if damage != "row-deficit":
        assert dataset.intensity_start is not None
        with source.open("r+b") as stream:
            stream.seek(dataset.intensity_start + 5 * 60)
            stream.write(
                struct.pack("<f", 1 if damage == "extra-plane" else np.nan)
            )
    for dataset in scan_lif(source):
        assert dataset.repetition_storage_model == "unresolved"
        assert dataset.recorded_plane_count is None


def test_dark_trailing_planes_do_not_choose_a_repetition_model(tmp_path):
    """Empty references cannot distinguish two valid row models."""
    source = compressed_stack_lif(
        tmp_path / "ambiguous.lif", StackSpec(recorded=4)
    )
    datasets = scan_lif(source)
    with source.open("r+b") as stream:
        for dataset in datasets:
            for start in dataset.intensity_plane_starts[2:]:
                stream.seek(start)
                stream.write(bytes(60))
    for dataset in scan_lif(source):
        # Four in-row planes or two explicit-repeat planes both fit.
        assert dataset.repetition_storage_model == "unresolved"
        assert dataset.recorded_plane_count is None
