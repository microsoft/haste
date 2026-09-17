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

from haste_artifact_protocol import (  # noqa: E402
    Protocol,
    artifact_name,
    producer_protocol,
    published_protocol,
)
from haste_artifacts import RCBuild, resolve_ci_build  # noqa: E402
from haste_release import (  # noqa: E402
    Resolution,
    list_release_assets,
    resolve,
    run_command,
    tags_pointing_at,
)


def emit_outputs(
    resolution: Resolution,
    *,
    build: RCBuild | None = None,
    source_date_epoch: int | None = None,
    protocol: Protocol = "legacy",
    name: str = "",
) -> None:
    """Write GitHub Actions outputs when GITHUB_OUTPUT is available."""
    values = {
        "version": resolution.version,
        "wheel_name": resolution.wheel_name,
        "channel": resolution.channel,
        "source_sha": resolution.source_sha,
        "source_tag": resolution.source_tag,
        "already_published": str(resolution.already_published).lower(),
        "rc_build_identity": (
            json.dumps(build.to_dict(), sort_keys=True) if build else ""
        ),
        "source_date_epoch": str(source_date_epoch or 0),
        "artifact_protocol": protocol,
        "artifact_name": name,
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
    parser.add_argument("--build-run-id")
    parser.add_argument("--build-attempt", default="1")
    parser.add_argument(
        "--artifact-protocol",
        choices=["legacy", "run-bound-v1", "auto", "produced"],
        default="run-bound-v1",
    )
    args = parser.parse_args(argv)

    protocol = args.artifact_protocol
    defer_protocol = protocol == "produced" and args.channel == "release"
    name = ""
    if args.build_run_id:
        if protocol == "auto":
            protocol = producer_protocol(args.build_run_id, args.build_attempt)
        elif protocol == "produced" and not defer_protocol:
            protocol = published_protocol(
                args.build_run_id, args.build_attempt
            )
        if not defer_protocol:
            name = artifact_name(
                args.build_run_id, args.build_attempt, protocol
            )
    elif protocol in {"auto", "produced"}:
        raise ValueError("Artifact protocol negotiation requires a build run")
    else:
        protocol = "legacy"

    build = None
    if (
        args.channel == "rc"
        and args.build_run_id
        and protocol == "run-bound-v1"
    ):
        if args.bump != "patch" or args.set_version:
            raise ValueError(
                "Build-bound RC versions use the frozen patch baseline and "
                "run ID; version overrides require a separate manual build."
            )
        build = resolve_ci_build(args.source_sha, args.build_run_id)
        source_epoch = build.source_date_epoch
        resolution = Resolution(
            version=build.version,
            wheel_name=build.wheel_name,
            channel="rc",
            source_sha=args.source_sha,
            source_tag="",
            already_published=False,
        )
    else:
        assets = list_release_assets()
        tags = (
            tags_pointing_at(args.source_sha)
            if args.channel == "release"
            else []
        )
        resolution = resolve(
            channel=args.channel,
            source_sha=args.source_sha,
            assets=assets,
            tags=tags,
            bump=args.bump,
            set_version=args.set_version,
        )
        source_epoch = int(
            run_command(
                [
                    "git",
                    "show",
                    "-s",
                    "--format=%ct",
                    args.source_sha,
                ]
            ).strip()
        )
    if defer_protocol:
        protocol = "legacy"
        if not resolution.already_published:
            protocol = published_protocol(
                args.build_run_id, args.build_attempt
            )
            name = artifact_name(
                args.build_run_id, args.build_attempt, protocol
            )
    emit_outputs(
        resolution,
        build=build,
        source_date_epoch=source_epoch,
        protocol=protocol,
        name=name,
    )

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(
                build.to_dict() if build else asdict(resolution), indent=2
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
