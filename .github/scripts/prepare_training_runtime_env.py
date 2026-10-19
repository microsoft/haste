#!/usr/bin/env python3
"""Point the training Conda environment at the current build's GDAL wheels."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

RUNTIME_DISTRIBUTIONS = {
    "haste-gdal-runtime",
    "gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
}
WHEEL_URL = re.compile(r"https://[^\s\"']+\.whl", re.IGNORECASE)


def wheel_distribution(filename: str) -> str | None:
    normalized = filename.casefold()
    matches = [
        name
        for name in RUNTIME_DISTRIBUTIONS
        if normalized.startswith(name.replace("-", "_") + "-")
    ]
    return matches[0] if len(matches) == 1 else None


def prepare_environment(
    source: Path, wheel_dir: Path, output: Path
) -> list[Path]:
    text = source.read_text(encoding="utf-8")
    replacements: dict[str, Path] = {}
    for match in WHEEL_URL.findall(text):
        filename = unquote(Path(urlsplit(match).path).name)
        target = wheel_dir / filename
        if not target.is_file():
            raise FileNotFoundError(
                f"runtime wheel referenced by env.yml is missing: {filename}"
            )
        normalized = wheel_distribution(filename)
        if normalized is None:
            raise ValueError(
                f"unexpected wheel distribution in env.yml: {filename}"
            )
        if normalized in replacements:
            raise ValueError(
                f"duplicate runtime wheel in env.yml: {normalized}"
            )
        replacements[normalized] = target
        text = text.replace(match, target.resolve().as_uri())

    if set(replacements) != RUNTIME_DISTRIBUTIONS:
        raise ValueError(
            "training environment must reference all six runtime wheels; "
            f"missing={sorted(RUNTIME_DISTRIBUTIONS - set(replacements))}"
        )
    output.write_text(text, encoding="utf-8")
    return list(replacements.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("wheel_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    wheels = prepare_environment(args.source, args.wheel_dir, args.output)
    print(f"Prepared {args.output} with {len(wheels)} locked runtime wheels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
