#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Validate and publish one immutable hastegeo wheel release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_artifacts import (  # noqa: E402
    RCBuild,
    provenance_name,
    read_json,
    validate_wheel_manifest,
    wheel_manifest,
    write_json,
)
from haste_release import (  # noqa: E402
    RC_VERSION_RE,
    RELEASE_TAG,
    REPOSITORY,
    STABLE_VERSION_RE,
    list_release_assets,
)


@dataclass(frozen=True)
class WheelIdentity:
    """Validated identity of a wheel artifact."""

    path: Path
    version: str
    filename: str
    sha256: str


def run_command(command: Sequence[str]) -> str:
    """Run a command and return stdout, failing on any error."""
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def sha256_file(path: Path) -> str:
    """Return the SHA256 digest for ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_wheel(
    wheel_path: Path, expected_version: str, channel: str
) -> WheelIdentity:
    """Validate filename, channel policy, ZIP structure, and METADATA."""
    if channel == "rc":
        if not RC_VERSION_RE.fullmatch(expected_version):
            raise ValueError(
                f"PR publication requires an rcN version, got "
                f"{expected_version!r}"
            )
    elif channel == "release":
        if not STABLE_VERSION_RE.fullmatch(expected_version):
            raise ValueError(
                f"Main publication requires a stable version, got "
                f"{expected_version!r}"
            )
    else:
        raise ValueError(f"Unsupported channel: {channel!r}")

    expected_name = f"hastegeo-{expected_version}-py3-none-any.whl"
    if wheel_path.name != expected_name:
        raise ValueError(
            f"Wheel filename {wheel_path.name!r} does not match "
            f"{expected_name!r}"
        )
    if not wheel_path.is_file() or not zipfile.is_zipfile(wheel_path):
        raise ValueError(f"Not a valid wheel ZIP file: {wheel_path}")

    with zipfile.ZipFile(wheel_path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError(
                "Wheel must contain exactly one dist-info/METADATA file"
            )
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))

    if metadata.get("Name", "").lower() != "hastegeo":
        raise ValueError(
            f"Wheel project is {metadata.get('Name')!r}, not 'hastegeo'"
        )
    if metadata.get("Version") != expected_version:
        raise ValueError(
            f"Wheel METADATA version {metadata.get('Version')!r} does not "
            f"match {expected_version!r}"
        )

    return WheelIdentity(
        path=wheel_path,
        version=expected_version,
        filename=expected_name,
        sha256=sha256_file(wheel_path),
    )


def get_tag_sha(tag: str) -> str:
    """Return the commit SHA for a lightweight release tag, or empty."""
    result = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/git/ref/tags/{tag}",
            "--jq",
            ".object.sha",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if "HTTP 404" in result.stderr:
        return ""
    raise RuntimeError(
        f"Failed to query source tag {tag}: {result.stderr.strip()}"
    )


def ensure_stable_tag(tag: str, source_sha: str) -> None:
    """Create the stable source tag or verify its existing target."""
    existing_sha = get_tag_sha(tag)
    if existing_sha:
        if existing_sha != source_sha:
            raise ValueError(
                f"{tag} points to {existing_sha}, expected {source_sha}"
            )
        return

    run_command(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{REPOSITORY}/git/refs",
            "-f",
            f"ref=refs/tags/{tag}",
            "-f",
            f"sha={source_sha}",
        ]
    )
    print(f"Created source tag {tag} at {source_sha}")


def verify_existing_file(filename: str, checksum: str) -> None:
    """Compare bytes; an existing filename alone is never an idempotent hit."""
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
                filename,
                "--dir",
                directory,
            ]
        )
        if sha256_file(Path(directory) / filename) != checksum:
            raise ValueError(
                "Published asset checksum differs; refusing overwrite"
            )


def verify_existing_json(filename: str, expected: dict) -> None:
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
                filename,
                "--dir",
                directory,
            ]
        )
        if read_json(Path(directory) / filename) != expected:
            raise ValueError(
                "Published provenance differs; refusing overwrite"
            )


def publish_json_asset(path: Path, expected: dict) -> None:
    assets = list_release_assets()
    if path.name in assets:
        verify_existing_json(path.name, expected)
        return
    run_command(
        [
            "gh",
            "release",
            "upload",
            RELEASE_TAG,
            str(path),
            "--repo",
            REPOSITORY,
        ]
    )
    if path.name not in list_release_assets():
        raise RuntimeError("Published provenance asset is missing")


def publish(
    identity: WheelIdentity,
    *,
    channel: str,
    source_sha: str,
    manifest: dict | None = None,
) -> str:
    """Publish ``identity`` without overwriting an existing release asset."""
    assets = list_release_assets()
    source_tag = (
        f"hastegeo-v{identity.version}" if channel == "release" else ""
    )
    if channel == "rc":
        rc_match = RC_VERSION_RE.fullmatch(identity.version)
        if not rc_match:
            raise ValueError(f"Invalid RC version: {identity.version}")
        stable_version = ".".join(rc_match.groups()[:3])
        stable_name = f"hastegeo-{stable_version}-py3-none-any.whl"
        if stable_name in assets:
            raise ValueError(
                f"Cannot publish {identity.version}: stable asset already "
                f"exists for {stable_version}"
            )
        if manifest is not None:
            build = RCBuild.from_dict(manifest["build"])
            if (
                build.source_sha != source_sha
                or build.version != identity.version
            ):
                raise ValueError("RC provenance does not match publication")
            validate_wheel_manifest(manifest, build, identity.sha256)
            if provenance_name(build) in assets:
                verify_existing_json(provenance_name(build), manifest)

    if identity.filename in assets:
        if channel == "release" and get_tag_sha(source_tag) == source_sha:
            print(
                f"{identity.filename} is already published for "
                f"{source_sha}; no-op."
            )
            return (
                f"https://github.com/{REPOSITORY}/releases/download/"
                f"{RELEASE_TAG}/{identity.filename}"
            )
        if channel != "rc" or manifest is None:
            raise ValueError(
                f"Release asset already exists and will not be overwritten: "
                f"{identity.filename}"
            )
        verify_existing_file(identity.filename, identity.sha256)
        print(f"Reusing identical RC asset: {identity.filename}")
    else:
        if source_tag:
            # Tag first so a failed stable upload can be resumed.
            ensure_stable_tag(source_tag, source_sha)
        run_command(
            [
                "gh",
                "release",
                "upload",
                RELEASE_TAG,
                str(identity.path),
                "--repo",
                REPOSITORY,
            ]
        )
        if identity.filename not in list_release_assets():
            raise RuntimeError(
                f"Upload returned success but asset is missing: {identity.filename}"
            )

    if channel == "rc" and manifest is not None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / provenance_name(build)
            write_json(path, manifest)
            publish_json_asset(path, manifest)

    return (
        f"https://github.com/{REPOSITORY}/releases/download/"
        f"{RELEASE_TAG}/{identity.filename}"
    )


def emit_outputs(identity: WheelIdentity, url: str = "") -> None:
    """Emit validation/publication metadata for later workflow jobs."""
    values = {
        "published_version": identity.version,
        "published_url": url,
        "wheel_name": identity.filename,
        "wheel_sha256": identity.sha256,
    }
    for key, value in values.items():
        print(f"{key}={value}")

    output_path = (
        Path(os.environ["GITHUB_OUTPUT"])
        if "GITHUB_OUTPUT" in os.environ
        else None
    )
    if output_path:
        with output_path.open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--channel", choices=["rc", "release"], required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the wheel without querying or mutating GitHub",
    )
    parser.add_argument("--json-output")
    parser.add_argument("--build-identity", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--legacy-rc",
        action="store_true",
        help="use the existing no-overwrite policy for a trusted legacy build",
    )
    args = parser.parse_args(argv)

    if args.legacy_rc and (
        args.channel != "rc" or args.build_identity or args.manifest
    ):
        raise ValueError("Legacy RC mode cannot bypass build provenance")
    if args.manifest and not args.manifest.is_file():
        raise ValueError(
            "RC build manifest is missing; start a fresh build using the "
            "updated workflow instead of guessing legacy provenance"
        )
    identity = validate_wheel(args.wheel, args.expected_version, args.channel)
    manifest = None
    if args.build_identity:
        if args.channel != "rc":
            raise ValueError("RC build identity is not a stable-release input")
        build = RCBuild.from_dict(read_json(args.build_identity))
        if (
            build.source_sha != args.source_sha
            or build.version != identity.version
        ):
            raise ValueError(
                "Build identity does not match the expected wheel"
            )
        manifest = (
            read_json(args.manifest)
            if args.manifest
            else wheel_manifest(build, identity.sha256)
        )
        validate_wheel_manifest(manifest, build, identity.sha256)
    elif args.manifest:
        raise ValueError(
            "A wheel manifest requires the expected build identity"
        )
    if (
        args.channel == "rc"
        and not args.validate_only
        and manifest is None
        and not args.legacy_rc
    ):
        raise ValueError("RC publication requires verified build provenance")
    if args.legacy_rc:
        print(
            "Legacy RC compatibility: retain no-overwrite publication; "
            "this is not a verified deployment-set manifest."
        )
    url = ""
    if not args.validate_only:
        url = publish(
            identity,
            channel=args.channel,
            source_sha=args.source_sha,
            manifest=manifest,
        )
    emit_outputs(identity, url)

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(
                manifest
                if manifest is not None
                else {
                    "version": identity.version,
                    "wheel_name": identity.filename,
                    "sha256": identity.sha256,
                    "url": url,
                    "source_sha": args.source_sha,
                    "channel": args.channel,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
