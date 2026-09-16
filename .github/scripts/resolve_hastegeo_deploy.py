#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Resolve and verify the exact hastegeo wheel used for deployment."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_artifacts import (  # noqa: E402
    artifact_set_name,
    read_json,
    validate_artifact_set,
)
from haste_release import (  # noqa: E402
    RELEASE_TAG,
    REPOSITORY,
    latest_stable,
    list_release_assets,
    run_command,
)

DEPLOY_VERSION_RE = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)(?:\.?rc0*(\d+))?$",
    re.IGNORECASE,
)


def canonicalize_version(value: str) -> str:
    """Canonicalize stable or RC input, including ``rc01`` -> ``rc1``."""
    match = DEPLOY_VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(
            f"Invalid hastegeo version {value!r}; expected X.Y.Z or X.Y.ZrcN"
        )
    major, minor, patch = (int(part) for part in match.groups()[:3])
    rc = match.group(4)
    base = f"{major}.{minor}.{patch}"
    return f"{base}rc{int(rc)}" if rc is not None else base


def resolve_deploy_wheel(
    requested_version: str, assets: Sequence[str]
) -> tuple[str, str, str]:
    """Return canonical version, wheel filename, and public URL."""
    if requested_version.strip():
        version = canonicalize_version(requested_version)
    else:
        version = ".".join(str(part) for part in latest_stable(assets))

    wheel_name = f"hastegeo-{version}-py3-none-any.whl"
    if wheel_name not in assets:
        raise ValueError(
            f"hastegeo release asset does not exist: {wheel_name}"
        )
    url = (
        f"https://github.com/{REPOSITORY}/releases/download/"
        f"{RELEASE_TAG}/{wheel_name}"
    )
    return version, wheel_name, url


def resolve_rc_artifact_set(
    version: str, source_sha: str, assets: Sequence[str]
) -> dict:
    name = artifact_set_name(version)
    if not source_sha:
        raise ValueError(
            "RC deployments require the exact application source SHA"
        )
    if name not in assets:
        raise ValueError("RC artifact set is incomplete or lacks provenance")
    with tempfile.TemporaryDirectory() as directory:
        run_command(
            [
                "gh",
                "release",
                "download",
                RELEASE_TAG,
                "--repo",
                REPOSITORY,
                "--pattern",
                name,
                "--dir",
                directory,
            ]
        )
        manifest = read_json(Path(directory) / name)
    validate_artifact_set(manifest, version, source_sha)
    return manifest


def emit_outputs(
    version: str, wheel_name: str, url: str, artifact_set: dict | None = None
) -> None:
    values = {
        "version": version,
        "wheel_name": wheel_name,
        "url": url,
    }
    if artifact_set is not None:
        images = artifact_set["images"]
        values.update(
            artifact_set=json.dumps(artifact_set, sort_keys=True),
            registry_sha256=images["training"]["registry_sha256"],
            training_digest=images["training"]["digest"],
            imageprep_digest=images["imageryprep"]["digest"],
        )
    for key, value in values.items():
        print(f"{key}={value}")

    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="")
    parser.add_argument("--source-sha", default="")
    args = parser.parse_args(argv)

    assets = list_release_assets()
    version, wheel_name, url = resolve_deploy_wheel(args.version, assets)
    manifest = None
    if "rc" in version:
        manifest = resolve_rc_artifact_set(version, args.source_sha, assets)
        url += "#sha256=" + manifest["wheel"]["wheel_sha256"]
    emit_outputs(version, wheel_name, url, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
