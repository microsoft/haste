#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Prune old hastegeo release-candidate wheels from the haste-binaries release.

For each target version, once its stable wheel is published every rc for that
version is obsolete and removed; otherwise the most recent ``--keep`` rc wheels
are retained. Asset names listed in ``--retain-file`` are never deleted.
Dry-run by default; pass ``--apply`` to actually delete.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Sequence

REPO = "microsoft/haste"
RELEASE_TAG = "haste-binaries"
STABLE_RE = re.compile(r"^hastegeo-(\d+)\.(\d+)\.(\d+)-py3-none-any\.whl$")
RC_RE = re.compile(r"^hastegeo-(\d+)\.(\d+)\.(\d+)rc(\d+)-py3-none-any\.whl$")


def _gh(args: Sequence[str]) -> str:
    """Run a gh command scoped to the HASTE repo and return stdout."""
    return subprocess.run(
        ["gh", *args, "--repo", REPO],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def list_assets() -> list[dict[str, object]]:
    """Return [{name, apiUrl}, ...] for the release's assets."""
    out = _gh(
        [
            "release",
            "view",
            RELEASE_TAG,
            "--json",
            "assets",
            "--jq",
            ".assets[] | {name: .name, apiUrl: .apiUrl}",
        ]
    )
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def plan_deletions(
    assets: Sequence[dict[str, object]],
    keep: int,
    retain: set[str],
) -> list[dict[str, object]]:
    """Return the list of rc assets that should be deleted."""
    if keep < 0:
        raise ValueError("keep must be non-negative")

    stable = set()
    rcs: dict[tuple[int, int, int], list[tuple[int, dict[str, object]]]] = {}
    for asset in assets:
        name = str(asset["name"])
        stable_match = STABLE_RE.match(name)
        if stable_match:
            stable.add(tuple(int(x) for x in stable_match.groups()))
            continue
        rc_match = RC_RE.match(name)
        if rc_match:
            target = tuple(int(x) for x in rc_match.groups()[:3])
            rcs.setdefault(target, []).append((int(rc_match.group(4)), asset))

    to_delete = []
    for target, items in rcs.items():
        items.sort(key=lambda pair: pair[0])
        if target in stable:
            doomed = items  # superseded by the stable release
        else:
            doomed = items[:-keep] if keep > 0 else items
        for _, asset in doomed:
            if str(asset["name"]) not in retain:
                to_delete.append(asset)
    return to_delete


def _delete_asset(api_url: str) -> None:
    subprocess.run(
        ["gh", "api", "-X", "DELETE", api_url],
        capture_output=True,
        text=True,
        check=True,
    )


def _load_retain(path: str | None) -> set[str]:
    if not path:
        return set()
    retain_path = Path(path)
    if not retain_path.is_file():
        raise FileNotFoundError(
            f"Configured retain file does not exist: {retain_path}"
        )
    with retain_path.open(encoding="utf-8") as handle:
        return {
            line.strip()
            for line in handle
            if line.strip() and not line.startswith("#")
        }


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        type=_non_negative_int,
        default=5,
        help="rc wheels to keep per unreleased version (default: 5)",
    )
    parser.add_argument(
        "--retain-file", help="file of asset names to never delete"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete for real (default: dry-run)",
    )
    args = parser.parse_args(argv)

    retain = _load_retain(args.retain_file)
    to_delete = plan_deletions(list_assets(), args.keep, retain)

    if not to_delete:
        print("No rc wheels to prune.")
        return 0

    for asset in to_delete:
        if args.apply:
            _delete_asset(str(asset["apiUrl"]))
            print(f"deleted {asset['name']}")
        else:
            print(f"[dry-run] would delete {asset['name']}")
    verb = "Deleted" if args.apply else "Would delete"
    print(f"{verb} {len(to_delete)} rc wheel(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
