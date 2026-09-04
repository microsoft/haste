#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Extract one version's release notes from CHANGELOG.md.

The changelog is the single source of truth for release notes. This script
lifts one ``## [<version>]`` section out of it and rewrites repo-relative
markdown links into permalinks, so the published notes keep working even
after the referenced files move.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "microsoft/haste"

# "## [v2.0.0] — Building labeling workflow" -> version, optional title.
HEADING_RE = re.compile(
    r"^##\s+\[(?P<version>[^\]]+)\]\s*(?:[—-]\s*(?P<title>.*?))?\s*$"
)
# Markdown links whose target is neither absolute, an anchor, nor a mailto.
RELATIVE_LINK_RE = re.compile(r"(?<=\]\()(?!https?://|#|mailto:)([^)]+)(?=\))")


@dataclass(frozen=True)
class ReleaseNotes:
    """One extracted changelog section."""

    version: str
    title: str
    body: str

    @property
    def display_title(self) -> str:
        """Return the release title, falling back to the bare version."""
        return f"{self.version} — {self.title}" if self.title else self.version


def absolutize_links(body: str, ref: str) -> str:
    """Rewrite repo-relative markdown links to permalinks at ``ref``."""

    def replace(match: re.Match[str]) -> str:
        target = match.group(1)
        path, _, anchor = target.partition("#")
        path = path.lstrip("./")
        if not path:
            return target
        kind = "tree" if path.endswith("/") else "blob"
        url = f"https://github.com/{REPOSITORY}/{kind}/{ref}/{path.rstrip('/')}"
        return f"{url}#{anchor}" if anchor else url

    return RELATIVE_LINK_RE.sub(replace, body)


def extract(changelog: str, version: str) -> ReleaseNotes:
    """Return the section for ``version``, or raise if it is absent."""
    wanted = version.lstrip("v").lower()
    lines = changelog.splitlines()

    start = None
    heading: re.Match[str] | None = None
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if not match:
            continue
        if start is not None:
            end = index
            break
        if match.group("version").lstrip("v").lower() == wanted:
            start, heading = index, match
    else:
        end = len(lines)

    if start is None or heading is None:
        available = [
            m.group("version")
            for m in (HEADING_RE.match(line) for line in lines)
            if m
        ]
        raise ValueError(
            f"No CHANGELOG section for {version!r}. Available: "
            + ", ".join(available)
        )

    body = "\n".join(lines[start + 1 : end]).strip()
    # Drop the horizontal rule that separates sections in the changelog.
    body = re.sub(r"\n*-{3,}\s*$", "", body).strip()
    if not body:
        raise ValueError(f"CHANGELOG section for {version!r} is empty")

    return ReleaseNotes(
        version=heading.group("version"),
        title=(heading.group("title") or "").strip(),
        body=body,
    )


def main(argv: Sequence[str] | None = None) -> int:
    # The changelog uses em dashes; do not let a legacy console encoding
    # mangle them when the notes are piped somewhere.
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--changelog",
        type=Path,
        default=REPO_ROOT / "CHANGELOG.md",
    )
    parser.add_argument(
        "--ref",
        default="",
        help="git ref used to build link permalinks (default: --version)",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--print-title",
        action="store_true",
        help="write the release title to stdout instead of the body",
    )
    args = parser.parse_args(argv)

    notes = extract(
        args.changelog.read_text(encoding="utf-8"), args.version
    )
    body = absolutize_links(notes.body, args.ref or args.version)

    if args.print_title:
        print(notes.display_title)
        return 0

    if args.output:
        args.output.write_text(body + "\n", encoding="utf-8")
    else:
        sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
