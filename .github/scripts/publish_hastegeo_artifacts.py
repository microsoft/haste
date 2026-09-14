#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Record image provenance and publish a verified complete RC artifact set."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_artifacts import (  # noqa: E402
    RCBuild,
    artifact_set,
    artifact_set_name,
    image_record,
    read_json,
    registry_fingerprint,
    validate_wheel_manifest,
    write_json,
)
from publish_hastegeo_wheel import publish_json_asset  # noqa: E402


def verify_image_configuration(build: RCBuild, configuration: dict) -> None:
    if (
        configuration.get("os") != "linux"
        or configuration.get("architecture") != "amd64"
    ):
        raise ValueError("RC worker image must be Linux amd64")
    labels = configuration.get("config", {}).get("Labels") or {}
    if (
        labels.get("org.opencontainers.image.revision") != build.source_sha
        or labels.get("org.opencontainers.image.version") != build.version
    ):
        raise ValueError("Registry image labels do not match the source build")


def record_image(
    build: RCBuild,
    family: str,
    registry: str,
    metadata: dict,
    configuration: dict,
) -> dict:
    verify_image_configuration(build, configuration)
    if (
        metadata.get("changeableAttributes", {}).get("writeEnabled")
        is not False
    ):
        raise ValueError("RC image must be locked before recording provenance")
    return image_record(
        build, family, metadata["digest"], registry_fingerprint(registry)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-image")
    check.add_argument("--identity", type=Path, required=True)
    check.add_argument("--configuration", type=Path, required=True)
    image = commands.add_parser("image")
    image.add_argument("--identity", type=Path, required=True)
    image.add_argument("--family", required=True)
    image.add_argument("--registry", required=True)
    image.add_argument("--metadata", type=Path, required=True)
    image.add_argument("--configuration", type=Path, required=True)
    image.add_argument("--output", type=Path, required=True)
    complete = commands.add_parser("complete")
    complete.add_argument("--identity", type=Path, required=True)
    complete.add_argument("--wheel-manifest", type=Path, required=True)
    complete.add_argument("--images", type=Path, required=True)
    complete.add_argument("--output-dir", type=Path, required=True)
    complete.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    build = RCBuild.from_dict(read_json(args.identity))
    if args.command == "check-image":
        verify_image_configuration(build, read_json(args.configuration))
    elif args.command == "image":
        result = record_image(
            build,
            args.family,
            args.registry,
            read_json(args.metadata),
            read_json(args.configuration),
        )
        write_json(args.output, result)
    else:
        manifest = read_json(args.wheel_manifest)
        validate_wheel_manifest(manifest, build)
        records = [
            read_json(path) for path in sorted(args.images.rglob("*.json"))
        ]
        result = artifact_set(manifest, records, build)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output = args.output_dir / artifact_set_name(build.version)
        write_json(output, result)
        if args.publish:
            publish_json_asset(output, result)
        print(f"Verified complete RC artifact set: {build.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
