"""Write and clean up the JSON, CSV and HTML export companions."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .metadata_reports import csv_report, html_report, metadata_rows


def companion_paths(target: Path) -> dict[str, Path]:
    """Keep companions next to their exact exported filename."""
    return {
        "json": Path(str(target) + ".json"),
        "csv": Path(str(target) + ".metadata.csv"),
        "html": Path(str(target) + ".metadata.html"),
    }


def export_path_available(target: Path) -> bool:
    """Do not overwrite data, provenance, reports or active writes."""
    return not any(
        path.exists() or path.with_name(path.name + ".part").exists()
        for path in (target, *companion_paths(target).values())
    )


def cleanup_export(target: Path) -> None:
    """Remove the current failed output and its companion files."""
    for path in (target, *companion_paths(target).values()):
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".part").unlink(missing_ok=True)


def write_companions(target: Path, sidecar: dict) -> dict[str, str]:
    """Stage every companion before publishing a complete bundle."""
    paths = companion_paths(target)
    sidecar["metadataReports"] = {
        kind: path.name for kind, path in paths.items() if kind != "json"
    }
    try:
        rows = metadata_rows(sidecar)
        contents = {
            "json": json.dumps(
                sidecar, indent=2, ensure_ascii=True, allow_nan=False
            ),
            "csv": csv_report(rows),
            "html": html_report(target, rows),
        }
        for kind, path in paths.items():
            temporary = path.with_name(path.name + ".part")
            temporary.write_text(
                contents[kind],
                encoding="utf-8-sig" if kind == "csv" else "utf-8",
                newline="",
            )
        for path in paths.values():
            os.replace(path.with_name(path.name + ".part"), path)
    except Exception:
        cleanup_export(target)
        raise
    return {kind: str(path) for kind, path in paths.items() if kind != "json"}
