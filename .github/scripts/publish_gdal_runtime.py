#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Validate and immutably publish one HASTE GDAL runtime bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hastelib"))

from haste_release import (  # noqa: E402
    RELEASE_TAG,
    REPOSITORY,
    list_release_assets,
)

EXPECTED_DISTRIBUTIONS = {
    "haste-gdal-runtime",
    "gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
}
BINDING_MODULES = {
    "gdal": "osgeo.gdal",
    "rasterio": "rasterio",
    "fiona": "fiona",
    "pyogrio": "pyogrio",
    "pyproj": "pyproj",
}
EVIDENCE_FILES = {
    "manifest.json",
    "bom.cdx.json",
    "THIRD_PARTY_NOTICES.txt",
}
SOURCE_LOCK_PATH = REPO_ROOT / "native" / "gdal-runtime" / "sources.lock"
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_.+-]+)$")
CommandRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class RuntimeBundle:
    """Validated bundle contents ready for immutable publication."""

    directory: Path
    assets: tuple[Path, ...]
    gdal_version: str
    runtime_version: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wheel_metadata(path: Path) -> tuple[Message, list[str]]:
    if not zipfile.is_zipfile(path):
        raise ValueError(f"Not a valid wheel ZIP file: {path.name}")
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        wheel_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/WHEEL")
        ]
        if len(names) != 1 or len(wheel_names) != 1:
            raise ValueError(
                f"{path.name}: expected one METADATA and WHEEL file"
            )
        metadata = BytesParser().parsebytes(archive.read(names[0]))
        tags = [
            line[5:].strip()
            for line in archive.read(wheel_names[0])
            .decode("utf-8")
            .splitlines()
            if line.startswith("Tag: ")
        ]
        return metadata, tags


def _read_checksums(path: Path) -> dict[str, str]:
    checksums = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        match = _CHECKSUM_LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Invalid SHA256SUMS entry on line {line_number}")
        digest, name = match.groups()
        if name in checksums:
            raise ValueError(f"Duplicate SHA256SUMS entry: {name}")
        checksums[name] = digest
    return checksums


def _locked_native_sources(path: Path | None = None) -> dict[str, str]:
    source_lock_path = SOURCE_LOCK_PATH if path is None else path
    sources = {}
    for line in source_lock_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if fields[0] == "HASTE_GDAL_BUILD":
            continue
        if len(fields) != 4:
            raise ValueError(f"Invalid native source lock row: {line!r}")
        name, version, _, _ = fields
        if name in sources:
            raise ValueError(f"Duplicate native source lock entry: {name}")
        sources[name] = version
    if not sources:
        raise ValueError("Native source lock has no source entries")
    return sources


def validate_bundle(directory: Path) -> RuntimeBundle:
    """Verify exact bundle contents, wheel identities, licenses and hashes."""
    if not directory.is_dir():
        raise FileNotFoundError(
            f"Runtime artifact directory is missing: {directory}"
        )
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != len(EXPECTED_DISTRIBUTIONS):
        raise ValueError(f"Expected six runtime wheels, found {len(wheels)}")

    manifest = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    gdal_version = manifest.get("gdal_release")
    if not isinstance(gdal_version, str) or not gdal_version:
        raise ValueError("Runtime manifest has no GDAL release")

    wheel_names = set()
    wheel_metadata = {}
    runtime_version = ""
    build_number = ""
    for path in wheels:
        metadata, tags = _wheel_metadata(path)
        name = re.sub(r"[-_.]+", "-", metadata.get("Name", "").lower())
        version = metadata.get("Version", "")
        if name not in EXPECTED_DISTRIBUTIONS or name in wheel_names:
            raise ValueError(
                f"Unexpected or duplicate wheel distribution: {name}"
            )
        wheel_names.add(name)
        if not metadata.get("License-Expression") and not metadata.get(
            "License"
        ):
            raise ValueError(f"{path.name}: wheel has no license metadata")
        if name == "haste-gdal-runtime" and not metadata.get(
            "License-Expression"
        ):
            raise ValueError(
                "Runtime wheel must declare an SPDX License-Expression"
            )
        normalized_filename_name = re.sub(r"[-_.]+", "_", name).lower()
        expected_tag = (
            "py3-none-manylinux_2_28_x86_64"
            if name == "haste-gdal-runtime"
            else "cp311-cp311-manylinux_2_28_x86_64"
        )
        expected_filename = (
            f"{normalized_filename_name}-{version}-{expected_tag}.whl"
        )
        if path.name != expected_filename or tags != [expected_tag]:
            raise ValueError(
                f"{path.name}: wheel filename/tag is not {expected_filename}"
            )
        match = re.fullmatch(r"(.+)\+haste\.(\d+)", version)
        if not match:
            raise ValueError(
                f"{path.name}: version must include a HASTE build number"
            )
        base_version, number = match.groups()
        if build_number and number != build_number:
            raise ValueError("Runtime wheels have inconsistent build numbers")
        build_number = number
        if name in {"gdal", "haste-gdal-runtime"}:
            if base_version != gdal_version:
                raise ValueError(
                    f"{path.name}: version does not match GDAL {gdal_version}"
                )
        wheel_metadata[name] = metadata
        if name == "haste-gdal-runtime":
            runtime_version = version

    if wheel_names != EXPECTED_DISTRIBUTIONS or not runtime_version:
        raise ValueError("Runtime wheel set is incomplete")
    for name, metadata in wheel_metadata.items():
        if name == "haste-gdal-runtime":
            continue
        required_runtime = (
            re.sub(
                r"\s+",
                "",
                f"haste-gdal-runtime=={runtime_version}",
            )
            .replace("_", "-")
            .lower()
        )
        requirements = [
            re.sub(r"\s+", "", value).replace("_", "-").lower()
            for value in metadata.get_all("Requires-Dist", [])
        ]
        if not any(
            required_runtime in requirement for requirement in requirements
        ):
            raise ValueError(
                f"{metadata.get('Name')}: does not pin "
                f"haste-gdal-runtime=={runtime_version}; found {requirements}"
            )

    expected_binding_versions = {
        module: wheel_metadata[name].get("Version", "").split("+", 1)[0]
        for name, module in BINDING_MODULES.items()
    }
    if manifest.get("binding_versions") != expected_binding_versions:
        raise ValueError(
            "Runtime manifest binding versions do not match the wheels"
        )

    notices_path = directory / "THIRD_PARTY_NOTICES.txt"
    notices = notices_path.read_text(encoding="utf-8")
    if "review required" in notices.casefold():
        raise ValueError(
            "Third-party notices still contain items marked for review"
        )
    bom = json.loads((directory / "bom.cdx.json").read_text(encoding="utf-8"))
    if bom.get("bomFormat") != "CycloneDX" or bom.get("specVersion") != "1.6":
        raise ValueError("Runtime SBOM must be CycloneDX 1.6")
    components = bom.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("Runtime SBOM has no components")
    unlicensed = sorted(
        component.get("name", "<unnamed>")
        for component in components
        if not component.get("licenses")
    )
    if unlicensed:
        raise ValueError(
            "Runtime SBOM components lack license metadata: "
            + ", ".join(unlicensed)
        )
    observed_sources = {}
    for component in components:
        if not component.get("purl", "").startswith("pkg:generic/"):
            continue
        name = component.get("name")
        if not isinstance(name, str) or name in observed_sources:
            raise ValueError("Runtime SBOM has an invalid or duplicate source")
        observed_sources[name] = component.get("version")
    locked_sources = _locked_native_sources()
    if observed_sources != locked_sources:
        missing_sources = {
            name: version
            for name, version in locked_sources.items()
            if observed_sources.get(name) != version
        }
        unexpected_sources = sorted(
            set(observed_sources) - set(locked_sources)
        )
        details = [
            f"{name}=={version}"
            for name, version in sorted(missing_sources.items())
        ]
        details.extend(f"unexpected {name}" for name in unexpected_sources)
        raise ValueError(
            "Runtime SBOM does not match sources.lock: " + ", ".join(details)
        )

    checksums_path = directory / "SHA256SUMS"
    checksums = _read_checksums(checksums_path)
    expected_files = {path.name for path in wheels} | EVIDENCE_FILES
    if set(checksums) != expected_files:
        raise ValueError("SHA256SUMS does not cover the exact runtime bundle")
    for name, digest in checksums.items():
        path = directory / name
        if not path.is_file() or _sha256(path) != digest:
            raise ValueError(f"SHA-256 mismatch or missing asset: {name}")

    entries = list(directory.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise ValueError("Runtime artifact directory has non-file entries")
    actual_files = {path.name for path in entries}
    if actual_files != expected_files | {"SHA256SUMS"}:
        raise ValueError("Runtime artifact directory has unexpected files")

    return RuntimeBundle(
        directory=directory,
        assets=tuple(
            [
                *wheels,
                *(directory / name for name in sorted(EVIDENCE_FILES)),
                checksums_path,
            ]
        ),
        gdal_version=gdal_version,
        runtime_version=runtime_version,
    )


def run_command(command: Sequence[str]) -> str:
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def publish_bundle(
    bundle: RuntimeBundle,
    *,
    runner: CommandRunner = run_command,
    asset_lister: Callable[[], list[str]] = list_release_assets,
) -> None:
    """Publish assets to haste-binaries without overwriting existing assets."""
    names = {path.name for path in bundle.assets}
    collisions = sorted(names & set(asset_lister()))
    if collisions:
        raise ValueError(
            "Release assets already exist and will not be overwritten: "
            + ", ".join(collisions)
        )
    runner(
        [
            "gh",
            "release",
            "upload",
            RELEASE_TAG,
            *(str(path) for path in bundle.assets),
            "--repo",
            REPOSITORY,
        ]
    )
    missing = sorted(names - set(asset_lister()))
    if missing:
        raise RuntimeError(
            "Upload succeeded but release assets are missing: "
            + ", ".join(missing)
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the bundle without querying or mutating GitHub",
    )
    args = parser.parse_args(argv)

    bundle = validate_bundle(args.artifact_dir)
    if not args.validate_only:
        publish_bundle(bundle)
    print(
        f"Validated GDAL {bundle.gdal_version} runtime "
        f"{bundle.runtime_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
