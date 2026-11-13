"""LMSRAW selection vectors shared by previews and both export
formats.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

from leica_xml import parse_xml

from .dataset import DatasetInfo
from .event_flags import (
    ALL_EVENT_FLAGS,
    RAW_ALL_PHOTONS,
    RAW_FIRST_PHOTONS,
    RAW_MODES,
    RAW_SINGLE_EVENT,
    marker_labels,
    normalize_selection,
    selection_metadata,
)

RAW_NO_FILTER = 0
_dead_time_cache: dict = {}


def _read_lif_xml(source):
    with Path(source).open("rb") as stream:
        if len(header := stream.read(13)) != 13:
            raise RuntimeError("The LIF header is truncated")
        magic, header_size = struct.unpack_from("<II", header, 0)
        if magic != 112 or header[8] != 42:
            raise RuntimeError(
                "The source is not a supported Leica LIF container"
            )
        character_count = struct.unpack_from("<I", header, 9)[0]
        xml_bytes = stream.read(character_count * 2)
    if len(xml_bytes) != character_count * 2 or header_size != 5 + len(
        xml_bytes
    ):
        raise RuntimeError("The LIF XML header is truncated or inconsistent")
    return parse_xml(xml_bytes.decode("utf-16le"))


def _detector_dead_time(dataset):
    if dataset.detector_dead_time_s is not None:
        return (
            dataset.detector_dead_time_s,
            dataset.detector_data_type or "PulseVersion2",
        )
    root = _read_lif_xml(dataset.source)
    element = next(
        (
            item
            for item in root.iter("Element")
            if (memory := item.find("Memory")) is not None
            and memory.get("MemoryBlockID") == dataset.memory_id
        ),
        None,
    )
    if element is None:
        element = next(
            (
                item
                for item in root.iter("Element")
                if item.get("Name") == dataset.acquisition_name
            ),
            None,
        )
    if element is None:
        raise RuntimeError(
            "Cannot locate detector metadata for " + dataset.display_name
        )
    sequences = list(element.findall(".//RawData/Sequence/SequenceItem"))
    if not 0 <= dataset.sequence_index < len(sequences):
        raise RuntimeError(
            "Detector sequence index is outside the source metadata"
        )
    detectors = sequences[dataset.sequence_index].findall(
        "Detectors/Detectors"
    )
    detector = next(
        (
            item
            for item in detectors
            if item.findtext("Detector") == str(dataset.detector_route)
        ),
        None,
    )
    if detector is None:
        raise RuntimeError(
            "Local detector route is absent from the source metadata"
        )
    return float(detector.findtext("DeadTime", "nan")), detector.findtext(
        "DataType", "PulseVersion2"
    )


def dead_time_info(dataset):
    """Read dead time from the selected sequence and local detector."""
    source = Path(dataset.source)
    if (
        dataset.clock_period_s is None
        or not math.isfinite(dataset.clock_period_s)
        or dataset.clock_period_s <= 0
    ):
        raise RuntimeError(
            "All Photons requires a positive LMSRAW clock period"
        )
    key = (
        str(source.resolve()),
        source.stat().st_mtime_ns,
        dataset.key,
        float(dataset.clock_period_s),
        dataset.detector_dead_time_s,
    )
    cached = _dead_time_cache.get(key)
    if cached is not None:
        return cached
    dead_time_s, data_type = _detector_dead_time(dataset)
    if not math.isfinite(dead_time_s) or dead_time_s <= 0:
        raise RuntimeError(
            "All Photons requires a positive detector DeadTime for "
            + dataset.display_name
        )
    clock_period_s = float(dataset.clock_period_s)
    threshold_bins = max(1, math.floor(dead_time_s / clock_period_s + 1e-12))
    path = "RawData/Sequence/SequenceItem/Detectors/Detectors/DeadTime"
    if dataset.sequence_count > 1:
        path = (
            f"RawData/Sequence/SequenceItem[{dataset.sequence_index}]/"
            f"Detectors/Detectors[Detector={dataset.detector_route}]/DeadTime"
        )
    info = {
        "deadTimeSeconds": dead_time_s,
        "clockPeriodSeconds": clock_period_s,
        "minimumSubsequentArrivalDeltaBins": threshold_bins,
        "deadTimeToClockRatio": dead_time_s / clock_period_s,
        "deadTimeMetadataPath": path,
        "dataType": data_type,
    }
    _dead_time_cache[key] = info
    return info


def _selected_raw_vectors(words, dataset, mode):
    """Return selected x positions, microtimes, and first-bit values for
    one row.
    """
    high = words >> 12
    route = (high < 8) & (high >> 1 == dataset.detector_route)
    control_nibble = words & 15
    controls = ((high == 10) | (high == 11)) & (
        (control_nibble == 4) | (control_nibble == 8)
    )
    x = np.cumsum(controls, dtype=np.int32)[route] // 2
    arrival = (words[route] & 255).astype(np.int32)
    first_bits = (high[route] & 1).astype(np.uint8)
    inside = (x >= 0) & (x < dataset.width)
    x = x[inside]
    arrival = arrival[inside]
    first_bits = first_bits[inside]
    if mode == RAW_FIRST_PHOTONS:
        keep = first_bits == 1
        return (x[keep], arrival[keep], first_bits[keep])
    if mode == RAW_SINGLE_EVENT:
        starts = np.flatnonzero(first_bits == 1)
        if starts.size == 0:
            return (x[:0], arrival[:0], first_bits[:0])
        lengths = np.diff(np.r_[starts, first_bits.size])
        keep = starts[lengths == 1]
        if lengths[-1] == 1 and keep.size and (keep[-1] == starts[-1]):
            keep = keep[:-1]
        return (x[keep], arrival[keep], first_bits[keep])
    return (x, arrival, first_bits)


def _select_all_valid_vectors(words, dataset, state, threshold):
    high = words >> 12
    low = words & 15
    controls = ((high == 10) | (high == 11)) & ((low == 4) | (low == 8))
    route = (high < 8) & (high >> 1 == int(dataset.detector_route))
    if not bool(np.any(route)):
        empty = np.empty(0, dtype=np.int32)
        return (empty, empty)
    x = (np.cumsum(controls, dtype=np.int32)[route] // 2).astype(
        np.int32, copy=False
    )
    arrivals = (words[route] & 255).astype(np.int16, copy=False)
    first = (high[route] & 1).astype(bool, copy=False)
    valid = x < int(dataset.width)
    x = x[valid]
    arrivals = arrivals[valid]
    first = first[valid]
    if arrivals.size == 0:
        empty = np.empty(0, dtype=np.int32)
        return (empty, empty)
    keep = first.copy()
    if arrivals.size > 1:
        keep[1:] |= np.diff(arrivals) >= threshold
    if state[0]:
        keep[0] |= int(arrivals[0]) - int(state[1]) >= threshold
    state[0] = True
    state[1] = int(arrivals[-1])
    return (
        x[keep].astype(np.int32, copy=False),
        arrivals[keep].astype(np.int32),
    )


def dataset_selection_metadata(dataset, mask):
    """Compute dataset selection metadata."""
    mode = normalize_selection(mask, dataset.storage_format)
    result = selection_metadata(mode)
    if mode == RAW_ALL_PHOTONS:
        result.update(dead_time_info(dataset))
    if mode in RAW_MODES:
        result["selectionSchema"] = 2
        result["implementation"] = "maintained-source/all-valid-photons-v2"
    elif dataset.detector_route:
        result["compressedDetectorRoute"] = dataset.detector_route
        result["includedEventFlags"] = list(
            marker_labels(mode, dataset.detector_route)
        )
        result["excludedEventFlags"] = list(
            marker_labels(ALL_EVENT_FLAGS ^ mode, dataset.detector_route)
        )
    return result


def plane_starts(dataset):
    """Compute plane starts."""
    return (
        set(dataset.plane_row_starts)
        if dataset.plane_row_starts
        else {
            dataset.plane_row_range(index)[0]
            for index in range(dataset.plane_count)
        }
    )


def select_raw_vectors(words, dataset, mask, state, threshold):
    """Compute select raw vectors."""
    mode = normalize_selection(mask, dataset.storage_format)
    if mode == RAW_ALL_PHOTONS:
        return _select_all_valid_vectors(words, dataset, state, threshold)
    x, arrivals, _first = _selected_raw_vectors(words, dataset, mode)
    return (x, arrivals)


def indexed_logical_lines(dataset: DatasetInfo, linear_plane: int) -> int:
    """Count represented raster lines, including a partial final
    repeat.
    """
    _first, rows = dataset.plane_row_range(linear_plane)
    repeats = (
        dataset.line_repetitions
        if dataset.repetition_storage_model == "explicit-line-repeat-rows"
        else 1
    )
    return (rows + repeats - 1) // repeats
