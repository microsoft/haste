# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Negotiate wheel artifacts with the active default-branch publisher."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from typing import Callable, Literal, Sequence

from haste_release import REPOSITORY, run_command

Protocol = Literal["legacy", "run-bound-v1"]
PROTOCOLS: tuple[Protocol, ...] = ("legacy", "run-bound-v1")
CAPABILITIES_PATH = ".github/hastegeo-artifacts.json"


def artifact_name(run_id: str, attempt: str, protocol: Protocol) -> str:
    for value in (run_id, attempt):
        if not isinstance(value, str) or not re.fullmatch(
            r"[1-9][0-9]{0,19}", value
        ):
            raise ValueError("Build run and attempt must be positive integers")
    if protocol == "legacy":
        return f"hastegeo-wheel-{run_id}"
    if protocol == "run-bound-v1":
        return f"hastegeo-wheel-{run_id}-{attempt}"
    raise ValueError(f"Unsupported artifact protocol: {protocol!r}")


def active_protocols(
    runner: Callable[[Sequence[str]], str] = run_command,
) -> list[Protocol]:
    default_branch = runner(
        ["gh", "api", f"repos/{REPOSITORY}", "--jq", ".default_branch"]
    ).strip()
    if not default_branch or default_branch == "null":
        raise ValueError("Cannot determine the trusted default branch")
    try:
        content = runner(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/{REPOSITORY}/contents/{CAPABILITIES_PATH}",
                "-f",
                f"ref={default_branch}",
                "--jq",
                ".content",
            ]
        )
    except subprocess.CalledProcessError as error:
        if "HTTP 404" not in (error.stderr or ""):
            raise
        print(
            "Active publisher uses the legacy artifact contract; "
            "keeping artifact names and RC versions compatible.",
            file=sys.stderr,
        )
        return ["legacy"]
    if len(content) > 4096:
        raise ValueError("Publisher capabilities exceed their size limit")
    capabilities = json.loads(
        base64.b64decode("".join(content.splitlines()), validate=True)
    )
    if (
        not isinstance(capabilities, dict)
        or type(capabilities.get("schema_version")) is not int
        or capabilities != {"schema_version": 1, "protocols": list(PROTOCOLS)}
    ):
        raise ValueError("Unsupported publisher capabilities")
    return ["legacy", "run-bound-v1"]


def run_artifacts(
    run_id: str,
    attempt: str,
    runner: Callable[[Sequence[str]], str],
) -> list[dict]:
    artifact_name(run_id, attempt, "legacy")
    pages = json.loads(
        runner(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts",
            ]
        )
    )
    return [artifact for page in pages for artifact in page["artifacts"]]


def producer_protocol(
    run_id: str,
    attempt: str,
    runner: Callable[[Sequence[str]], str] = run_command,
) -> Protocol:
    artifact_name(run_id, attempt, "legacy")
    supported = active_protocols(runner)
    if attempt != "1":
        artifacts = run_artifacts(run_id, attempt, runner)
        previous = set()
        for artifact in artifacts:
            name = artifact["name"]
            if name == artifact_name(run_id, attempt, "legacy"):
                previous.add("legacy")
            elif re.fullmatch(rf"hastegeo-wheel-{run_id}-[1-9][0-9]*", name):
                previous.add("run-bound-v1")
        if len(previous) > 1:
            raise ValueError("Build run contains mixed artifact protocols")
        if previous:
            for protocol in supported:
                if protocol in previous:
                    return protocol
            raise ValueError(
                "Active publisher no longer supports this build's protocol; "
                "start a fresh build instead of downgrading it"
            )
    return supported[-1]


def published_protocol(
    run_id: str,
    attempt: str,
    runner: Callable[[Sequence[str]], str] = run_command,
) -> Protocol:
    names = [
        artifact["name"]
        for artifact in run_artifacts(run_id, attempt, runner)
        if artifact["expired"] is False
    ]
    matches = [
        protocol
        for protocol in PROTOCOLS
        for name in names
        if name == artifact_name(run_id, attempt, protocol)
    ]
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one wheel artifact for the source run/attempt"
        )
    return matches[0]
