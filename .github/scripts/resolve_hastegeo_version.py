#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Resolve the exact hastegeo RC or stable version for a CI build."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_release import (  # noqa: E402
    Resolution,
    list_release_assets,
    resolve,
    tags_pointing_at,
)


def emit_outputs(resolution: Resolution) -> None:
    """Write GitHub Actions outputs when GITHUB_OUTPUT is available."""
    values = {
        "version": resolution.version,
        "wheel_name": resolution.wheel_name,
        "channel": resolution.channel,
        "source_sha": resolution.source_sha,
        "source_tag": resolution.source_tag,
        "already_published": str(resolution.already_published).lower(),
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
    parser.add_argument("--channel", choices=["rc", "release"], required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
    )
    parser.add_argument("--set-version", default="")
    parser.add_argument("--json-output")
    args = parser.parse_args(argv)

    assets = list_release_assets()
    tags = (
        tags_pointing_at(args.source_sha) if args.channel == "release" else []
    )
    resolution = resolve(
        channel=args.channel,
        source_sha=args.source_sha,
        assets=assets,
        tags=tags,
        bump=args.bump,
        set_version=args.set_version,
    )
    emit_outputs(resolution)

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(asdict(resolution), indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
