#!/usr/bin/env python3
"""Fail when a Dockerfile's Python no longer matches the version CI tests.

The dependency-validation workflow resolves each image's requirements on
a Python version listed in its matrix. That proof is only worth anything
while the matrix agrees with the image's base: resolving against 3.11
says nothing about an image that has moved to 3.12, and the check would
keep passing while proving the wrong thing.

`rasterio==1.5.1` is the reason this matters -- it requires Python 3.12,
so an image's Python version is the difference between a working install
and `No matching distribution found`.

Usage:  python .github/scripts/check_image_python.py <Dockerfile> <3.11>
Exit 0 when they match, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Matches the python version in a base image reference, e.g.
# `FROM mcr.microsoft.com/azure-functions/python:4-python3.11-slim`.
_FROM_PYTHON = re.compile(r"^FROM\s+.*?python(\d+\.\d+)", re.IGNORECASE)


def base_python_version(dockerfile_text: str) -> Optional[str]:
    """Return the Python version of the first FROM line, if it has one."""
    for line in dockerfile_text.splitlines():
        if not line.lstrip().upper().startswith("FROM "):
            continue
        match = _FROM_PYTHON.match(line.strip())
        if match:
            return match.group(1)
        # A FROM without a python tag (e.g. a build stage) is not the
        # runtime base we care about; keep looking.
    return None


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(
            "usage: check_image_python.py <Dockerfile> <expected-version>",
            file=sys.stderr,
        )
        return 2

    dockerfile = Path(args[0])
    expected = args[1].strip()

    try:
        text = dockerfile.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"No Dockerfile at {dockerfile}", file=sys.stderr)
        return 2

    found = base_python_version(text)
    if found is None:
        print(
            f"{dockerfile}: could not read a Python version from any FROM "
            "line.",
            file=sys.stderr,
        )
        return 1

    if found != expected:
        print(
            f"{dockerfile} is built on Python {found}, but this job "
            f"resolves dependencies against {expected}. Update the matrix "
            "in .github/workflows/dependency-validation.yml so the check "
            "keeps proving something.",
            file=sys.stderr,
        )
        return 1

    print(f"{dockerfile} is Python {found}, matching this job.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
