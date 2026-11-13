"""Shared array, JSON, and callback contracts for maintained code."""

from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypedDict

import numpy as np
from numpy.typing import NDArray

type CountArray = NDArray[np.uint16 | np.uint32]
type ArrivalArray = NDArray[np.int32]
type WordArray = NDArray[np.uint16]
type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]
type ProgressCallback = Callable[[str], None]
type CancelCheck = Callable[[], bool]
type BatchProgress = Callable[[str, float, float], None]


class RawChannel(TypedDict):
    """One detector route described by the source XML."""

    index: int
    name: str | None
    identifier: str | None
    color: str | None
    excitation_nm: NotRequired[float | None]
    sequence_index: NotRequired[int]
    detector_index: NotRequired[int]
    detector_count: NotRequired[int]
    sequence_count: NotRequired[int]


class DeadTimeInfo(TypedDict):
    """Physical detector qualification and its exact bin conversion."""

    deadTimeSeconds: float
    clockPeriodSeconds: float
    minimumSubsequentArrivalDeltaBins: int
    deadTimeToClockRatio: float
    deadTimeMetadataPath: str
    dataType: str


class PtuTag(TypedDict):
    """One independently parsed PTU header tag."""

    ident: str
    index: int
    type: int
    value: int | float | str


class PtuRecordSummary(TypedDict):
    """Observable counts from the independent PTU record reader."""

    count: int
    photons: int
    markers: int
    overflowRecords: int
    overflowWraps: int
    channels: dict[int, int]
    markerBits: dict[int, int]


class PtuFileInfo(TypedDict):
    """PTU structure, with optional full record validation."""

    version: str
    tags: list[PtuTag]
    dataOffset: int
    fileSize: int
    records: NotRequired[PtuRecordSummary]
