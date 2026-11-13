"""Create or verify a complete release payload manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST_NAME = "RELEASE_MANIFEST.json"


def payload_hashes(root: Path) -> dict[str, dict[str, int | str]]:
    """Reject links and hash every payload file except the manifest."""
    result: dict[str, dict[str, int | str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Linked payload is not supported: {path}")
        if not path.is_file() or path == root / MANIFEST_NAME:
            continue
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result[path.relative_to(root).as_posix()] = {
            "size": path.stat().st_size,
            "sha256": digest,
        }
    if not result:
        raise ValueError("Refuse to certify an empty payload")
    return result


def create_manifest(root: Path) -> None:
    """Refuse to overwrite an existing release's manifest."""
    payload = payload_hashes(root)
    with (root / MANIFEST_NAME).open("x", encoding="utf-8") as stream:
        json.dump(
            {"schemaVersion": 1, "algorithm": "sha256", "files": payload},
            stream,
            indent=2,
        )
        stream.write("\n")


def verify_manifest(root: Path) -> bool:
    """Detect modified, missing and additional files."""
    manifest = json.loads((root / MANIFEST_NAME).read_text("utf-8"))
    return (
        isinstance(manifest, dict)
        and manifest.get("schemaVersion") == 1
        and manifest.get("algorithm") == "sha256"
        and manifest.get("files") == payload_hashes(root)
    )


def main() -> int:
    """Use a candidate directory without executing its payload."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "verify"))
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    root = args.folder.resolve()
    if not root.is_dir():
        parser.error("Supply an existing candidate directory")
    try:
        if args.operation == "create":
            create_manifest(root)
        elif not verify_manifest(root):
            print("FAIL: payload differs from its manifest")
            return 1
    except (OSError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1
    print(f"PASS: {args.operation} {root / MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
