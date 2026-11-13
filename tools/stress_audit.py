"""Resume a bounded scientific audit without altering supplied data."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path

import numpy as np

from leica_flim_converter.catalog import scan_lif
from leica_flim_converter.dataset import DatasetInfo
from leica_flim_converter.export_inspection import (
    inspect_ptu,
    read_ics,
    rehistogram_arrivals,
)
from leica_flim_converter.ics_export import IcsExportOptions, export_ics_blocks
from leica_flim_converter.native_decoder import (
    decode_histogram_cube,
    decode_histogram_plane,
)
from leica_flim_converter.ptu_export import PtuExportOptions, export_ptu_blocks
from leica_flim_converter.timing import time_grid


@dataclass
class AuditLog:
    """Flush each result so interrupted audits can resume."""

    path: Path
    completed: set[str] = field(default_factory=set)
    active: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                result = json.loads(line)
                if result["status"] != "failed":
                    self.completed.add(result["id"])

    def check(self, identity: str, action: Callable[[], dict]) -> None:
        """Record failures and continue independent cases."""
        self.active.add(identity)
        if identity in self.completed:
            return
        print(f"Checking {identity}", flush=True)
        started = time.perf_counter()
        result: dict
        try:
            result = {"id": identity, "status": "passed", **action()}
        except Exception as error:  # pylint: disable=broad-exception-caught
            result = {
                "id": identity,
                "status": "failed",
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        if result["status"] != "failed":
            self.completed.add(identity)
        result.setdefault("seconds", time.perf_counter() - started)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result) + "\n")
        print(f"{result['status']}: {identity}", flush=True)

    def finish(self) -> int:
        """Report current cases, preserving the full failure history."""
        latest = {
            row["id"]: row
            for row in map(
                json.loads, self.path.read_text(encoding="utf-8").splitlines()
            )
        }
        results = [latest[identity] for identity in self.active]
        failed = [row for row in results if row["status"] == "failed"]
        summary = {
            "activeCases": len(results),
            "failed": len(failed),
            "passed": len(results) - len(failed),
            "handledInvalid": sum("handledInvalid" in row for row in results),
            "failures": [
                {"id": row["id"], "error": row["error"]} for row in failed
            ],
            "historicalCasesSuperseded": len(set(latest) - self.active),
        }
        self.path.with_suffix(".summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        return int(bool(failed))


def _check_round_trip(
    dataset, cube, image, photons, sidecar, ptu_cube
) -> dict:
    np.testing.assert_array_equal(image.counts, cube.counts)
    assert dataset.clock_period_s is not None
    histogram, excluded = rehistogram_arrivals(
        photons, image, dataset.clock_period_s
    )
    np.testing.assert_array_equal(
        ptu_cube.counts.sum(axis=(1, 2), dtype=np.uint64), histogram
    )
    assert photons.photons == ptu_cube.events + ptu_cube.overflow_events
    assert photons.monotonic_macrotime
    assert (
        sidecar["photonAccounting"]["selectedPhotons"]
        == cube.events + cube.overflow_events
    )
    assert (
        sidecar["photonAccounting"]["excludedOutsideTimeWindow"]
        == cube.overflow_events
    )
    assert excluded == ptu_cube.overflow_events
    return {
        "photons": photons.photons,
        "excluded": excluded,
        "countsSha256": hashlib.sha256(memoryview(cube.counts)).hexdigest(),
        "ptu": photons.metadata(),
        "icsHeader": image.header,
        "shape": list(image.counts.shape),
        "alignment": cube.spatial_transform,
        "alignmentConfirmed": cube.spatial_alignment_confirmed,
        "referenceEvents": cube.reference_events,
        "eventDifference": cube.event_difference,
    }


def _export_case(
    dataset, plane, mask, bins, directory, compressed_rows
) -> dict:
    """Check images and arrival streams, then discard payloads."""
    grid = time_grid(dataset, bins)
    cube = decode_histogram_plane(
        dataset,
        plane,
        bins=grid.bins,
        grid=grid,
        threads=4,
        event_flag_mask=mask,
    )
    selection = {dataset.key: [plane]}
    image_result = export_ics_blocks(
        [dataset],
        directory,
        IcsExportOptions(
            bins=bins,
            event_flag_mask=mask,
            threads=4,
            compression="gzip" if plane % 2 else "uncompressed",
        ),
        plane_selection=selection,
        filenames={dataset.key: "probe.ics"},
        cached_cubes={dataset.key: cube},
    )[0]
    assert image_result["status"] == "exported", image_result
    ptu_dataset = dataset
    ptu_cube = cube
    if dataset.storage_format == "compressed" and compressed_rows:
        ranges = [
            dataset.plane_row_range(p) for p in range(dataset.plane_count)
        ]
        first, length = ranges[plane]
        ranges[plane] = first, min(length, compressed_rows)
        ptu_dataset = replace(
            dataset,
            plane_row_ranges=tuple(ranges),
            intensity_start=None,
            intensity_end=None,
            intensity_plane_starts=(),
            total_photons=None,
        )
        ptu_cube = decode_histogram_plane(
            ptu_dataset,
            plane,
            bins=grid.bins,
            grid=grid,
            threads=4,
            event_flag_mask=mask,
        )
    ptu_result = export_ptu_blocks(
        [ptu_dataset],
        directory,
        PtuExportOptions(event_flag_mask=mask),
        plane_selection=selection,
        filenames={dataset.key: "probe.ptu"},
    )[0]
    assert ptu_result["status"] == "exported", ptu_result
    image = read_ics(Path(image_result["path"]))
    photons = inspect_ptu(Path(ptu_result["path"]))
    sidecar = json.loads(Path(image_result["sidecar"]).read_text("utf-8"))
    evidence = _check_round_trip(
        dataset, cube, image, photons, sidecar, ptu_cube
    )
    assert dataset.plane_indices(plane) == (
        sidecar["plane"]["tIndexZeroBased"],
        sidecar["plane"]["zIndexZeroBased"],
    )
    if dataset.mosaic is not None:
        assert sidecar["mosaic"][
            "tileIndexZeroBased"
        ] == dataset.plane_stage_index(plane)
    for result in (image_result, ptu_result):
        payload = Path(result["path"]).resolve()
        assert payload.is_relative_to(directory.resolve())
        payload.unlink()
    return {
        "dataset": dataset.key,
        "fullImagePhotons": cube.events + cube.overflow_events,
        "ptuEncodedRows": ptu_dataset.plane_row_range(plane)[1],
        "sourceEncodedRows": dataset.plane_row_range(plane)[1],
        "plane": plane,
        "mask": mask,
        "bins": bins,
        **evidence,
    }


def _invalid_case(dataset: DatasetInfo, directory: Path) -> dict:
    """Incomplete geometry must not publish scientific data."""
    reason = ""
    directory = directory / "guard-check"
    try:
        decode_histogram_plane(dataset, 0, bins=16, threads=1)
    except RuntimeError as error:
        reason = str(error)
    else:
        raise AssertionError("Unresolved acquisition was decoded")
    outputs = [
        *export_ics_blocks(
            [dataset], directory, plane_selection={dataset.key: [0]}
        ),
        *export_ptu_blocks(
            [dataset], directory, plane_selection={dataset.key: [0]}
        ),
    ]
    assert len(outputs) == 2 and all(r["status"] == "failed" for r in outputs)
    assert not list(directory.glob("*.ics"))
    assert not list(directory.glob("*.ptu"))
    return {"dataset": dataset.key, "handledInvalid": reason}


def run_exports(
    source: Path, output: Path, compressed_rows: int | None, workers: int = 1
) -> int:
    """Exercise every plane and all three named photon selections."""
    log = AuditLog(output / "full-exports.jsonl")
    jobs = []
    for path in sorted(source.rglob("*.lif")):
        for dataset in scan_lif(path):
            token = hashlib.sha256(dataset.key.encode()).hexdigest()[:16]
            if dataset.repetition_storage_model == "unresolved":
                log.active.add(dataset.key)
                if dataset.key not in log.completed:
                    jobs.append(
                        (
                            dataset.key,
                            partial(
                                _invalid_case,
                                dataset,
                                output / "payloads" / token,
                            ),
                        )
                    )
                continue
            for plane in range(dataset.plane_count):
                for index, mask in enumerate((7, 3, 1)):
                    bins = (None, 128, 256)[(plane + index) % 3]
                    identity = f"{dataset.key}|p{plane}|m{mask}"
                    directory = output / "payloads" / f"{token}-{plane}-{mask}"
                    log.active.add(identity)
                    if identity not in log.completed:
                        jobs.append(
                            (
                                identity,
                                partial(
                                    _export_case,
                                    dataset,
                                    plane,
                                    mask,
                                    bins,
                                    directory,
                                    compressed_rows,
                                ),
                            )
                        )
    if workers == 1:
        for identity, action in jobs:
            log.check(identity, action)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_timed_action, action): identity
                for identity, action in jobs
            }
            for future in as_completed(futures):
                log.check(futures[future], future.result)
    return log.finish()


def _timed_action(action: Callable[[], dict]) -> dict:
    started = time.perf_counter()
    result: dict
    try:
        result = action()
    except Exception as error:  # pylint: disable=broad-exception-caught
        result = {
            "status": "failed",
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
    result["seconds"] = time.perf_counter() - started
    return result


def _inspect_vendor_ics(path: Path) -> dict:
    """Read declared vendor axis orders independently of our writer."""
    header = {}
    with path.open("rb") as stream:
        while True:
            line = stream.readline()
            if not line:
                raise ValueError("Truncated ICS header")
            fields = line.decode("ascii").strip().split()
            if fields and fields[0] == "end":
                break
            if len(fields) > 2:
                header["/".join(fields[:2])] = fields[2:]
        payload = stream.read()
    bits, *sizes = map(int, header["layout/sizes"])
    assert header["representation/format"] == ["integer"]
    assert header["representation/sign"] == ["unsigned"]
    byte_order = header["representation/byte_order"]
    assert byte_order in (["little"], [str(i + 1) for i in range(bits // 8)])
    if header["representation/compression"] == ["gzip"]:
        payload = gzip.decompress(payload)
    else:
        assert header["representation/compression"] == ["uncompressed"]
    counts = np.frombuffer(payload, dtype=f"<u{bits // 8}")
    assert counts.size == int(np.prod(sizes))
    return {
        "storageSizes": sizes,
        "header": header,
        "photons": int(counts.sum(dtype=np.uint64)),
    }


def _reference_file(path: Path) -> dict:
    if path.suffix.lower() == ".ptu":
        return inspect_ptu(path).metadata()
    if path.suffix.lower() == ".ics":
        return _inspect_vendor_ics(path)
    if path.suffix.lower() == ".json":
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        return {"rootType": type(document).__name__}
    return {"workspaceLogBytes": path.stat().st_size}


def run_references(source: Path, output: Path) -> int:
    """Read every supplied comparison payload and metadata file."""
    log = AuditLog(output / "supplied-exports.jsonl")
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix.lower() in {
            ".ptu",
            ".ics",
            ".json",
            ".sptl",
        }:
            log.check(str(path), lambda target=path: _reference_file(target))
    return log.finish()


def _overview_case(dataset: DatasetInfo, mask: int) -> dict:
    grid = time_grid(dataset, 32)
    overview = decode_histogram_cube(
        dataset,
        bins=grid.bins,
        grid=grid,
        threads=4,
        event_flag_mask=mask,
    )
    expected = np.zeros_like(overview.counts, dtype=np.uint64)
    events = excluded = 0
    for plane in range(dataset.plane_count):
        cube = decode_histogram_plane(
            dataset,
            plane,
            bins=grid.bins,
            grid=grid,
            threads=4,
            event_flag_mask=mask,
        )
        expected += cube.counts
        events += cube.events
        excluded += cube.overflow_events
    np.testing.assert_array_equal(overview.counts, expected)
    assert (overview.events, overview.overflow_events) == (events, excluded)
    return {
        "planes": dataset.plane_count,
        "events": events,
        "excluded": excluded,
    }


def run_overviews(source: Path, output: Path) -> int:
    """Compare every summed T/Z image against its individual planes."""
    log = AuditLog(output / "overviews.jsonl")
    for path in sorted(source.rglob("*.lif")):
        for dataset in scan_lif(path):
            if (
                dataset.repetition_storage_model == "unresolved"
                or dataset.plane_count <= 1
                or dataset.stage_count > 1
            ):
                continue
            for mask in (7, 3, 1):
                log.check(
                    f"{dataset.key}|m{mask}",
                    partial(_overview_case, dataset, mask),
                )
    return log.finish()


def main() -> int:
    """Write resumable evidence beneath a separate audit directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compressed-ptu-rows", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--phase",
        choices=("exports", "references", "overviews"),
        required=True,
    )
    options = parser.parse_args()
    if not 1 <= options.workers <= 16:
        parser.error("Choose between 1 and 16 independent export workers")
    source, output = options.input.resolve(), options.output.resolve()
    if output == source or output.is_relative_to(source):
        parser.error(
            "Audit output must be outside the supplied data directory"
        )
    if options.phase == "exports":
        return run_exports(
            source, output, options.compressed_ptu_rows, options.workers
        )
    if options.phase == "references":
        return run_references(source, output)
    return run_overviews(source, output)


if __name__ == "__main__":
    raise SystemExit(main())
