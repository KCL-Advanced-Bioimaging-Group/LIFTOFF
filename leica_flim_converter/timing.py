"""Shared physical timing and explicit histogram window contracts."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .dataset import DatasetInfo

ICS_BIN_CHOICES = (
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
    2048,
    4096,
    8192,
    16384,
    32768,
)


@dataclass(frozen=True)
class TimingValue:
    """A physical quantity with units and evidence provenance."""

    value: float | None = None
    units: str = "s"
    source: str | None = None
    quality: str = "unavailable"

    def metadata(self) -> dict:
        """Return portable provenance without rounding stored values."""
        return asdict(self)


@dataclass(frozen=True)
class AcquisitionTiming:
    """Recorded scan fields and original timestamp XML."""

    clock: TimingValue = field(default_factory=TimingValue)
    laser_frequency: TimingValue = field(
        default_factory=lambda: TimingValue(units="Hz")
    )
    pixel_dwell: TimingValue = field(default_factory=TimingValue)
    line_period: TimingValue = field(default_factory=TimingValue)
    frame_period: TimingValue = field(default_factory=TimingValue)
    timestamp_lists_xml: tuple[str, ...] = ()

    def metadata(self) -> dict:
        """Keep raw scan timing separate from image timestamps."""
        return {
            "arrivalClock": self.clock.metadata(),
            "laserFrequency": self.laser_frequency.metadata(),
            "laserRepetitionPeriod": TimingValue(
                1.0 / self.laser_frequency.value
                if _positive(self.laser_frequency.value)
                and self.laser_frequency.value is not None
                else None,
                source=f"1 / {self.laser_frequency.source}"
                if self.laser_frequency.source
                else None,
                quality="calculated"
                if _positive(self.laser_frequency.value)
                else "unavailable",
            ).metadata(),
            "pixelDwell": self.pixel_dwell.metadata(),
            "linePeriod": self.line_period.metadata(),
            "framePeriod": self.frame_period.metadata(),
            "timestampLists": {
                "source": "selected acquisition/TimeStampList",
                "rawXml": list(self.timestamp_lists_xml),
                "interpretation": (
                    "raw XML; validated image times, where available, "
                    "are in acquisitionMetadata.imageTimestamps"
                ),
            },
            "originalPhotonMacrotimesAvailable": False,
        }


def _positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def recorded_timing(dataset: DatasetInfo) -> AcquisitionTiming:
    """Resolve legacy datasets through the shared timing model."""
    timing = dataset.acquisition_timing or AcquisitionTiming()

    def quantity(value, units, existing, source):
        if not _positive(value):
            return TimingValue(units=units)
        return TimingValue(value, units, existing.source or source, "recorded")

    return AcquisitionTiming(
        clock=quantity(
            dataset.clock_period_s, "s", timing.clock, "Leica/ClockPeriod"
        ),
        laser_frequency=quantity(
            dataset.laser_frequency_hz,
            "Hz",
            timing.laser_frequency,
            "Leica/LaserPulseFrequency",
        ),
        pixel_dwell=timing.pixel_dwell,
        line_period=timing.line_period,
        frame_period=timing.frame_period,
        timestamp_lists_xml=timing.timestamp_lists_xml,
    )


def require_calibration(dataset: DatasetInfo) -> tuple[float, float]:
    """Require recorded calibration for temporal exports."""
    timing = recorded_timing(dataset)
    clock, frequency = timing.clock.value, timing.laser_frequency.value
    if not _positive(clock) or not _positive(frequency):
        raise ValueError(
            "Calibrated export requires a recorded positive arrival clock "
            "and laser frequency; timing is unavailable"
        )
    assert clock is not None and frequency is not None
    if not math.isfinite(1.0 / frequency / clock):
        raise ValueError("Timing calibration is outside the supported range")
    return clock, frequency


@dataclass(frozen=True)
class NumericTimeWindow:
    """A power-of-two native window and its repetition-rate evidence."""

    bins: int
    frequency: TimingValue
    rate_role: str


def numeric_time_window(dataset: DatasetInfo) -> NumericTimeWindow:
    """Use the selected rate with a labelled actual-rate fallback."""
    clock, _actual = require_calibration(dataset)
    selected = dataset.selected_rate_metadata
    nominal = selected.get("value")
    if nominal is not None:
        frequency = TimingValue(
            nominal * 1e6, "Hz", selected["source"], "recorded setting"
        )
        role = "selected"
    else:
        frequency = recorded_timing(dataset).laser_frequency
        role = "actual fallback; selected rate unavailable"
    rate = frequency.value
    assert rate is not None
    native_period = 1.0 / rate / clock
    if not math.isfinite(native_period) or native_period <= 0:
        raise ValueError(
            "Numeric timing window is outside the supported range"
        )
    lower = 1 << max(0, math.floor(math.log2(native_period)))
    upper = lower * 2
    count = lower if native_period - lower <= upper - native_period else upper
    if count > 32768:
        raise ValueError("Numeric timing window exceeds 32768 native bins")
    return NumericTimeWindow(count, frequency, role)


@dataclass(frozen=True)
class TimeGrid:
    """Half-open bins in native-clock units, shared by data and
    headers.
    """

    bins: int
    clock_s: float
    step_s: float
    native_step: float
    mode: str
    window_frequency: TimingValue | None = None
    window_frequency_role: str | None = None

    @property
    def extent_s(self) -> float:
        """Return the actual exported window, including a final full
        bin.
        """
        return self.bins * self.step_s

    def lookup(self) -> np.ndarray:
        """Share physical bin boundaries with native workers."""
        count = self.bins * int(self.native_step) + 1
        if count > 16777216:
            raise ValueError(
                "Timing lookup exceeds 16 million native increments"
            )
        result = self.indices(np.arange(count)).astype(np.int32)
        result[(result < 0) | (result >= self.bins)] = -1
        return result

    def indices(self, arrivals: np.ndarray) -> np.ndarray:
        """Group native indices exactly using integer division."""
        factor = int(self.native_step)
        if factor < 1 or factor != self.native_step:
            raise ValueError("Histogram bins require whole native increments")
        return arrivals.astype(np.int64) // factor

    def metadata(self) -> dict:
        """Describe boundaries and exclusion policy for independent
        readers.
        """
        return {
            "mode": self.mode,
            "bins": self.bins,
            "originSeconds": 0.0,
            "binWidthSeconds": self.step_s,
            "extentSeconds": self.extent_s,
            "nativeClockSeconds": self.clock_s,
            "nativeIncrementsPerOutputBin": self.native_step,
            "nativeWindowBins": self.bins * int(self.native_step),
            "nativeIndexAssignment": "native arrival index // grouping factor",
            "boundaryConvention": "[i * binWidth, (i + 1) * binWidth)",
            "outOfWindowPolicy": "exclude and count; never clip",
            "quality": "recorded" if self.mode == "native" else "calculated",
            "binWidthSource": "recorded arrival clock"
            if self.mode == "native"
            else "recorded arrival clock * integer grouping factor",
            "windowQuality": "calculated",
            "windowSource": "complete native bins spanning one laser period"
            if self.mode == "native"
            else "first power-of-two native window from repetition rate",
            "windowFrequency": self.window_frequency.metadata()
            if self.window_frequency is not None
            else None,
            "windowFrequencyRole": self.window_frequency_role,
            "windowBinCountRule": "nearest power of two; ties choose smaller"
            if self.mode != "native"
            else "ceil(actual laser period / native clock)",
        }


def time_grid(dataset: DatasetInfo, bins: int | None) -> TimeGrid:
    """Retain native timing or sum groups in a rate-derived window."""
    clock, frequency = require_calibration(dataset)
    native_period = 1.0 / frequency / clock
    if bins is None:
        # Native bins retain their entire width; no rounded-period
        # scaling.
        count = max(1, math.ceil(native_period))
        if count > 32768:
            raise ValueError("Native timing window exceeds 32768 arrival bins")
        return TimeGrid(count, clock, clock, 1.0, "native")
    if bins not in ICS_BIN_CHOICES:
        raise ValueError(f"ICS bins must be one of {ICS_BIN_CHOICES}")
    window = numeric_time_window(dataset)
    if bins > window.bins:
        raise ValueError(
            f"ICS {bins}-bin output exceeds the {window.bins}-bin native "
            f"window ({window.rate_role}); upsampling is unavailable"
        )
    factor = window.bins // bins
    step = clock * factor
    if not _positive(step):
        raise ValueError("Output time step is outside the supported range")
    return TimeGrid(
        bins,
        clock,
        step,
        float(factor),
        "rebinned",
        window.frequency,
        window.rate_role,
    )


def native_source_grid(dataset: DatasetInfo, output: TimeGrid) -> TimeGrid:
    """Cover preview reflection bounds and the output arrival window."""
    native = time_grid(dataset, None)
    count = max(native.bins, output.bins * int(output.native_step))
    return TimeGrid(count, native.clock_s, native.clock_s, 1.0, "native")


def reconstruction_error(dataset: DatasetInfo) -> str | None:
    """Require explicit scan periods instead of assuming absent
    flyback.
    """
    timing = recorded_timing(dataset)
    dwell, line, frame = (
        timing.pixel_dwell.value,
        timing.line_period.value,
        timing.frame_period.value,
    )
    if not _positive(dwell) or not _positive(line):
        return "Recorded pixel dwell and line period are required"
    assert dwell is not None and line is not None
    frequency = timing.laser_frequency.value
    if frequency is not None and dwell * frequency < 2:
        return "Recorded dwell is too short for distinct PTU scan markers"
    if line < dataset.width * dwell:
        return "Recorded line period is shorter than the active pixel scan"
    if dataset.line_repetitions > 1:
        return (
            "Individual timing of accumulated line repetitions is unavailable"
        )
    if dataset.frame_repetitions > 1 and (
        not _positive(frame) or frame is None or frame < dataset.height * line
    ):
        return (
            "A consistent recorded frame period is required for frame repeats"
        )
    return (
        "Partial scans do not establish complete frame timing"
        if dataset.dimension_status.startswith("partial")
        else None
    )


def timing_quality(dataset: DatasetInfo, mode: str = "synthetic") -> str:
    """Give export tables an honest timing summary."""
    try:
        require_calibration(dataset)
    except ValueError:
        return "Unavailable"
    if mode == "ics":
        return "Recorded arrival clock"
    if mode == "reconstructed":
        return (
            "Reconstructed"
            if reconstruction_error(dataset) is None
            else "Unavailable"
        )
    return "Synthetic"
