#!/usr/bin/env python3
"""Filter runtime-owned GDAL wheels from public-index dependency checks.

The exact HASTE wheels are validated and installed from the build artifact by
the GDAL runtime workflow. This keeps the general dependency resolver from
trying to build GDAL from an sdist before those private build artifacts exist.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

RUNTIME_DISTRIBUTIONS = {
    "gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
    "hastegeo",
    "haste-gdal-runtime",
}


def _name(line: str) -> str | None:
    content = line.strip()
    if not content or content.startswith("#"):
        return None
    if content.startswith("-e "):
        return "hastegeo"
    match = re.match(r"([A-Za-z0-9_.-]+)(?=\s|[<=>!~;\[]|$)", content)
    if not match:
        return None
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def filter_requirements(source: Path, output: Path) -> None:
    retained = [
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if _name(line) not in RUNTIME_DISTRIBUTIONS
    ]
    output.write_text("\n".join(retained) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    filter_requirements(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
