#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Resolve and verify the exact hastegeo wheel used for deployment."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_release import (  # noqa: E402
    RELEASE_TAG,
    REPOSITORY,
    latest_stable,
    list_release_assets,
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


def emit_outputs(version: str, wheel_name: str, url: str) -> None:
    values = {
        "version": version,
        "wheel_name": wheel_name,
        "url": url,
    }
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
    args = parser.parse_args(argv)

    version, wheel_name, url = resolve_deploy_wheel(
        args.version, list_release_assets()
    )
    emit_outputs(version, wheel_name, url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
