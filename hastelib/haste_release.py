# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Pure release-version policy shared by hastegeo CI scripts."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

REPOSITORY = "microsoft/haste"
RELEASE_TAG = "haste-binaries"
STABLE_ASSET_RE = re.compile(
    r"^hastegeo-(\d+)\.(\d+)\.(\d+)-py3-none-any\.whl$"
)
RC_ASSET_RE = re.compile(
    r"^hastegeo-(\d+)\.(\d+)\.(\d+)rc(\d+)-py3-none-any\.whl$"
)
STABLE_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
RC_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)rc(\d+)$")
SOURCE_TAG_RE = re.compile(r"^hastegeo-v(\d+\.\d+\.\d+)$")

CommandRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class Resolution:
    """Resolved version and publication state."""

    version: str
    wheel_name: str
    channel: str
    source_sha: str
    source_tag: str
    already_published: bool


def run_command(command: Sequence[str]) -> str:
    """Run a command and return stdout, failing closed on any error."""
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def list_release_assets(
    runner: CommandRunner = run_command,
) -> list[str]:
    """Return all asset names from the haste-binaries release."""
    output = runner(
        [
            "gh",
            "release",
            "view",
            RELEASE_TAG,
            "--repo",
            REPOSITORY,
            "--json",
            "assets",
            "--jq",
            ".assets[].name",
        ]
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def tags_pointing_at(
    source_sha: str,
    runner: CommandRunner = run_command,
) -> list[str]:
    """Return hastegeo release tags that point at ``source_sha``."""
    output = runner(
        [
            "git",
            "tag",
            "--points-at",
            source_sha,
            "--list",
            "hastegeo-v*",
        ]
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def latest_stable(assets: Iterable[str]) -> tuple[int, int, int]:
    """Return the highest stable version, ignoring RC assets."""
    versions = []
    for asset in assets:
        match = STABLE_ASSET_RE.fullmatch(asset)
        if match:
            versions.append(tuple(int(part) for part in match.groups()))
    if not versions:
        raise ValueError(
            "No stable hastegeo wheel exists; use --set-version for the "
            "initial release."
        )
    return max(versions)


def bump_version(
    version: tuple[int, int, int], bump: str
) -> tuple[int, int, int]:
    """Apply a semantic version bump."""
    major, minor, patch = version
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    if bump == "patch":
        return major, minor, patch + 1
    raise ValueError(f"Unsupported bump: {bump!r}")


def parse_set_version(
    value: str, channel: str
) -> tuple[tuple[int, int, int], int | None]:
    """Parse an exact stable target or an exact RC override."""
    stable = STABLE_VERSION_RE.fullmatch(value)
    if stable:
        return tuple(int(part) for part in stable.groups()), None

    rc = RC_VERSION_RE.fullmatch(value)
    if rc and channel == "rc":
        return tuple(int(part) for part in rc.groups()[:3]), int(rc.group(4))

    raise ValueError(
        f"Invalid --set-version {value!r} for channel {channel!r}; use "
        "X.Y.Z or, for RC builds, X.Y.ZrcN."
    )


def next_rc(assets: Iterable[str], target: tuple[int, int, int]) -> int:
    """Return one more than the highest RC number for ``target``."""
    numbers = []
    for asset in assets:
        match = RC_ASSET_RE.fullmatch(asset)
        if not match:
            continue
        asset_target = tuple(int(part) for part in match.groups()[:3])
        if asset_target == target:
            numbers.append(int(match.group(4)))
    return max(numbers, default=0) + 1


def stable_tag_version(tags: Iterable[str]) -> str:
    """Return the one stable version tagged at a source SHA, if present."""
    versions = []
    for tag in tags:
        match = SOURCE_TAG_RE.fullmatch(tag)
        if match:
            versions.append(match.group(1))
    if len(versions) > 1:
        raise ValueError(
            "Multiple hastegeo stable tags point at the same source SHA: "
            + ", ".join(sorted(versions))
        )
    return versions[0] if versions else ""


def resolve(
    *,
    channel: str,
    source_sha: str,
    assets: Sequence[str],
    tags: Sequence[str],
    bump: str = "patch",
    set_version: str = "",
) -> Resolution:
    """Resolve a deterministic version from release assets and source tags."""
    if channel not in {"rc", "release"}:
        raise ValueError(f"Unsupported channel: {channel!r}")
    if not source_sha:
        raise ValueError("source_sha is required")

    if channel == "release":
        tagged_version = stable_tag_version(tags)
        if tagged_version:
            wheel_name = f"hastegeo-{tagged_version}-py3-none-any.whl"
            return Resolution(
                version=tagged_version,
                wheel_name=wheel_name,
                channel=channel,
                source_sha=source_sha,
                source_tag=f"hastegeo-v{tagged_version}",
                already_published=wheel_name in assets,
            )

    if set_version:
        target, explicit_rc = parse_set_version(set_version, channel)
    else:
        target = bump_version(latest_stable(assets), bump)
        explicit_rc = None

    target_text = ".".join(str(part) for part in target)
    if channel == "rc":
        rc_number = explicit_rc or next_rc(assets, target)
        version = f"{target_text}rc{rc_number}"
        source_tag = ""
    else:
        version = target_text
        source_tag = f"hastegeo-v{version}"

    wheel_name = f"hastegeo-{version}-py3-none-any.whl"
    if wheel_name in assets:
        raise ValueError(
            "Release asset already exists without an idempotent source tag: "
            f"{wheel_name}"
        )

    return Resolution(
        version=version,
        wheel_name=wheel_name,
        channel=channel,
        source_sha=source_sha,
        source_tag=source_tag,
        already_published=False,
    )
