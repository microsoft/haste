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
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

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
    if not wheel_path.is_file():
        raise ValueError(
            f"Expected wheel not found: {wheel_path}. The downloaded "
            "artifact does not contain a file matching the re-resolved "
            f"version {expected_version!r}. This is unexpected: either "
            "the build artifact was not uploaded correctly, or the "
            "version re-resolved here no longer matches what the build "
            "produced (e.g. a wheel was published for this target "
            "version by another run after this one was built); re-run "
            "the build workflow to obtain a wheel matching the "
            "currently available version."
        )
    if not zipfile.is_zipfile(wheel_path):
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


def publish(
    identity: WheelIdentity,
    *,
    channel: str,
    source_sha: str,
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
        raise ValueError(
            f"Release asset already exists and will not be overwritten: "
            f"{identity.filename}"
        )

    if source_tag:
        # Create the tag before upload. If upload fails, a rerun resolves the
        # same version from the tag and completes the missing asset.
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
            f"Upload returned success but asset is missing: "
            f"{identity.filename}"
        )

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
    args = parser.parse_args(argv)

    identity = validate_wheel(args.wheel, args.expected_version, args.channel)
    url = ""
    if not args.validate_only:
        url = publish(
            identity,
            channel=args.channel,
            source_sha=args.source_sha,
        )
    emit_outputs(identity, url)

    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(
                {
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
