"""Recognised field encodings and complete readable export bundles."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter import export_companions
from leica_flim_converter.export_inspection import inspect_ptu, read_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.optical_metadata import EmissionBand
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.version import APPLICATION_VERSION


def _export(dataset, destination, kind, collision="suffix"):
    if kind == "ics":
        return export_ics_blocks(
            [dataset],
            destination,
            IcsExportOptions(
                bins=32, event_flag_mask=256, collision=collision
            ),
            filenames={dataset.key: "probe.ics"},
        )[0]
    return export_ptu_blocks(
        [dataset],
        destination,
        PtuExportOptions(event_flag_mask=256, collision=collision),
        filenames={dataset.key: "probe.ptu"},
    )[0]


@pytest.mark.parametrize("kind", ["ics", "ptu"])
def test_report_bundle_and_recognised_headers(raw_dataset, tmp_path, kind):
    """Inspect reports, native fields and retained source text."""
    dataset = replace(
        raw_dataset,
        detector_name="HyD S 2",
        channel_name="566 - 630 nm",
        excitation_wavelengths_nm=(555.4,),
        emission_filter_band="566 - 630 nm",
        emission_band_metadata=EmissionBand(
            ("565.55", "630.123456789012345678"),
            ("LeftWorld", "RightWorld"),
            "2",
        ),
        series_name='=SUM(1,2) <script>alert("α")</script>',
        source_acquisition_xml='<Objective Name="Original &amp; exact"/>',
    )
    result = _export(dataset, tmp_path, kind)
    assert result["status"] == "exported", result.get("error")
    target = Path(result["path"])
    sidecar = json.loads(Path(result["sidecar"]).read_text(encoding="utf-8"))
    assert (
        sidecar["sourceMetadata"]["acquisitionXml"]
        == dataset.source_acquisition_xml
    )
    reports = result["metadataReports"]
    assert Path(reports["csv"]).read_bytes().startswith(b"\xef\xbb\xbf")
    with Path(reports["csv"]).open(encoding="utf-8-sig", newline="") as stream:
        entries = list(csv.DictReader(stream))
    rows = {row["Field"]: row for row in entries}
    assert rows["Application"]["Value"] == "LIFTOFF"
    assert rows["Application version"]["Value"] == APPLICATION_VERSION
    assert rows["Native photon-arrival increment"]["Value"] == "100"
    assert rows["Native photon-arrival increment"]["Unit"] == "ps"
    assert rows["X sample spacing"]["Value"] == "1"
    assert rows["X sample spacing"]["Unit"] == "µm"
    assert rows["Excitation source values"]["Value"] == "555.4"
    assert rows["Emission source bounds"]["Value"].endswith(
        "630.123456789012345678"
    )
    assert rows["Series"]["Value"].startswith("'=SUM")
    report = Path(reports["html"]).read_text(encoding="utf-8")
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "α" in report
    assert "µm" in report
    assert "Original &amp; exact" not in report
    assert target.name + ".json" in report
    assert "Source T index (zero-based)" in report
    assert not list(tmp_path.glob("*.part"))
    if kind == "ics":
        with target.open("rb") as stream:
            header = []
            while (line := stream.readline()) != b"end\t\n":
                assert line
                header.append(line.decode("ascii"))
        text = "".join(header)
        assert "history\tsoftware\tLIFTOFF\n" in text
        assert "sensor\ts_params\tLambdaEx\t555\n" in text
        assert "sensor\ts_params\tLambdaEm\t" not in text
        assert "sensor\ts_params\tChannels\t1\n" in text
        assert "history\tdetector\tHyD S 2\n" in text
        assert "history\tfilterset emm name\t566 - 630 nm\n" in text
        assert rows["Exported arrival-bin width"]["Value"] == "50"
        image = read_ics(target)
        assert float(image.header["parameter/scale"][-1]) == pytest.approx(
            50e-12
        )
        assert int(image.counts.sum()) == 6
    else:
        tags = {
            tag["ident"]: tag["value"] for tag in parse_ptu(target)["tags"]
        }
        assert tags["CreatorSW_Name"] == "LIFTOFF"
        assert tags["CreatorSW_Version"] == APPLICATION_VERSION
        comment = tags["File_Comment"]
        assert isinstance(comment, str)
        assert "Excitation: 555 nm" in comment
        assert "Emission: 566 - 630 nm" in comment
        assert "raster macrotime is synthetic" in comment
        assert tags["ImgHdr_PixResol"] == 1
        assert tags["MeasDesc_Resolution"] == 1e-10
        assert rows["PTU raster timeline"]["Value"] == "Synthetic"
        assert inspect_ptu(target).photons == 6
    assert (
        sidecar["acquisitionMetadata"]["headerMappings"]["format"].lower()
        == kind
    )


def test_multiple_excitation_and_unknown_axes(raw_dataset, tmp_path):
    """No scalar wavelength or physical pixel size is invented."""
    dataset = replace(
        raw_dataset, excitation_wavelengths_nm=(488, 555), pixel_size_x_m=None
    )
    result = _export(dataset, tmp_path, "ics")
    assert result["status"] == "exported", result
    header = Path(result["path"]).read_bytes().split(b"end\t\n")[0]
    assert b"sensor\ts_params\tLambdaEx\t" not in header
    assert b"parameter\tunits\trelative\tm\tpixel\ts" in header
    with Path(result["metadataReports"]["csv"]).open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        rows = {row["Field"]: row for row in csv.DictReader(stream)}
    assert rows["X sample spacing"]["Unit"] == "pixel"
    assert rows["X sample spacing"]["Status"] == "uncalibrated"
    assert rows["Emission band"]["Status"] == "unavailable"


@pytest.mark.parametrize("kind", ["ics", "ptu"])
@pytest.mark.parametrize("companion", ["csv", "html", "json", "part"])
def test_report_collision_preserves_existing(
    raw_dataset, tmp_path, kind, companion
):
    """A report without its data still reserves its output basename."""
    target = tmp_path / f"probe.{kind}"
    occupied = (
        target.with_name(target.name + ".part")
        if companion == "part"
        else export_companions.companion_paths(target)[companion]
    )
    occupied.write_text("Existing report", encoding="utf-8")
    skipped = _export(raw_dataset, tmp_path, kind, "skip")
    assert skipped["status"] == "skipped"
    assert occupied.read_text(encoding="utf-8") == "Existing report"
    suffixed = _export(raw_dataset, tmp_path, kind)
    assert suffixed["status"] == "exported", suffixed
    assert Path(suffixed["path"]).stem == "probe_2"
    assert occupied.read_text(encoding="utf-8") == "Existing report"


@pytest.mark.parametrize("kind", ["ics", "ptu"])
@pytest.mark.parametrize("failure", ["render", "publish"])
def test_failed_report_removes_current_bundle(
    raw_dataset, tmp_path, monkeypatch, kind, failure
):
    """Report failures cannot publish misleading successful exports."""
    completed = _export(raw_dataset, tmp_path, kind)
    assert completed["status"] == "exported", completed
    original = {
        path: path.read_bytes() for path in tmp_path.glob(f"probe.{kind}*")
    }
    if failure == "render":

        def fail_render(_rows):
            raise OSError("Report failure")

        monkeypatch.setattr(export_companions, "csv_report", fail_render)
    else:
        replace_file = export_companions.os.replace

        def fail_publish(source, destination):
            if str(destination).endswith(".metadata.html"):
                raise OSError("Report failure")
            return replace_file(source, destination)

        monkeypatch.setattr(export_companions.os, "replace", fail_publish)
    failed = _export(raw_dataset, tmp_path, kind)
    assert failed["status"] == "failed"
    assert "Report failure" in failed["error"]
    assert not list(tmp_path.glob("probe_2*"))
    assert all(path.read_bytes() == value for path, value in original.items())


def test_histogram_and_record_payloads_are_unchanged(raw_dataset, tmp_path):
    """Reports and header GUIDs do not affect photon payloads."""
    first = _export(raw_dataset, tmp_path, "ptu")
    second = _export(raw_dataset, tmp_path, "ptu")
    assert (
        inspect_ptu(Path(first["path"])).record_sha256
        == inspect_ptu(Path(second["path"])).record_sha256
    )
    first = _export(raw_dataset, tmp_path, "ics")
    second = _export(raw_dataset, tmp_path, "ics")
    np.testing.assert_array_equal(
        read_ics(Path(first["path"])).counts,
        read_ics(Path(second["path"])).counts,
    )
