"""Benchmark full native-period previews on the current target host."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import sys
from pathlib import Path
from time import perf_counter

from leica_flim_converter.catalog import DatasetInfo, scan_lif
from leica_flim_converter.decay import native_period_bins
from leica_flim_converter.native_decoder import decode_histogram_plane


def benchmark_dataset(
    dataset: DatasetInfo,
    threads: list[int],
    repeats: int,
) -> list[dict]:
    """Warm each population, then measure identical complete
    previews.
    """
    results = []
    masks = (
        (256, 512, 1024) if dataset.storage_format == "lmsraw" else (7, 3, 1)
    )
    bins = native_period_bins(
        dataset.clock_period_s, dataset.laser_frequency_hz
    )
    for mask in masks:
        for count in threads:
            timings = []
            hashes = set()
            photons = set()
            for iteration in range(repeats + 1):
                started = perf_counter()
                cube = decode_histogram_plane(
                    dataset,
                    0,
                    bins=bins,
                    threads=count,
                    event_flag_mask=mask,
                )
                elapsed = perf_counter() - started
                hashes.add(
                    hashlib.sha256(
                        cube.counts.astype("<u4").tobytes()
                    ).hexdigest()
                )
                photons.add(cube.events)
                del cube
                gc.collect()
                if iteration:
                    timings.append(elapsed)
            if len(hashes) != 1 or len(photons) != 1:
                raise RuntimeError(
                    "Repeated previews produced different results"
                )
            result = {
                "file": dataset.source.name,
                "memory": dataset.memory_id,
                "channel": dataset.channel_index,
                "plane": 0,
                "mask": mask,
                "threads": count,
                "photons": photons.pop(),
                "sha256": hashes.pop(),
                "seconds": timings,
                "medianSeconds": statistics.median(timings),
            }
            results.append(result)
            print(
                result["file"],
                mask,
                count,
                round(result["medianSeconds"], 3),
                flush=True,
            )
    return results


def main() -> None:
    """Benchmark explicit files without assuming developer data
    paths.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--threads", nargs="+", type=int, default=[1, 4, 16])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--memory", nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or any(count < 1 for count in args.threads):
        parser.error("Repetitions and thread counts must be positive")
    report = {
        "system": platform.platform(),
        "python": sys.version,
        "method": "one warm-up, then repeated sequential full previews",
        "cases": [],
    }
    for index, path in enumerate(args.files):
        datasets = scan_lif(path)
        memory = args.memory[index] if index < len(args.memory) else None
        dataset = next(
            (item for item in datasets if item.memory_id == memory),
            datasets[0],
        )
        report["cases"].extend(
            benchmark_dataset(dataset, args.threads, args.repeats)
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
