"""Generate download redirects for a successful standalone build."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from datetime import datetime
from html import escape
from pathlib import Path
from typing import TypedDict

PLATFORMS = {
    "standalone-Windows_x86_64": ("windows-x64", "Windows (x86-64)"),
    "standalone-macOS_arm64": ("macos-arm64", "macOS (Apple Silicon)"),
    "standalone-macOS_x86_64": ("macos-x64", "macOS (Intel)"),
    "standalone-Linux_x86_64": ("linux-x64", "Linux (x86-64)"),
}


class Artifact(TypedDict):
    """Fields loaded from GitHub's workflow-run artifact API."""

    name: str
    id: int
    expired: bool
    expires_at: str


def latest_artifacts(artifacts: list[Artifact]) -> dict[str, Artifact]:
    """Find four usable downloads across build attempts."""
    latest: dict[str, tuple[int, Artifact]] = {}
    for artifact in artifacts:
        name, _, suffix = artifact["name"].partition("-attempt-")
        if name not in PLATFORMS or artifact["expired"]:
            continue
        attempt = int(suffix or "1")
        if name not in latest or attempt > latest[name][0]:
            latest[name] = (attempt, artifact)
    available = {name: artifact for name, (_, artifact) in latest.items()}
    missing = PLATFORMS.keys() - available.keys()
    if missing:
        raise ValueError(f"Missing usable build artifacts: {sorted(missing)}")
    return available


def write_page(path: Path, title: str, body: str, redirect: str = "") -> None:
    """Write a complete page with an optional immediate redirect."""
    target = escape(redirect)
    refresh = (
        f'<meta http-equiv="refresh" content="0; url={target}">'
        if target
        else ""
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, '
        'initial-scale=1">\n'
        f"<title>{escape(title)}</title>\n{refresh}\n</head>\n<body>\n"
        f"<main><h1>{escape(title)}</h1>{body}</main>\n</body>\n</html>\n",
        encoding="utf-8",
    )


def write_downloads(
    output: Path, artifacts: list[Artifact], run_url: str, version: str
) -> None:
    """Generate the four redirects and a download index."""
    available = latest_artifacts(artifacts)
    index_links = []
    for name, (slug, label) in PLATFORMS.items():
        artifact = available[name]
        url = f"{run_url}/artifacts/{artifact['id']}"
        expires = datetime.fromisoformat(artifact["expires_at"]).date()
        title = f"LIFTOFF {version} for {label}"
        body = (
            f'<p><a href="{escape(url)}">Download for {label}</a></p>\n'
            f"<p>Sign in to GitHub to download this build. The artifact "
            f"expires on {expires.day} {expires:%B %Y}.</p>\n"
        )
        write_page(
            output / "downloads" / slug / "index.html", title, body, url
        )
        index_links.append(f'<li><a href="downloads/{slug}/">{label}</a></li>')
    index_body = "<p>Sign in to GitHub to download a build.</p>\n"
    index_body += f"<ul>{''.join(index_links)}</ul>\n"
    write_page(
        output / "index.html", f"LIFTOFF {version} downloads", index_body
    )


def main() -> None:
    """Read GitHub artifact metadata and write the download site."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    server = os.environ["GITHUB_SERVER_URL"]
    run_id = os.environ["GITHUB_RUN_ID"]
    run_url = f"{server}/{repository}/actions/runs/{run_id}"
    with Path("pyproject.toml").open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    artifacts = [
        artifact
        for page in json.load(sys.stdin)
        for artifact in page["artifacts"]
    ]
    write_downloads(args.output, artifacts, run_url, version)


if __name__ == "__main__":
    main()
