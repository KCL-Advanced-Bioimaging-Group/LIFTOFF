"""Immutable dataset metadata and established plane/row interfaces."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .data_types import JsonObject
from .mosaic import MosaicLayout
from .optical_metadata import (
    EmissionBand,
    nominal_wavelength_nm,
    wavelength_label,
)
from .timing import AcquisitionTiming


@dataclass(frozen=True)
# Flat declared metadata preserves the public dataset and sidecar
# contract.
# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class DatasetInfo:
    """Immutable Leica metadata and compatible plane interfaces."""

    source: Path
    memory_id: str
    block_start: int
    block_end: int
    compressed_bytes: int
    width: int
    height: int
    decoded_rows: int
    intensity_memory_id: str | None
    intensity_start: int | None
    intensity_end: int | None
    total_photons: int | None
    thumbnail: Image.Image | None
    pixel_size_x_m: float | None
    pixel_size_y_m: float | None
    clock_period_s: float | None
    laser_frequency_hz: float | None
    acquisition_name: str | None = None
    series_name: str | None = None
    channel_name: str | None = None
    timepoint_name: str | None = None
    z_name: str | None = None
    detector_name: str | None = None
    element_path: tuple[str, ...] = ()
    frame_count: int = 1
    z_count: int = 1
    t_count: int = 1
    z_stride: int = 0
    t_stride: int = 0
    dimension_order: tuple[str, ...] = ("X", "Y")
    dimension_status: str = "confirmed"
    dimension_records: tuple[dict, ...] = ()
    storage_format: str = "compressed"
    channel_index: int = 0
    channel_count: int = 1
    channel_color: str | None = None
    detector_identifier: str | None = None
    frame_repetitions: int = 1
    line_repetitions: int = 1
    repetition_storage_model: str = "frame-repeat-rows"
    frame_repetitions_source: str = "default"
    line_repetitions_source: str = "default"
    line_offsets_start: int | None = None
    line_offsets_end: int | None = None
    plane_row_starts: tuple[int, ...] = ()
    emission_filter_band: str = "Emission band unavailable"
    original_channel_name: str | None = None
    original_channel_color: str | None = None
    excitation_wavelengths_nm: tuple[float, ...] = ()
    excitation_sources: tuple[str | None, ...] = ()
    sequence_index: int = 0
    sequence_count: int = 1
    sequence_name: str | None = None
    local_detector_index: int | None = None
    sequence_detector_count: int | None = None
    detector_dead_time_s: float | None = None
    detector_data_type: str | None = None
    plane_row_ranges: tuple[tuple[int, int], ...] = ()
    intensity_plane_starts: tuple[int, ...] = ()
    emission_band_metadata: EmissionBand | None = None
    stage_count: int = 1
    stage_stride: int = 0
    mosaic: MosaicLayout | None = None
    tile_index: int | None = None
    acquisition_timing: AcquisitionTiming | None = None
    recorded_plane_count: int | None = None
    spatial_sources: tuple[dict, ...] = ()
    source_acquisition_xml: str | None = None

    @property
    def detector_route(self) -> int:
        """Resolve the sequence-local photon route."""
        return (
            self.channel_index
            if self.local_detector_index is None
            else self.local_detector_index
        )

    @property
    def detector_route_count(self) -> int:
        """Count hardware routes in this sequence."""
        return self.sequence_detector_count or self.channel_count

    @property
    def indexed_rows(self) -> int:
        """Count this sequence's rows across T/Z planes."""
        return (
            sum(length for _first, length in self.plane_row_ranges)
            if self.plane_row_ranges
            else self.decoded_rows
        )

    @property
    def sequence_label(self) -> str:
        """Identify scan settings even when wavelengths are reused."""
        name = f"Sequence {self.sequence_index + 1}"
        if self.sequence_name:
            name += f" ({self.sequence_name})"
        return f"{self.excitation_label} | {name}"

    @property
    def export_channel_label(self) -> str:
        """Identify the recorded pair in an export selection row."""
        if self.sequence_count <= 1:
            return self.channel_name or "-"
        return (
            f"Seq. {self.sequence_index + 1} | Ex. {self.excitation_label} / "
            f"Em. {self.emission_filter_band}"
        )

    @property
    def sequence_metadata(self) -> dict:
        """Retain source identities and export row ranges."""
        return {
            "sequenceIndexZeroBased": self.sequence_index,
            "sequenceCount": self.sequence_count,
            "sequenceName": self.sequence_name,
            "displayChannelIndexZeroBased": self.channel_index,
            "localDetectorRoute": self.detector_route,
            "detectorRoutesInSequence": self.detector_route_count,
            "detectorDataType": self.detector_data_type,
            "excitationWavelengthsNm": self.excitation_wavelengths_nm,
            "excitationSources": self.excitation_sources,
            "emissionBand": self.emission_filter_band,
            "planeRowRanges": self.plane_row_ranges,
        }

    @property
    def excitation_label(self) -> str:
        """Describe excitation, preserving unavailable values."""
        if not self.excitation_wavelengths_nm:
            return "unavailable"
        if any(self.excitation_sources):
            parts = []
            for index, wavelength in enumerate(self.excitation_wavelengths_nm):
                source = (
                    self.excitation_sources[index]
                    if index < len(self.excitation_sources)
                    else None
                )
                suffix = f" ({source})" if source else ""
                parts.append(f"{wavelength_label(wavelength)} nm{suffix}")
            return " / ".join(parts)
        return (
            " / ".join(
                wavelength_label(value)
                for value in self.excitation_wavelengths_nm
            )
            + " nm"
        )

    @property
    def optical_metadata(self) -> JsonObject:
        """Store wavelength policy and unrounded source values."""
        return {
            "wavelengthUnit": "nm",
            "displayIncrementNm": 1,
            "rounding": "nearest whole nm; half up",
            "precisionBasis": "nominal settings, not calibrated uncertainty",
            "excitation": {
                "label": self.excitation_label,
                "nominalWavelengthsNm": [
                    nominal_wavelength_nm(value)
                    for value in self.excitation_wavelengths_nm
                ],
                "sourceWavelengthsNm": list(self.excitation_wavelengths_nm),
                "sources": list(self.excitation_sources),
            },
            "emission": (
                self.emission_band_metadata.metadata
                if self.emission_band_metadata is not None
                else None
            ),
        }

    @property
    def raw_photon_label(self) -> str:
        """Describe optional preview counts."""
        if self.total_photons is None:
            return "raw counts unavailable"
        return f"{self.total_photons:,} raw counts"

    @property
    def pair_key(self) -> str:
        """Identify the recorded pair independently of its tile view."""
        if self.sequence_count > 1:
            key = (
                f"{self.source}|{self.memory_id}|s{self.sequence_index}"
                f"|d{self.detector_route}|c{self.channel_index}"
            )
        else:
            key = f"{self.source}|{self.memory_id}|c{self.channel_index}"
        return key

    @property
    def key(self) -> str:
        """Return a stable pair and optional tile identity."""
        key = self.pair_key
        return (
            key if self.tile_index is None else f"{key}|tile{self.tile_index}"
        )

    @property
    def display_name(self) -> str:
        """Return the human-readable acquisition and detector label."""
        detector = self.detector_name or self.channel_name
        suffix = f" | {detector}" if detector else ""
        if self.sequence_count > 1:
            suffix = f" | Ex. {self.sequence_label}{suffix}"
        return (
            f"{self.acquisition_name or self.source.stem}"
            f"{suffix}"
            " | "
            f"{self.memory_id}"
        )

    @property
    def plane_count(self) -> int:
        """Return the number of indexed T/Z planes."""
        return (
            self.recorded_plane_count
            if self.recorded_plane_count is not None
            else self.declared_plane_count
        )

    @property
    def declared_plane_count(self) -> int:
        """Preserve the source's reserved T/Z/stage extent."""
        stages = self.stage_count if self.tile_index is None else 1
        return self.z_count * self.t_count * stages

    @property
    def plane_coverage_metadata(self) -> dict:
        """Distinguish recorded planes from reserved empty planes."""
        return {
            "declaredPlaneCount": self.declared_plane_count,
            "recordedPlaneCount": (
                self.plane_count
                if self.repetition_storage_model != "unresolved"
                else None
            ),
            "recordedPrefixVerified": self.recorded_plane_count is not None,
            "absentTrailingPlaneCount": (
                self.declared_plane_count - self.plane_count
                if self.repetition_storage_model != "unresolved"
                else None
            ),
            "evidence": self.dimension_status,
        }

    @property
    def preview_plane_count(self) -> int:
        """Navigate T/Z independently of the matrix of tiles."""
        return (
            self.plane_count
            if self.recorded_plane_count is not None
            else self.z_count * self.t_count
        )

    def plane_stage_index(self, linear_plane: int) -> int:
        """Keep stage identity independent of time and depth."""
        if not 0 <= linear_plane < self.plane_count:
            raise IndexError(linear_plane)
        if self.tile_index is not None:
            return self.tile_index
        return (
            linear_plane // self.stage_stride % self.stage_count
            if self.stage_stride
            else 0
        )

    def mosaic_metadata(self, linear_plane: int | None = None) -> dict | None:
        """Describe unstitched geometry and the selected tile."""
        if self.mosaic is None:
            return None
        index = (
            self.plane_stage_index(linear_plane)
            if linear_plane is not None
            else self.tile_index
        )
        return self.mosaic.metadata(index)

    @property
    def expected_rows(self) -> int:
        """Return the complete encoded row count from metadata."""
        return self.rows_per_plane * self.plane_count

    @property
    def rows_per_plane(self) -> int:
        """Compute rows per plane."""
        multiplier = (
            self.line_repetitions
            if self.repetition_storage_model == "explicit-line-repeat-rows"
            else 1
        )
        return self.height * self.frame_repetitions * multiplier

    def plane_row_range(self, linear_plane: int) -> tuple[int, int]:
        """Compute plane row range."""
        if not 0 <= linear_plane < self.plane_count:
            raise IndexError(linear_plane)
        if self.plane_row_ranges:
            if len(self.plane_row_ranges) != self.plane_count:
                raise RuntimeError("Sequence T/Z index is incomplete")
            first, length = self.plane_row_ranges[linear_plane]
            if first < 0 or length <= 0 or first + length > self.decoded_rows:
                raise RuntimeError("Sequence row range exceeds the line table")
            return first, length
        first = (
            self.plane_row_starts[linear_plane]
            if len(self.plane_row_starts) == self.plane_count
            else linear_plane * self.rows_per_plane
        )
        if self.dimension_status.startswith("partial indexed acquisition:"):
            stop = (
                self.plane_row_starts[linear_plane + 1]
                if linear_plane + 1 < self.plane_count
                else self.decoded_rows
            )
            if not 0 <= first < stop <= self.decoded_rows:
                raise RuntimeError(
                    "partial acquisition frame index is invalid"
                )
            return (first, stop - first)
        return (first, self.rows_per_plane)

    def encoded_row_to_y(self, row: int, first_row: int | None = None) -> int:
        """Compute encoded row to y."""
        if self.repetition_storage_model == "unresolved":
            raise ValueError(
                f"unresolved repetition row layout for {self.display_name}"
            )
        if first_row is None:
            if len(self.plane_row_starts) == self.plane_count:
                plane = bisect_right(self.plane_row_starts, row) - 1
                if plane < 0:
                    raise IndexError(row)
                if self.plane_row_ranges:
                    start, length = self.plane_row_ranges[plane]
                    if not start <= row < start + length:
                        raise IndexError(row)
                first_row = self.plane_row_starts[plane]
            else:
                first_row = row // self.rows_per_plane * self.rows_per_plane
        relative = row - first_row
        if not 0 <= relative < self.rows_per_plane:
            raise IndexError(row)
        if self.repetition_storage_model == "explicit-line-repeat-rows":
            return (
                relative
                % (self.height * self.line_repetitions)
                // self.line_repetitions
            )
        return relative % self.height

    def plane_indices(self, linear_plane: int) -> tuple[int, int]:
        """Compute plane indices."""
        if not 0 <= linear_plane < self.plane_count:
            raise IndexError(linear_plane)
        z = (
            linear_plane // self.z_stride % self.z_count
            if self.z_stride
            else 0
        )
        t = (
            linear_plane // self.t_stride % self.t_count
            if self.t_stride
            else 0
        )
        return (t, z)

    def tile_label(self, index: int) -> str:
        """Name a tile by its spatial cell rather than storage order."""
        if self.mosaic is None:
            raise ValueError("No validated tile layout")
        tile = self.mosaic.tiles[index]
        return f"tile_r{tile.row + 1:02d}_c{tile.column + 1:02d}"

    def plane_label(
        self, linear_plane: int, *, include_tile: bool = True
    ) -> str:
        """Compute plane label."""
        t, z = self.plane_indices(linear_plane)
        parts = []
        if self.mosaic is not None and include_tile:
            parts.append(self.tile_label(self.plane_stage_index(linear_plane)))
        if self.t_count > 1:
            parts.append(f"t{t + 1:0{max(3, len(str(self.t_count)))}d}")
        if self.z_count > 1:
            parts.append(f"z{z + 1:0{max(3, len(str(self.z_count)))}d}")
        return "_".join(parts)
