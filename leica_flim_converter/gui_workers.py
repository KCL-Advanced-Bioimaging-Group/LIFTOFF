"""Maintained desktop component: workers."""

from __future__ import annotations

import threading
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QThread, Signal, Slot

from .catalog import IndexCancelled, scan_lif
from .dataset import DatasetInfo
from .decay import native_period_bins
from .event_flags import PRIMARY_EVENT_FLAGS
from .gui_models import connect_signal
from .histogram import decode_histogram_cube
from .histogram_core import DecodeCancelled, HistogramCube
from .ics_export import IcsExportCancelled, IcsExportOptions, export_ics_blocks
from .native_decoder import decode_histogram_plane
from .ptu_export import PtuExportCancelled, PtuExportOptions, export_ptu_blocks
from .timing import time_grid


class ResultWorker(QThread):
    """Publish results after the worker thread has actually ended."""

    completed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._result: tuple[object, ...] | None = None
        connect_signal(self.finished, self._deliver_result)

    def _complete(self, *args: object) -> None:
        self._result = args

    @Slot()
    def _deliver_result(self) -> None:
        self.wait()
        result, self._result = (self._result, None)
        if result is not None:
            self.completed.emit(*result)


class ScanWorker(ResultWorker):
    """Index selected sources with cancellation and GUI delivery."""

    completed = Signal(object, float, str)
    status = Signal(str)

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request safe cancellation at the next bounded work
        boundary.
        """
        self.cancel_event.set()

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        started = perf_counter()
        datasets = []
        try:
            for index, path in enumerate(self.paths, 1):
                self.status.emit(
                    f"Indexing {path.name} ({index}/{len(self.paths)})"
                )
                datasets.extend(
                    scan_lif(
                        path,
                        progress=self.status.emit,
                        cancelled=self.cancel_event.is_set,
                    )
                )
            self._complete(datasets, perf_counter() - started, "")
        except IndexCancelled:
            self._complete([], perf_counter() - started, "Cancelled")
        # Convert unexpected worker failures into explicit user-facing
        # errors.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:
            self._complete([], perf_counter() - started, str(exc))


class DecodeWorker(ResultWorker):
    """Decode the selected plane and photon population off-thread."""

    completed = Signal(object, str)
    status = Signal(str)

    def __init__(
        self,
        dataset: DatasetInfo,
        threads: int,
        linear_plane: int | None = None,
        event_flag_mask: int = PRIMARY_EVENT_FLAGS,
    ) -> None:
        super().__init__()
        self.dataset = dataset
        self.threads = threads
        self.linear_plane = linear_plane
        self.event_flag_mask = event_flag_mask
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request safe cancellation at the next bounded work
        boundary.
        """
        self.cancel_event.set()

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        try:
            try:
                grid = time_grid(self.dataset, None)
            except ValueError:
                grid = None
            bins = (
                grid.bins
                if grid is not None
                else native_period_bins(
                    self.dataset.clock_period_s,
                    self.dataset.laser_frequency_hz,
                )
            )
            if self.linear_plane is None:
                cube = decode_histogram_cube(
                    self.dataset,
                    bins=bins,
                    grid=grid,
                    threads=self.threads,
                    progress=self.status.emit,
                    cancelled=self.cancel_event.is_set,
                    prefer_native=True,
                    event_flag_mask=self.event_flag_mask,
                )
            else:
                cube = decode_histogram_plane(
                    self.dataset,
                    self.linear_plane,
                    bins=bins,
                    grid=grid,
                    threads=self.threads,
                    progress=self.status.emit,
                    cancelled=self.cancel_event.is_set,
                    prefer_native=True,
                    event_flag_mask=self.event_flag_mask,
                )
            self._complete(cube, "")
        except DecodeCancelled:
            self._complete(None, "Cancelled")
        # Convert unexpected worker failures into explicit user-facing
        # errors.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:
            self._complete(None, str(exc))


class IcsExportWorker(ResultWorker):
    """Export selected calibrated ICS arrays off-thread."""

    completed = Signal(object, str)
    status = Signal(str, float, float)

    def __init__(
        self,
        datasets: list[DatasetInfo],
        output_dir: Path,
        options: IcsExportOptions,
        filenames: dict[str, str],
        cached_cubes: dict[str, HistogramCube],
        plane_selection: dict[str, list[int]],
        output_directories: dict[str, Path] | None = None,
    ) -> None:
        super().__init__()
        self.datasets, self.output_dir, self.options = (
            datasets,
            output_dir,
            options,
        )
        self.filenames, self.cached_cubes = (filenames, cached_cubes)
        self.plane_selection = plane_selection
        self.output_directories = output_directories or {}
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request safe cancellation at the next bounded work
        boundary.
        """
        self.cancel_event.set()

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        try:
            results = export_ics_blocks(
                self.datasets,
                self.output_dir,
                self.options,
                cached_cubes=self.cached_cubes,
                filenames=self.filenames,
                plane_selection=self.plane_selection,
                output_directories=self.output_directories,
                progress=self.status.emit,
                cancelled=self.cancel_event.is_set,
            )
            self._complete(results, "")
        except IcsExportCancelled:
            self._complete([], "Cancelled")
        # Convert unexpected worker failures into explicit user-facing
        # errors.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:
            self._complete([], str(exc))


class PtuExportWorker(ResultWorker):
    """Export selected photon records off-thread."""

    completed = Signal(object, str)
    status = Signal(str, float, float)

    def __init__(
        self,
        datasets: list[DatasetInfo],
        output_dir: Path,
        options: PtuExportOptions,
        filenames: dict[str, str],
        plane_selection: dict[str, list[int]],
        output_directories: dict[str, Path] | None = None,
    ) -> None:
        super().__init__()
        self.datasets, self.output_dir, self.options = (
            datasets,
            output_dir,
            options,
        )
        self.filenames, self.plane_selection = (filenames, plane_selection)
        self.output_directories = output_directories or {}
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request safe cancellation at the next bounded work
        boundary.
        """
        self.cancel_event.set()

    def run(self) -> None:
        """Perform worker work and deliver success or explicit
        failure.
        """
        try:
            results = export_ptu_blocks(
                self.datasets,
                self.output_dir,
                self.options,
                filenames=self.filenames,
                plane_selection=self.plane_selection,
                output_directories=self.output_directories,
                progress=self.status.emit,
                cancelled=self.cancel_event.is_set,
            )
            self._complete(results, "")
        except PtuExportCancelled:
            self._complete([], "Cancelled")
        # Convert unexpected worker failures into explicit user-facing
        # errors.
        # pylint: disable-next=broad-exception-caught
        except Exception as exc:
            self._complete([], str(exc))
