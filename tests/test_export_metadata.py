"""Standalone metadata, original evidence and spatial calibration."""

from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import read_ics
from leica_flim_converter.ics import write_ics
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.optical_metadata import EmissionBand
from leica_flim_converter.ptu import parse_ptu
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.reflection_export import ReflectionWindow
from leica_flim_converter.spatial_metadata import dimension_calibration
from tests.compressed_fixture import mixed_compressed_lif


def _ics_metadata(path: Path) -> dict:
    header = read_ics(path).header
    chunks = sorted(
        key for key in header if key.startswith("history/LeicaMetadata_")
    )
    return json.loads("".join(header[key][0] for key in chunks))


@pytest.mark.parametrize("compression", ["gzip", "uncompressed"])
@pytest.mark.parametrize("missing", [None, 0, -1, float("nan"), float("inf")])
def test_unknown_axis_uses_pixels(raw_dataset, tmp_path, missing, compression):
    """Unknown X must not erase valid Y or invent a metric scale."""
    dataset = replace(raw_dataset, pixel_size_x_m=missing, pixel_size_y_m=2e-6)
    counts = np.arange(64, dtype=np.uint16).reshape(16, 2, 2)
    path = tmp_path / "mixed.ics"
    write_ics(path, counts, dataset, compression=compression)
    image = read_ics(path)
    np.testing.assert_array_equal(image.counts, counts)
    assert image.header["parameter/units"] == ["relative", "m", "pixel", "s"]
    assert list(map(float, image.header["parameter/scale"]))[1:3] == [2e-6, 1]
    assert image.header["history/units"] == ["pixel m s"]
    assert list(map(float, image.header["history/extents"][0].split()))[
        :2
    ] == [2, 4e-6]
    axis = _ics_metadata(path)["spatialCalibration"]["axes"]["x"]
    assert axis["spacingMetres"] is None
    assert axis["status"] == "unavailable"


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"Length": "2.460317e-4", "NumberOfElements": "512", "Unit": "m"},
            4.814710371819961e-7,
        ),
        ({"Length": "8", "NumberOfElements": "5", "Unit": "um"}, 2e-6),
        ({"Length": "8", "NumberOfElements": "1", "Unit": "m"}, None),
        ({"Length": "nan", "NumberOfElements": "5", "Unit": "m"}, None),
        ({"Length": "-8", "NumberOfElements": "5", "Unit": "m"}, None),
        ({"Length": "8", "NumberOfElements": "5", "Unit": "pixel"}, None),
        ({"Length": "8", "NumberOfElements": "5"}, None),
    ],
)
def test_dimension_calibration_keeps_source(record, expected):
    """Centre-to-centre spacing requires multiple samples and units."""
    calibration = dimension_calibration("x", record)
    assert calibration["sourceValues"] == record
    if expected is None:
        assert calibration["spacingMetres"] is None
    else:
        assert calibration["spacingMetres"] == pytest.approx(expected)


def test_catalogue_calibration_and_original_xml(tmp_path):
    """Parse source calibration and settings after photon memory."""
    source = mixed_compressed_lif(tmp_path / "dimensions.lif")
    # The independent fixture has 3 X samples and 2 Y samples.
    data = source.read_bytes()
    end = 13 + struct.unpack_from("<I", data, 9)[0] * 2
    xml = data[13:end].decode("utf-16le")
    xml = xml.replace(
        'Length="3e-6" BytesInc="4"',
        'Length="3e-6" Unit="m" BytesInc="4"',
    )
    xml = xml.replace(
        'Length="2e-6" BytesInc="12"',
        'Length="2e-6" Unit="m" BytesInc="12"',
    )
    encoded = xml.encode("utf-16le")
    prefix = struct.pack("<IIBI", 112, len(encoded) + 5, 42, len(encoded) // 2)
    source.write_bytes(prefix + encoded + data[end:])
    dataset = scan_lif(source)[0]
    assert dataset.pixel_size_x_m == pytest.approx(1.5e-6)
    assert dataset.pixel_size_y_m == pytest.approx(2e-6)
    assert dataset.spatial_sources[0]["sourceValues"]["Length"] == "3e-6"
    assert dataset.source_acquisition_xml is not None
    assert dataset.source_acquisition_xml.endswith("</Element>")
    assert '<Element Name="Intensity">' in dataset.source_acquisition_xml


@pytest.mark.parametrize("pixel_x", [None, 1e-6, 2e-6, float("nan")])
def test_standalone_export_metadata(
    raw_dataset: DatasetInfo, tmp_path: Path, pixel_x
):
    """Read files without JSON and compare the retained metadata."""
    original_xml = '<Element Name="source"><Objective NA="1.40"/></Element>'
    dataset = replace(
        raw_dataset,
        series_name="Cells α\t\nend\t series " + "é" * 600,
        channel_name="566 - 630 nm",
        detector_name="HyD S 2",
        excitation_wavelengths_nm=(555.4,),
        emission_filter_band="566 - 630 nm",
        emission_band_metadata=EmissionBand(
            ("565.55", "630.123456789012345678"),
            ("LeftWorld", "RightWorld"),
            "2",
        ),
        pixel_size_x_m=pixel_x,
        source_acquisition_xml=original_xml,
        spatial_sources=(
            dimension_calibration(
                "z",
                {
                    "Length": "4e-6",
                    "NumberOfElements": "3",
                    "Origin": "-1e-6",
                    "Unit": "m",
                },
            ),
        ),
    )
    results = [
        export_ics_blocks(
            [dataset],
            tmp_path,
            IcsExportOptions(bins=32, event_flag_mask=256),
            filenames={dataset.key: "metadata.ics"},
        )[0],
        export_ptu_blocks(
            [dataset],
            tmp_path,
            PtuExportOptions(event_flag_mask=256),
            filenames={dataset.key: "metadata.ptu"},
        )[0],
    ]
    for result in results:
        assert result["status"] == "exported", result.get("error")
        sidecar_path = Path(result["sidecar"])
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar_path.rename(sidecar_path.with_suffix(".hidden"))
        path = Path(result["path"])
        if path.suffix == ".ics":
            embedded = _ics_metadata(path)
            assert sidecar["interpretation"]["unavailable"] == (
                ["pixelSizeXMetres"]
                if pixel_x is None or np.isnan(pixel_x)
                else []
            )
            header_bytes = path.read_bytes().split(b"end\t\n", 1)[0]
            history = [
                line
                for line in header_bytes.splitlines(keepends=True)
                if line.startswith(b"history\t")
            ]
            assert max(map(len, history)) <= 220
        else:
            parsed = parse_ptu(path, parse_records=True)
            tags = {tag["ident"]: tag["value"] for tag in parsed["tags"]}
            encoded_metadata = tags["Leica_Acquisition"]
            assert isinstance(encoded_metadata, str)
            embedded = json.loads(encoded_metadata)
            assert ("ImgHdr_PixResol" in tags) == (pixel_x == 1e-6)
            assert tags["Leica_SpatialUnitX"] == (
                "m"
                if pixel_x is not None and np.isfinite(pixel_x)
                else "pixel"
            )
            assert parsed["dataOffset"] % 8 == 0
        assert embedded == sidecar["acquisitionMetadata"]
        assert embedded["leicaNames"]["series"] == dataset.series_name
        assert embedded["opticalMetadata"] == sidecar["opticalMetadata"]
        assert (
            embedded["spatialCalibration"]["axes"]["z"]["spacingMetres"]
            == 2e-6
        )
        assert embedded["plane"]["linearIndexZeroBased"] == 0
        assert embedded["eventSelection"]
        assert sidecar["sourceMetadata"]["acquisitionXml"] == original_xml
        assert (
            sidecar["sourceMetadata"]["spatialCalibration"][0]["sourceValues"][
                "Origin"
            ]
            == "-1e-6"
        )


def test_integrated_and_filtered_metadata(raw_dataset, tmp_path):
    """Embed integration identity and export-filter boundaries."""
    window = ReflectionWindow(raw_dataset.key, 1, 3)
    results = export_ics_blocks(
        [raw_dataset],
        tmp_path,
        IcsExportOptions(
            bins=32,
            event_flag_mask=256,
            dimension_mode="integrate",
            reflection_windows=(window,),
        ),
    )
    assert results[0]["status"] == "exported", results
    metadata = _ics_metadata(Path(results[0]["path"]))
    assert metadata["plane"]["mode"] == "integrate"
    assert metadata["plane"]["linearIndexZeroBased"] is None
    assert metadata["reflectionFilter"]["enabled"]
    assert metadata["histogramTiming"]["bins"] == 32
