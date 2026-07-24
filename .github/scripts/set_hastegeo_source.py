#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Toggle the hastegeo install source in requirements.txt files.

The committed default for the function-app requirements is the editable local
tree (``-e ../../hastelib``) so ``docker compose`` builds from source with no
wheel publish. Deployment CI calls this to flip that line to the published
wheel (``hastegeo @ <url>``) before ``func azure functionapp publish``. The
inactive alternative is preserved as a comment, so the switch is reversible
and idempotent.

Usage:
    set_hastegeo_source.py --mode wheel --url <URL> FILE [FILE ...]
    set_hastegeo_source.py --mode editable [--path ../../hastelib] FILE ...
"""

import argparse
import re
from pathlib import Path
from typing import Sequence

EDITABLE_RE = re.compile(r"^\s*#?\s*-e\s+(?P<path>\S*hastelib\S*)\s*$")
WHEEL_RE = re.compile(r"^\s*#?\s*hastegeo\s*@\s*(?P<url>\S+)\s*$")


def rewrite(
    path: str,
    mode: str,
    url: str | None,
    editable_path: str,
) -> None:
    """Rewrite ``path`` with exactly one active hastegeo source line."""
    requirement_path = Path(path)
    lines = requirement_path.read_text(encoding="utf-8").splitlines()

    existing_url = None
    for line in lines:
        wheel_match = WHEEL_RE.match(line)
        if wheel_match:
            existing_url = existing_url or wheel_match.group("url")

    wheel_url = url or existing_url
    if mode == "wheel" and not wheel_url:
        raise SystemExit(f"{path}: --url required (no existing wheel line)")

    editable_line = f"-e {editable_path}"
    wheel_line = f"hastegeo @ {wheel_url}" if wheel_url else None

    first_source_index = next(
        (
            index
            for index, line in enumerate(lines)
            if EDITABLE_RE.match(line) or WHEEL_RE.match(line)
        ),
        len(lines),
    )
    out = [
        line
        for line in lines
        if not EDITABLE_RE.match(line) and not WHEEL_RE.match(line)
    ]
    source_block = []
    if mode == "editable":
        source_block.append(editable_line)
        if wheel_line:
            source_block.append(f"# {wheel_line}")
        active = editable_line
    else:
        source_block.extend([f"# {editable_line}", wheel_line])
        active = wheel_line

    out[first_source_index:first_source_index] = source_block
    requirement_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{path}: hastegeo source -> {active}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Toggle the hastegeo install source in requirements files."
    )
    parser.add_argument("--mode", required=True, choices=["wheel", "editable"])
    parser.add_argument("--url", help="wheel URL (for --mode wheel)")
    parser.add_argument(
        "--path",
        default="../../hastelib",
        help="editable path for --mode editable (default: ../../hastelib)",
    )
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    for path in args.files:
        rewrite(path, args.mode, args.url, args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
