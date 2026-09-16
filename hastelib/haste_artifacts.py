# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Build-only RC identity and artifact-set contracts."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from haste_release import (
    RELEASE_TAG,
    REPOSITORY,
    STABLE_ASSET_RE,
    STABLE_VERSION_RE,
    bump_version,
    latest_stable,
    run_command,
)

SHA_RE = re.compile(r"[0-9a-f]{40}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_NAMES = {"training": "hastetraining", "imageryprep": "hasteimageryprep"}
IDENTITY_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "source_sha",
        "build_run_id",
        "build_created_at",
        "source_date_epoch",
        "release_baseline",
        "version",
        "wheel_name",
        "channel",
    }
)


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Artifact timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Artifact timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def read_json(path: Path) -> dict:
    if path.stat().st_size > 65536:
        raise ValueError("Artifact manifest exceeds its size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Artifact manifest must be an object")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


@dataclass(frozen=True)
class RCBuild:
    source_sha: str
    run_id: str
    created_at: str
    source_date_epoch: int
    release_baseline: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_sha, str) or not SHA_RE.fullmatch(
            self.source_sha
        ):
            raise ValueError("RC source must be an exact commit SHA")
        if not isinstance(self.run_id, str) or not re.fullmatch(
            r"[1-9][0-9]{0,19}", self.run_id
        ):
            raise ValueError("RC build run ID must be a positive integer")
        if (
            type(self.source_date_epoch) is not int
            or self.source_date_epoch < 0
        ):
            raise ValueError("Source timestamp must be a non-negative integer")
        timestamp(self.created_at)
        if not isinstance(
            self.release_baseline, str
        ) or not STABLE_VERSION_RE.fullmatch(self.release_baseline):
            raise ValueError("RC release baseline must be a stable version")

    @property
    def version(self) -> str:
        baseline = tuple(
            int(part) for part in self.release_baseline.split(".")
        )
        target = ".".join(
            str(part) for part in bump_version(baseline, "patch")
        )
        return f"{target}rc{self.run_id}"

    @property
    def wheel_name(self) -> str:
        return f"hastegeo-{self.version}-py3-none-any.whl"

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "repository": REPOSITORY,
            "source_sha": self.source_sha,
            "build_run_id": self.run_id,
            "build_created_at": timestamp(self.created_at).isoformat(),
            "source_date_epoch": self.source_date_epoch,
            "release_baseline": self.release_baseline,
            "version": self.version,
            "wheel_name": self.wheel_name,
            "channel": "rc",
        }

    @classmethod
    def from_dict(cls, value: dict) -> RCBuild:
        if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
            raise ValueError("Invalid RC build identity fields")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or value["repository"] != REPOSITORY
            or value["channel"] != "rc"
        ):
            raise ValueError("Invalid RC build identity")
        build = cls(
            source_sha=value["source_sha"],
            run_id=value["build_run_id"],
            created_at=value["build_created_at"],
            source_date_epoch=value["source_date_epoch"],
            release_baseline=value["release_baseline"],
        )
        if value != build.to_dict():
            raise ValueError("RC build identity is not canonical")
        return build


def resolve_ci_build(
    source_sha: str,
    run_id: str,
    runner: Callable[[Sequence[str]], str] = run_command,
) -> RCBuild:
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise ValueError("RC source must be an exact commit SHA")
    if not isinstance(run_id, str) or not re.fullmatch(
        r"[1-9][0-9]{0,19}", run_id
    ):
        raise ValueError("Invalid build run ID")
    run = json.loads(
        runner(
            [
                "gh",
                "api",
                f"repos/{REPOSITORY}/actions/runs/{run_id}",
            ]
        )
    )
    if (
        str(run["id"]) != run_id
        or run["head_sha"] != source_sha
        or run["repository"]["full_name"] != REPOSITORY
        or run["path"].split("@", 1)[0]
        != ".github/workflows/hastegeo-build.yml"
        or run["event"] not in {"pull_request", "workflow_dispatch"}
    ):
        raise ValueError(
            "Build identity does not match the requested source run"
        )
    cutoff = timestamp(run["created_at"])
    assets = json.loads(
        runner(
            [
                "gh",
                "release",
                "view",
                RELEASE_TAG,
                "--repo",
                REPOSITORY,
                "--json",
                "assets",
            ]
        )
    )["assets"]
    baseline_assets = [
        asset["name"]
        for asset in assets
        if STABLE_ASSET_RE.fullmatch(asset["name"])
        and timestamp(asset["createdAt"]) < cutoff
    ]
    baseline = ".".join(str(part) for part in latest_stable(baseline_assets))
    source_epoch = int(
        runner(
            [
                "git",
                "show",
                "-s",
                "--format=%ct",
                source_sha,
            ]
        ).strip()
    )
    return RCBuild(
        source_sha, run_id, cutoff.isoformat(), source_epoch, baseline
    )


def wheel_manifest(build: RCBuild, sha256: str) -> dict:
    if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
        raise ValueError("Invalid wheel checksum")
    return {"build": build.to_dict(), "wheel_sha256": sha256}


def validate_wheel_manifest(
    value: dict, expected: RCBuild, actual_sha256: str | None = None
) -> str:
    if not isinstance(value, dict) or set(value) != {"build", "wheel_sha256"}:
        raise ValueError("Invalid wheel manifest fields")
    if RCBuild.from_dict(value["build"]) != expected:
        raise ValueError("Wheel provenance does not match the source build")
    checksum = value["wheel_sha256"]
    if not isinstance(checksum, str) or not HASH_RE.fullmatch(checksum):
        raise ValueError("Invalid wheel checksum")
    if actual_sha256 is not None and checksum != actual_sha256:
        raise ValueError("Wheel checksum does not match the build manifest")
    return checksum


def image_record(
    build: RCBuild, family: str, digest: str, registry_sha256: str
) -> dict:
    if (
        not isinstance(family, str)
        or family not in IMAGE_NAMES
        or not isinstance(digest, str)
        or not DIGEST_RE.fullmatch(digest)
        or not isinstance(registry_sha256, str)
        or not HASH_RE.fullmatch(registry_sha256)
    ):
        raise ValueError("Invalid image identity")
    return {
        "family": family,
        "reference": IMAGE_NAMES[family] + ":" + build.version,
        "registry_sha256": registry_sha256,
        "digest": digest,
        "source_sha": build.source_sha,
        "version": build.version,
        "build_run_id": build.run_id,
    }


def artifact_set(
    manifest: dict, images: Sequence[dict], expected: RCBuild
) -> dict:
    validate_wheel_manifest(manifest, expected)
    validated = {}
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Image provenance must be an object")
        family = image.get("family")
        if family in validated:
            raise ValueError("Duplicate image family in artifact set")
        actual = image_record(
            expected, family, image["digest"], image["registry_sha256"]
        )
        if actual != image:
            raise ValueError(
                "Image provenance does not match the source build"
            )
        validated[family] = actual
    if set(validated) != set(IMAGE_NAMES):
        raise ValueError("RC artifact set requires both worker images")
    if len({image["registry_sha256"] for image in validated.values()}) != 1:
        raise ValueError("Worker images must use the same configured registry")
    return {"schema_version": 1, "wheel": manifest, "images": validated}


def validate_artifact_set(
    value: dict, version: str, source_sha: str
) -> RCBuild:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "wheel", "images"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
    ):
        raise ValueError("Invalid deployment artifact-set manifest")
    build = RCBuild.from_dict(value["wheel"]["build"])
    if build.version != version or build.source_sha != source_sha:
        raise ValueError(
            "RC artifacts do not match the deployment source/version"
        )
    if not isinstance(value["images"], Mapping):
        raise ValueError("Invalid artifact image mapping")
    if (
        artifact_set(value["wheel"], list(value["images"].values()), build)
        != value
    ):
        raise ValueError("Invalid deployment artifact-set contents")
    return build


def provenance_name(build: RCBuild) -> str:
    return build.wheel_name + ".provenance.json"


def artifact_set_name(version: str) -> str:
    return f"hastegeo-{version}-artifacts.json"


def registry_fingerprint(login_server: str) -> str:
    if not isinstance(login_server, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9.-]*", login_server
    ):
        raise ValueError("Invalid registry login server")
    return hashlib.sha256(login_server.encode()).hexdigest()
