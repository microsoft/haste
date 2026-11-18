#!/usr/bin/env python3
"""Verify that staged consumer pins refer to an existing runtime release."""

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_FILES = (
    "api/hastefuncapi/requirements.txt",
    "api/hastefuncqueues/requirements.txt",
    "api/titilerfuncapi/requirements.txt",
    "docker/imageryprep/requirements.txt",
    "docker/training/env/env.yml",
)
WHEELS = {
    "haste-gdal-runtime",
    "gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
}


def build_number(text: str) -> int:
    value = text.strip()
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Invalid published runtime build number")
    return int(value)


def locked_candidate(text: str) -> int:
    matches = re.findall(r"(?m)^HASTE_GDAL_BUILD\s+([0-9]+)\s*$", text)
    if len(matches) != 1:
        raise ValueError("Expected exactly one candidate build number")
    return build_number(matches[0])


def locked_assets(text: str, published: int) -> dict[str, str]:
    result = {}
    for raw in text.splitlines():
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 2:
            raise ValueError("Invalid published runtime asset lock")
        digest, filename = fields
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or "/" in filename
            or "\\" in filename
            or filename in result
            or not re.search(rf"\+haste\.{published}-", filename)
        ):
            raise ValueError("Invalid published runtime asset lock")
        result[filename] = f"sha256:{digest}"
    if len(result) != len(WHEELS):
        raise ValueError("Expected exactly six published runtime wheel hashes")
    return result


def validate_pins(
    requirements: dict[str, str],
    published: int,
    candidate: int,
    base_published: int,
    expected_assets: dict[str, str],
    assets: list[dict],
) -> None:
    if published < base_published or candidate < published:
        raise ValueError("Runtime build cannot precede the published baseline")
    available = {
        asset["name"]: asset.get("digest")
        for asset in assets
        if asset.get("state") == "uploaded"
        and re.fullmatch(r"sha256:[0-9a-f]{64}", asset.get("digest") or "")
    }
    for path, content in requirements.items():
        found = set()
        for line in content.splitlines():
            match = re.match(r"^\s*-?\s*([A-Za-z0-9_.-]+)\s*@\s*(\S+)", line)
            if not match:
                continue
            name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
            if name not in WHEELS:
                continue
            parsed = urlsplit(match.group(2))
            prefix = "/microsoft/haste/releases/download/haste-binaries/"
            if (
                parsed.scheme != "https"
                or parsed.netloc != "github.com"
                or not parsed.path.startswith(prefix)
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(f"{path}: invalid runtime asset URL")
            filename = unquote(parsed.path[len(prefix) :])
            if "/" in filename or "\\" in filename:
                raise ValueError(f"{path}: invalid runtime asset filename")
            if not filename.lower().startswith(name.replace("-", "_") + "-"):
                raise ValueError(f"{path}: runtime wheel name does not match")
            if not re.search(
                rf"\+haste\.{published}-", filename, re.IGNORECASE
            ):
                raise ValueError(f"{path}: inconsistent runtime build")
            if (
                filename not in expected_assets
                or available.get(filename) != expected_assets[filename]
            ):
                raise ValueError(
                    f"{path}: missing or changed runtime asset {filename}"
                )
            if name in found:
                raise ValueError(f"{path}: duplicate runtime distribution")
            found.add(name)
        expected = (
            {"haste-gdal-runtime", "rasterio"}
            if path == "api/titilerfuncapi/requirements.txt"
            else WHEELS
        )
        if found != expected:
            raise ValueError(f"{path}: incomplete runtime wheel set")


def base_published_build() -> int:
    result = subprocess.run(
        [
            "git",
            "show",
            "origin/main:native/gdal-runtime/published-build.txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return build_number(result.stdout)
    baseline = subprocess.check_output(
        ["git", "show", "origin/main:native/gdal-runtime/sources.lock"],
        text=True,
    )
    return locked_candidate(baseline)


def main() -> None:
    published = build_number(
        (ROOT / "native/gdal-runtime/published-build.txt").read_text(
            encoding="utf-8"
        )
    )
    candidate = locked_candidate(
        (ROOT / "native/gdal-runtime/sources.lock").read_text(encoding="utf-8")
    )
    requirements = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in RUNTIME_FILES
    }
    release = json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "repos/microsoft/haste/releases/tags/haste-binaries",
            ],
            text=True,
        )
    )
    validate_pins(
        requirements,
        published,
        candidate,
        base_published_build(),
        locked_assets(
            (ROOT / "native/gdal-runtime/published-assets.lock").read_text(
                encoding="utf-8"
            ),
            published,
        ),
        release["assets"],
    )
    print(
        f"Published build {published} assets are available; "
        f"candidate {candidate}."
    )


if __name__ == "__main__":
    main()
