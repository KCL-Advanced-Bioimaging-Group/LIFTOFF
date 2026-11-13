"""Reject missing indexes in previews and scientific exports."""

import struct
from dataclasses import replace

import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.gui_helpers import _esp_validate_dataset_2
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import decode_histogram_plane
from leica_flim_converter.ptu_export import (
    PtuExportOptions,
    export_ptu_blocks,
    write_dataset_ptu,
)
from tests.compressed_fixture import mixed_compressed_lif
from tests.test_reference_science import example_path


@pytest.mark.parametrize(
    "corruption,reason",
    [
        ("zero_index", "empty"),
        ("control", "control flags"),
        ("bounds", "exceeds"),
        ("row_count", "indexes"),
        ("group", "without row"),
        ("bit_lengths", "bit lengths"),
    ],
)
def test_compressed_descriptor_preflight(tmp_path, corruption, reason):
    """Retain entries with an explicit failure before export."""
    source = mixed_compressed_lif(tmp_path / "damaged.lif")
    first = scan_lif(source)[0]
    content = bytearray(source.read_bytes())
    header = list(struct.unpack_from("<8Q", content, first.block_start))
    start = first.block_start + header[1] + header[2]
    if corruption == "zero_index":
        content[start : start + header[3]] = bytes(header[3])
    elif corruption == "control":
        value = struct.unpack_from("<I", content, start + 4)[0]
        struct.pack_into("<I", content, start + 4, value & 0xBFFFFFFF)
    elif corruption == "bounds":
        header[3] = first.compressed_bytes + 4
    elif corruption == "row_count":
        header[5] += 1
    elif corruption == "group":
        struct.pack_into("<I", content, start, 0x80000010)
    else:
        struct.pack_into("<I", content, start + 8, 0xBFFFFFFF)
    struct.pack_into("<8Q", content, first.block_start, *header)
    source.write_bytes(content)
    for dataset in scan_lif(source):
        assert dataset.repetition_storage_model == "unresolved"
        assert reason in dataset.dimension_status
        with pytest.raises(RuntimeError):
            decode_histogram_plane(dataset, 0, bins=16)
        for exporter in (export_ics_blocks, export_ptu_blocks):
            result = exporter([dataset], tmp_path / "output")[0]
            assert result["status"] == "failed", result
    assert not list((tmp_path / "output").glob("*.ics"))
    assert not list((tmp_path / "output").glob("*.ptu"))


@pytest.mark.parametrize("storage", ["compressed", "lmsraw"])
def test_unresolved_ptu_guard(raw_dataset, tmp_path, storage):
    """An unresolved row model cannot bypass export preflight."""
    dataset = (
        scan_lif(mixed_compressed_lif(tmp_path / "source.lif"))[0]
        if storage == "compressed"
        else raw_dataset
    )
    invalid = replace(
        dataset,
        repetition_storage_model="unresolved",
        dimension_status="Test row layout is unresolved",
    )
    target = tmp_path / "must-not-exist.ptu"
    with pytest.raises(RuntimeError, match="Test row layout"):
        write_dataset_ptu(
            invalid,
            0,
            target,
            PtuExportOptions(),
            progress=lambda _m: None,
            cancelled=lambda: False,
        )
    assert not target.exists()
    assert not target.with_suffix(".ptu.part").exists()


@pytest.mark.parametrize("format_name", ["ics", "ptu"])
def test_invalid_batch_entry_does_not_stop_valid_data(tmp_path, format_name):
    """Keep a batch's valid files while reporting invalid entries."""
    valid = scan_lif(mixed_compressed_lif(tmp_path / "source.lif"))[0]
    invalid = replace(
        valid,
        memory_id="MemBlock_invalid",
        repetition_storage_model="unresolved",
        dimension_status="Test invalid batch entry",
    )
    if format_name == "ics":
        result = export_ics_blocks(
            [invalid, valid], tmp_path / "output", IcsExportOptions(bins=32)
        )
    else:
        result = export_ptu_blocks(
            [invalid, valid], tmp_path / "output", PtuExportOptions()
        )
    assert [r["status"] for r in result] == ["failed", "exported"]


def test_preflight_cache_tracks_layout(raw_dataset):
    """Do not cache success across row-layout changes."""
    assert _esp_validate_dataset_2(raw_dataset)[0]
    changed = replace(
        raw_dataset,
        repetition_storage_model="unresolved",
        dimension_status="Audit layout changed",
    )
    ready, reason = _esp_validate_dataset_2(changed)
    assert not ready
    assert reason == "Audit layout changed"
    assert _esp_validate_dataset_2(raw_dataset)[0]


@pytest.mark.real_data
def test_paneth_seven_has_incomplete_source_payload(tmp_path):
    """Distinguish the real zero-filled source from a reader failure."""
    source = example_path(
        "20251009_morg_noe_1_day4_mENR_CV__differ_CTX_TMRM_nadph.lif"
    )
    if source is None:
        pytest.skip("Optional collaborator LIF is unavailable")
    datasets = [
        d for d in scan_lif(source) if d.acquisition_name == "paneth_ctx555_7"
    ]
    assert len(datasets) == 2
    assert {d.memory_id for d in datasets} == {"MemBlock_8630"}
    first = datasets[0]
    with source.open("rb") as stream:
        # Check the binary record independently of the row reader.
        stream.seek(first.block_start - 48)
        record = stream.read(48)
        assert record[:4] == b"p\x00\x00\x00"
        assert record[22:].decode("utf-16-le") == first.memory_id
        assert struct.unpack_from("<Q", record, 9)[0] == 32 * 1024**2
        header = struct.unpack("<8Q", stream.read(64))
        assert header == (1, 64, 17044590, 5592, 16, 512, 0, 0)
        stream.seek(first.block_start + 16 * 1024**2 - 1)
        assert stream.read(1) != b"\x00"
        # The missing stream suffix, index and footer lie in this half.
        tail = stream.read(16 * 1024**2)
        assert len(tail) == 16 * 1024**2 and not any(tail)
    assert [d.total_photons for d in datasets] == [41562453, 4287088]
    for dataset in datasets:
        assert dataset.repetition_storage_model == "unresolved"
        assert "descriptor table is empty" in dataset.dimension_status
        with pytest.raises(RuntimeError, match="descriptor table is empty"):
            decode_histogram_plane(dataset, 0, bins=32)
        for exporter in (export_ics_blocks, export_ptu_blocks):
            result = exporter([dataset], tmp_path / "output")[0]
            assert result["status"] == "failed"
            assert "descriptor table is empty" in result["error"]
    assert not list((tmp_path / "output").glob("*.ics"))
    assert not list((tmp_path / "output").glob("*.ptu"))
