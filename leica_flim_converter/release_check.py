"""Opt-in verification using the actual source or frozen application."""

from __future__ import annotations

# Release checks inspect the production workspace and its workers.
# pylint: disable=protected-access
import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from time import perf_counter, sleep

import numpy as np
import PIL
import PySide6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .dataset import DatasetInfo
from .export_inspection import inspect_ptu, read_ics
from .gui import MainWindow
from .gui_helpers import _group_key_2
from .ics import write_ics
from .native_decoder import decode_histogram_plane, native_decoder_info
from .ptu_export import PtuExportOptions, write_dataset_ptu
from .raw_selection import load_filter_library
from .timing import time_grid
from .version import APPLICATION_VERSION, application_metadata


def _wait(app: QApplication, finished: Callable[[], bool]) -> None:
    deadline = perf_counter() + 120
    while not finished():
        app.processEvents()
        if perf_counter() > deadline:
            raise TimeoutError("Release verification worker did not finish")
        sleep(0.01)
    app.processEvents()


def _decode_check(
    dataset: DatasetInfo, output: Path, plane: int = 0
) -> dict[str, object]:
    """Exercise calibrated decoding and small round-trip exports."""
    grid = time_grid(dataset, None)
    cube = decode_histogram_plane(
        dataset, plane, bins=grid.bins, grid=grid, threads=4, event_flag_mask=7
    )
    decay = cube.counts.sum(axis=(1, 2), dtype=np.uint64)
    result: dict[str, object] = {
        "source": str(dataset.source),
        "acquisition": dataset.acquisition_name,
        "sequence": dataset.sequence_index,
        "channel": dataset.channel_index,
        "plane": plane,
        "planeLabel": dataset.plane_label(plane),
        "planeCoverage": dataset.plane_coverage_metadata,
        "excluded": cube.overflow_events,
        "events": cube.events,
        "backend": cube.backend,
        "shape": list(cube.counts.shape),
        "decaySha256": hashlib.sha256(decay.tobytes()).hexdigest(),
        "thumbnail": dataset.thumbnail is not None,
    }
    if cube.events <= 0 or "native" not in cube.backend:
        raise RuntimeError(f"Native decoding failed: {result}")
    if dataset.width * dataset.height <= 256:
        identity = hashlib.sha256(dataset.key.encode()).hexdigest()[:12]
        stem = f"check-{identity}-p{plane}"
        ptu = output / f"{stem}.ptu"
        write_dataset_ptu(
            dataset,
            plane,
            ptu,
            PtuExportOptions(),
            progress=lambda _message: None,
            cancelled=lambda: False,
        )
        if inspect_ptu(ptu).photons != cube.events + cube.overflow_events:
            raise RuntimeError("Bundled PTU round trip failed")
        ics = output / f"{stem}.ics"
        write_ics(ics, cube.counts, dataset, grid=grid)
        if not np.array_equal(read_ics(ics).counts, cube.counts):
            raise RuntimeError("Bundled ICS round trip failed")
        result["exports"] = "PTU and ICS passed"
    return result


def _gui_check(
    app: QApplication,
    window: MainWindow,
    output: Path,
    target: DatasetInfo | None = None,
) -> dict[str, object]:
    """Inspect aligned controls, navigation and production workers."""
    item = next(
        window.block_list.item(row)
        for row in range(window.block_list.count())
        if isinstance(
            found := window.block_list.item(row).data(
                Qt.ItemDataRole.UserRole
            ),
            DatasetInfo,
        )
        and (
            found.key == target.key
            if target
            else found.width * found.height <= 256
        )
    )
    window.select_block(item)
    _wait(app, lambda: window.decode_worker is None)
    acquisition = target or window.selected
    if acquisition is None:
        raise RuntimeError("No GUI acquisition was selected")
    pairs = list(window.current_acquisition_group())
    window.pair_selector.set_selection(dataset.key for dataset in pairs)
    _wait(app, lambda: window.decode_worker is None)
    last_plane = acquisition.preview_plane_count - 1
    window.plane_combo.setCurrentIndex(window.plane_combo.findData(last_plane))
    _wait(app, lambda: window.decode_worker is None)
    panels = window._multichannel_channel_panels
    tiles = acquisition.stage_count if acquisition.mosaic is not None else 1
    if not panels or len(panels) != len(pairs) * tiles:
        raise RuntimeError(
            f"GUI comparison failed for {acquisition.acquisition_name}: "
            f"{len(panels or [])} panels, {len(pairs)} pairs, {tiles} tiles; "
            f"{window.status_label.text()}"
        )
    graphs = window.histogram.graph_panels()
    if len(graphs) != len(pairs):
        raise RuntimeError("GUI combined graph count is incorrect")
    if tiles > 1:
        button = window.histogram.separate_tiles_button
        button.click()
        if len(window.histogram.graph_panels()) != len(panels):
            raise RuntimeError("GUI separate tile graph count is incorrect")
        button.click()
    report: dict[str, object] = {
        "pairCount": len(pairs),
        "imageCount": len(panels),
        "tileCount": tiles,
        "plane": window.current_plane,
        "planeLabel": window.plane_combo.currentText(),
        "events": [panel["events"] for panel in panels],
        "status": window.status_label.text(),
        "screenshotSaved": window.grab().save(str(output / "pairs.png")),
    }
    if window.current_plane != last_plane:
        raise RuntimeError("Bundled T/Z navigation failed")
    return report


def _data_checks(datasets, output, expected_unreadable):
    """Fail unexpected errors and verify named rejection cases."""
    decoded, rejected = [], []
    for dataset in datasets:
        if dataset.acquisition_name in expected_unreadable:
            try:
                decode_histogram_plane(dataset, 0, bins=32, threads=4)
            except (RuntimeError, ValueError) as error:
                rejected.append(
                    {
                        "acquisition": dataset.acquisition_name,
                        "error": str(error),
                    }
                )
            else:
                raise RuntimeError("Expected unreadable entry decoded")
        else:
            for plane in sorted({0, dataset.plane_count - 1}):
                decoded.append(_decode_check(dataset, output, plane))
    if expected_unreadable != {row["acquisition"] for row in rejected}:
        raise RuntimeError("Expected unreadable acquisition was not checked")
    return decoded, rejected


def _gui_checks(app, window, output, names):
    """Exercise small fixtures and explicitly requested real views."""
    checked, seen = [], set()
    for dataset in window.datasets:
        key = _group_key_2(dataset)
        if key in seen or (
            dataset.width * dataset.height > 256
            and dataset.acquisition_name not in names
        ):
            continue
        seen.add(key)
        directory = output / f"gui-{len(checked)}"
        directory.mkdir(exist_ok=True)
        checked.append(_gui_check(app, window, directory, dataset))
    return checked


def main() -> None:
    """Write bounded release evidence without requiring Python tools."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-release", type=Path, required=True)
    parser.add_argument("--verify-lif", type=Path, action="append", default=[])
    parser.add_argument("--expect-unreadable", action="append", default=[])
    parser.add_argument(
        "--verify-gui-acquisition", action="append", default=[]
    )
    args = parser.parse_args()
    output = args.verify_release.resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    if not isinstance(app, QApplication):
        raise RuntimeError("Release checks need a GUI application instance")
    window = MainWindow()
    window.show()
    app.processEvents()
    report: dict[str, object] = {
        "application": application_metadata(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "python": sys.version,
        "qtPlatform": app.platformName(),
        "windowTitle": window.windowTitle(),
        "native": native_decoder_info(),
        "filterLibrary": load_filter_library()._name,
        "dependencies": {
            module.__name__: {
                "version": module.__version__,
                "path": module.__file__,
            }
            for module in (np, PIL, PySide6)
        },
        "startupScreenshot": window.grab().save(str(output / "startup.png")),
    }
    try:
        if APPLICATION_VERSION not in window.windowTitle():
            raise RuntimeError("Window title has the wrong version")
        if args.verify_lif:
            window._load_files(args.verify_lif)
            _wait(app, lambda: window.scan_worker is None)
            if not window.datasets:
                raise RuntimeError("Bundled LIF indexing failed")
            report["decoded"], report["rejected"] = _data_checks(
                window.datasets, output, set(args.expect_unreadable)
            )
            report["gui"] = _gui_checks(
                app, window, output, set(args.verify_gui_acquisition)
            )
        report["passed"] = True
    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
        report["passed"] = False
        report["error"] = str(error)
        raise
    finally:
        window.close()
        _wait(app, lambda: not window.isVisible())
        (output / "result.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
