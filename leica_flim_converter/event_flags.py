"""Shared scientific photon selection for both Leica event grammars."""

from __future__ import annotations

from collections.abc import Iterable

from .data_types import JsonObject

EVENT_MARKERS = (168, 160, 176, 184)
EVENT_FLAG_BITS = dict(zip(EVENT_MARKERS, (1, 2, 4, 8), strict=False))
PRIMARY_EVENT_FLAGS = 7
ALL_EVENT_FLAGS = 15
RAW_ALL_PHOTONS = 256
RAW_FIRST_PHOTONS = 512
RAW_SINGLE_EVENT = 1024
RAW_MODES = (RAW_ALL_PHOTONS, RAW_FIRST_PHOTONS, RAW_SINGLE_EVENT)
COMPRESSED_MODES = (7, 3, 1)
SELECTION_NAMES = ("All Photons", "First Photons", "Single-event Photons")


def validate_event_flag_mask(mask: int, *, allow_empty: bool = False) -> int:
    """Compute validate event flag mask."""
    value = mask
    if value in RAW_MODES:
        return value
    if (
        value < 0
        or value > ALL_EVENT_FLAGS
        or (not value and (not allow_empty))
    ):
        raise ValueError("Select at least one valid photon event class")
    return value


def markers_from_mask(mask: int, detector_route: int = 0) -> tuple[int, ...]:
    """Select class markers for one compressed detector route."""
    value = validate_event_flag_mask(mask, allow_empty=True)
    if value in RAW_MODES:
        raise ValueError("LMSRAW selections have no compressed event markers")
    if not 0 <= detector_route <= 7:
        raise ValueError("Compressed detector route must be between 0 and 7")
    return tuple(
        marker | detector_route
        for marker in EVENT_MARKERS
        if value & EVENT_FLAG_BITS[marker]
    )


def compressed_route_mask(mask: int, detector_route: int) -> int:
    """Encode native API 5's four class bits per detector route."""
    markers_from_mask(mask, detector_route)
    return mask << (4 * detector_route)


def mask_from_markers(markers: Iterable[int]) -> int:
    """Compute mask from markers."""
    value = 0
    for marker in markers:
        if marker not in EVENT_FLAG_BITS:
            raise ValueError(f"Unknown event marker: {marker:#x}")
        value |= EVENT_FLAG_BITS[marker]
    return value


def marker_labels(mask: int, detector_route: int = 0) -> tuple[str, ...]:
    """Compute marker labels."""
    return tuple(
        f"0x{marker:02X}" for marker in markers_from_mask(mask, detector_route)
    )


def normalize_selection(mask: int, storage_format: str) -> int:
    """Compute normalize selection."""
    value = validate_event_flag_mask(mask)
    if storage_format == "lmsraw":
        if value in COMPRESSED_MODES:
            return RAW_MODES[COMPRESSED_MODES.index(value)]
        if value not in RAW_MODES:
            raise ValueError("LMSRAW requires a named photon selection")
    elif value in RAW_MODES:
        return COMPRESSED_MODES[RAW_MODES.index(value)]
    return value


def selection_name(mask: int) -> str:
    """Compute selection name."""
    value = validate_event_flag_mask(mask, allow_empty=True)
    if value in RAW_MODES:
        return SELECTION_NAMES[RAW_MODES.index(value)]
    if value in COMPRESSED_MODES:
        return SELECTION_NAMES[COMPRESSED_MODES.index(value)]
    return " + ".join(marker_labels(value)) or "No photons"


def filename_suffix(mask: int) -> str:
    """Compute filename suffix."""
    value = validate_event_flag_mask(mask, allow_empty=True)
    if value in (7, RAW_ALL_PHOTONS):
        return ""
    if value in (3, RAW_FIRST_PHOTONS):
        return "_first-photons"
    if value in (1, RAW_SINGLE_EVENT):
        return "_single-event-photons"
    return f"_events-{value:02x}"


def selection_metadata(mask: int, *, applicable: bool = True) -> JsonObject:
    """Compute selection metadata."""
    value = validate_event_flag_mask(mask)
    raw = value in RAW_MODES
    index = (
        RAW_MODES.index(value)
        if raw
        else COMPRESSED_MODES.index(value)
        if value in COMPRESSED_MODES
        else None
    )
    mode = (
        "all-valid-photons" if raw else "all-photons",
        "first-photons",
        "single-event-photons",
    )
    result: JsonObject = {
        "applicable": (applicable),
        "sourceGrammar": "LMSRAW PulseVersion2 detector-route records"
        if raw
        else "LMSCOMPRESSED encoded FLIM photon records",
        "mode": mode[index] if index is not None else "custom-event-flags",
        "name": selection_name(value),
        "filterEnabled": True,
        "compressedEventMask": None if raw else f"0x{value:02X}",
    }
    if not raw:
        result.update(
            availableModes=[
                "all-photons",
                "first-photons",
                "single-event-photons",
            ]
        )
        result["includedEventFlags"] = list(marker_labels(value))
        result["excludedEventFlags"] = list(
            marker_labels(ALL_EVENT_FLAGS ^ value)
        )
        if index is not None:
            result.update(
                validationSample="PL109 R72C CC CCCP NH4Cl, Series002",
                validationPhotonCount=(91899036, 88834959, 83572902)[index],
                interpretation=(
                    "Corrected LAS X PTU count and complete "
                    "microtime-histogram match for the cumulative "
                    "LMSCOMPRESSED marker hierarchy"
                ),
            )
        return result
    result.update(
        firstPhotonFlagRequired=value == RAW_FIRST_PHOTONS,
        singleEventCycleRequired=value == RAW_SINGLE_EVENT,
    )
    if value == RAW_ALL_PHOTONS:
        result.update(
            qualification=(
                "first-in-cycle photons, plus subsequent photons whose"
                " signed arrival-bin delta from the immediately "
                "preceding detector-route photon meets the detector "
                "dead-time threshold"
            ),
            predecessorState=(
                "every detector-route photon advances predecessor "
                "state; state continues across encoded rows and resets"
                " at each plane"
            ),
            thresholdConversion="floor(deadTimeSeconds / clockPeriodSeconds)",
            deadTimeSource="LIF RawData detector metadata",
        )
    elif value == RAW_FIRST_PHOTONS:
        result["qualification"] = "first-in-cycle flag"
    else:
        result.update(
            implementation=(
                "completed excitation cycles containing exactly one event"
            ),
            qualification=(
                "completed excitation cycles containing exactly one "
                "event; validated against the supplied LAS X reference"
                " PTUs"
            ),
            cycleBoundary=(
                "first-in-cycle bit; incomplete terminal cycles at row"
                " boundaries are excluded"
            ),
        )
    return result
