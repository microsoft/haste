#!/usr/bin/env python3
"""Fail when the resolved protobuf would break the Functions worker.

The Azure Functions Python worker ships its own protobuf (5.29.x at the
time of writing) under
`/azure-functions-host/workers/python/<ver>/LINUX/X64/google/protobuf`.
Its generated `pb2` modules cannot load under protobuf 7, and when the
copy in site-packages wins the worker reports:

    Reading functions metadata (Worker)
    0 functions found (Worker)
    ...
    No HTTP routes mapped

Every HTTP route 404s and every queue trigger stops firing, with no error
in any log -- the app simply has no functions. That is what
`tensorboard==2.21.0` did: it requires `protobuf >= 6.31.1`, so pip
resolved protobuf 7 quite happily and the failure only appeared at
runtime.

A clean `pip install` is therefore not enough on its own. This reads the
resolution report pip writes with `--report` and rejects the install set
before it can be built into an image.

Usage:  python .github/scripts/check_protobuf_pin.py <pip-report.json>
Exit 0 when compatible, 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# The first protobuf major the bundled worker cannot load.
FIRST_INCOMPATIBLE_MAJOR = 6

PACKAGE = "protobuf"


def resolved_version(report: dict, package: str = PACKAGE) -> Optional[str]:
    """Return the version of ``package`` pip would install, if any."""
    for item in report.get("install", []):
        metadata = item.get("metadata", {})
        if metadata.get("name", "").lower() == package.lower():
            version = metadata.get("version")
            return str(version) if version else None
    return None


def major_of(version: str) -> int:
    """Return the leading major number of a version string."""
    head = version.split(".", 1)[0].strip()
    if not head.isdigit():
        raise ValueError(f"Cannot read a major version from {version!r}")
    return int(head)


def is_compatible(version: Optional[str]) -> bool:
    """True when this protobuf can coexist with the bundled worker."""
    if version is None:
        # protobuf is not being installed, so nothing can shadow the
        # worker's own copy.
        return True
    return major_of(version) < FIRST_INCOMPATIBLE_MAJOR


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: check_protobuf_pin.py <pip-report.json>",
            file=sys.stderr,
        )
        return 2

    report_path = Path(args[0])
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"No pip report at {report_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as error:
        print(f"Malformed pip report: {error}", file=sys.stderr)
        return 2

    version = resolved_version(report)
    if version is None:
        print("protobuf is not in the resolved set.")
        return 0

    if not is_compatible(version):
        print(
            f"protobuf {version} would be installed, but the Azure "
            "Functions Python worker bundles 5.x and fails to index any "
            "functions above it -- silently, with no error.\n"
            "Pin protobuf<6, and keep tensorboard below 2.21 (it requires "
            "protobuf>=6.31.1).",
            file=sys.stderr,
        )
        return 1

    print(f"protobuf {version} is compatible with the Functions worker.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
