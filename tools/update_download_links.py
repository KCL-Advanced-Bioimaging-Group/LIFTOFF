"""Prepare a README update from a successful standalone build run."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from typing import TypedDict

START = "<!-- standalone-downloads:start -->"
END = "<!-- standalone-downloads:end -->"
PLATFORMS = {
    "standalone-Windows_x86_64": "Windows (x86-64)",
    "standalone-macOS_arm64": "macOS (Apple Silicon)",
    "standalone-macOS_x86_64": "macOS (Intel)",
    "standalone-Linux_x86_64": "Linux (x86-64)",
}
COMMIT_QUERY = """
mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { url } }
}
"""


class Artifact(TypedDict):
    """Fields loaded from GitHub's workflow-run artifact API."""

    name: str
    id: int
    expired: bool
    expires_at: str


def refresh_readme(
    readme: str, artifacts: list[Artifact], run_url: str, version: str
) -> str:
    """Replace the marked block when all four links are available."""
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError("Expected one pair of README download markers")
    before, _, remainder = readme.partition(START)
    _, end, after = remainder.partition(END)
    if not end:
        raise ValueError("README download markers are out of order")

    available = {
        artifact["name"]: artifact
        for artifact in artifacts
        if not artifact["expired"]
    }
    missing = PLATFORMS.keys() - available.keys()
    if missing:
        raise ValueError(f"Missing usable build artifacts: {sorted(missing)}")
    links = [
        f"- [Download for {label}]"
        f"({run_url}/artifacts/{available[name]['id']})"
        for name, label in PLATFORMS.items()
    ]
    expires = min(
        datetime.fromisoformat(available[name]["expires_at"]).date()
        for name in PLATFORMS
    )
    return "\n".join(
        (
            before + START,
            f"Sign in to GitHub, then download the LIFTOFF {version} "
            "build for your computer.",
            "",
            *links,
            "",
            f"These download links expire on {expires.day} {expires:%B %Y}.",
            END + after,
        )
    )


def main() -> None:
    """Print a guarded commit request for the README file alone."""
    repository = os.environ["GITHUB_REPOSITORY"]
    server = os.environ["GITHUB_SERVER_URL"]
    run_id = os.environ["GITHUB_RUN_ID"]
    run_url = f"{server}/{repository}/actions/runs/{run_id}"
    with Path("pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    readme = Path("README.md").read_text(encoding="utf-8")
    updated = refresh_readme(
        readme, json.load(sys.stdin)["artifacts"], run_url, version
    )
    if updated == readme:
        return
    payload = {
        "branch": {"id": os.environ["LIFTOFF_MAIN_REF_ID"]},
        "expectedHeadOid": os.environ["GITHUB_SHA"],
        "message": {
            "headline": "Refresh standalone download links",
            "body": f"Build artifacts from {run_url}",
        },
        "fileChanges": {
            "additions": [
                {
                    "path": "README.md",
                    "contents": b64encode(updated.encode("utf-8")).decode(
                        "ascii"
                    ),
                }
            ]
        },
    }
    json.dump(
        {"query": COMMIT_QUERY, "variables": {"input": payload}}, sys.stdout
    )


if __name__ == "__main__":
    main()
