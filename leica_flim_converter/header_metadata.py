"""Conventional export fields with explicit mapping limitations."""

from __future__ import annotations

from .acquisition_metadata import ICS_HISTORY_RECORD_BYTES


def _ics_text(value) -> str:
    return (
        " ".join(str(value).split())
        .encode("ascii", "backslashreplace")
        .decode("ascii")
    )


def ics_standard_header(metadata: dict) -> str:
    """Emit defined ICS fields and record their mapping routes."""
    names = metadata["leicaNames"]
    optics = metadata["opticalMetadata"]
    fields = {
        "history\ttitle": names["acquisition"],
        "history\tdetector": names["detector"],
        "history\tfilterset emm name": metadata["sequence"]["emissionBand"],
        "sensor\ts_params\tChannels": 1,
        "sensor\ts_params\tDescription": names["channel"],
        "sensor\ts_params\tDetectorModel": names["detector"],
    }
    mappings = {
        "spatialAxes": "parameter scale / units (Y, X)",
        "photonArrivalAxis": (
            "parameter scale / units (t, seconds); history type Time Resolved"
        ),
        "acquisitionName": "history title",
        "detector": "history detector; sensor s_params DetectorModel",
        "channelName": "sensor s_params Description",
        "emissionBand": "history filterset emm name (range label)",
        "excitationWavelength": (
            "extensions only: multiple or unavailable wavelengths"
        ),
        "emissionWavelength": (
            "extensions only: a band is not a single wavelength"
        ),
        "acquisitionTimeAndDepth": (
            "extensions only; t is photon microtime, not acquisition time"
        ),
    }
    settings = metadata.get("acquisitionSettings", {})
    aperture = settings.get("NumericalAperture", {}).get("value")
    if isinstance(aperture, (float, int)) and aperture > 0:
        fields["sensor\ts_params\tNumAperture"] = aperture
        fields["sensor\ts_states\tNumAperture"] = "reported"
        mappings["numericalAperture"] = "sensor s_params NumAperture"
    for field, history in (
        ("ObjectiveName", "objective"),
        ("Magnification", "objective magnification"),
        ("MicroscopeModel", "microscope"),
    ):
        value = settings.get(field, {}).get("value")
        if value is not None:
            fields[f"history\t{history}"] = value
            mappings[field] = f"history {history}"
    wavelengths = optics["excitation"]["nominalWavelengthsNm"]
    if len(wavelengths) == 1:
        fields["sensor\ts_params\tLambdaEx"] = wavelengths[0]
        fields["sensor\ts_states\tLambdaEx"] = "reported"
        mappings["excitationWavelength"] = (
            "sensor s_params LambdaEx (nominal nm)"
        )
    emission = optics.get("emission")
    if (
        emission is not None
        and emission["sourceBoundsNm"][0] == emission["sourceBoundsNm"][1]
    ):
        fields["sensor\ts_params\tLambdaEm"] = emission["nominalBoundsNm"][0]
        fields["sensor\ts_states\tLambdaEm"] = "reported"
        mappings["emissionWavelength"] = (
            "sensor s_params LambdaEm (nominal nm)"
        )
    written = {}
    for key, value in fields.items():
        if value is None:
            continue
        text = _ics_text(value)
        limit = (
            63
            if key.startswith("sensor")
            else ICS_HISTORY_RECORD_BYTES - len(key) - 2
        )
        if len(text) <= limit:
            written[key] = text
    metadata["headerMappings"] = {
        "format": "ICS",
        "fields": mappings,
        "writtenFields": list(written),
    }
    return "".join(f"{key}\t{value}\n" for key, value in written.items())


def ptu_header_mappings(metadata: dict) -> dict:
    """Only claim tags with defined, applicable PTU meanings."""
    axes = metadata["spatialCalibration"]["axes"]
    pixel_x, pixel_y = axes["x"]["spacingMetres"], axes["y"]["spacingMetres"]
    return {
        "format": "PTU",
        "fields": {
            "imageDimensions": "ImgHdr_PixX / ImgHdr_PixY",
            "pixelSize": "ImgHdr_PixResol (micrometres)"
            if pixel_x is not None and pixel_x == pixel_y
            else "extensions only: unequal or unavailable X/Y calibration",
            "photonMicrotime": "MeasDesc_Resolution (seconds)",
            "syncPeriod": "MeasDesc_GlobalResolution (seconds)",
            "syncRate": "TTResult_SyncRate (integer Hz)",
            "scanMarkers": "ImgHdr_LineStart / ImgHdr_LineStop / ImgHdr_Frame",
            "acquisitionSummary": "File_Comment (text)",
            "opticalSettingsAndPlaneIdentity": (
                "File_Comment text and Leica_* extensions"
            ),
        },
    }


def ptu_acquisition_comment(metadata: dict, timing_quality: str) -> str:
    """Put an ordinary readable summary in PTU's standard comment."""
    names, plane = metadata["leicaNames"], metadata["plane"]
    lines = [
        "Decoded Leica FLIM events; raster macrotime is "
        f"{timing_quality.lower()}.",
        "Original individual photon hardware timestamps are unavailable.",
        f"Source: {metadata['sourceFilename']}",
        *(
            f"{name.title()}: {value}"
            for name, value in names.items()
            if value
        ),
        f"Excitation: {metadata['opticalMetadata']['excitation']['label']}",
        f"Emission: {metadata['sequence']['emissionBand']}",
        f"Acquisition T index (zero-based): {plane['tIndexZeroBased']}",
        f"Acquisition Z index (zero-based): {plane['zIndexZeroBased']}",
    ]
    for axis, calibration in metadata["spatialCalibration"]["axes"].items():
        lines.append(
            f"{axis.upper()} sample spacing: {calibration['scale']:.17g} "
            f"{calibration['unit']} ({calibration['status']})"
        )
    for field in ("ObjectiveName", "NumericalAperture", "Zoom", "ScanSpeed"):
        setting = metadata.get("acquisitionSettings", {}).get(field, {})
        if setting.get("value") is not None:
            lines.append(
                f"{setting['label']}: {setting['value']} {setting['unit']}"
            )
    stamps = metadata.get("imageTimestamps", {})
    if stamps.get("selectedExposureUtc"):
        lines.append(
            f"Image exposure timestamp (UTC): {stamps['selectedExposureUtc']}"
        )
    for key, label in (
        ("laserFrequency", "Recorded laser repetition rate"),
        ("pixelDwell", "Recorded pixel dwell"),
    ):
        quantity = metadata["timing"][key]
        value = quantity["value"]
        lines.append(
            f"{label}: {value:.17g} {quantity['units']}"
            if value is not None
            else f"{label}: unavailable"
        )
    lines.append(
        "Detailed provenance and source values are in the JSON companion."
    )
    return "\n".join(_ics_text(line) for line in lines)
