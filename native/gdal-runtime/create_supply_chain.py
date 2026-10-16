"""Create an inventory, notices bundle and checksums for runtime artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import uuid
import zipfile
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from fetch_sources import parse_lock

LICENSE_NAMES = {
    "copying",
    "copying.md",
    "copying.txt",
    "copyright",
    "copyright.md",
    "copyright.txt",
    "license",
    "license.md",
    "license.rst",
    "license.txt",
    "notice",
    "notice.md",
    "notice.txt",
}
MAX_NOTICE_SIZE = 2 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _notice_path(name: str, path: str) -> str:
    if name in {"", ".", ".."} or "/" in name or "\\" in name or ":" in name:
        raise ValueError(f"unsafe notice component: {name!r}")
    safe_parts = []
    for part in PurePosixPath(path).parts:
        if part in {"", ".", ".."} or ":" in part:
            raise ValueError(f"unsafe notice path: {path!r}")
        safe_parts.append(part)
    return "/".join(["licenses", name, *safe_parts])


def extract_native_notices(
    archive_path: Path, component: str
) -> dict[str, bytes]:
    notices: dict[str, bytes] = {}
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            basename = PurePosixPath(member.name).name.casefold()
            if basename not in LICENSE_NAMES:
                continue
            if member.size > MAX_NOTICE_SIZE:
                raise ValueError(
                    f"{archive_path.name}:{member.name} "
                    "exceeds notice size limit"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(
                    f"cannot read notice {member.name} "
                    f"from {archive_path.name}"
                )
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(
                    f"unsafe notice path in {archive_path.name}: {member.name}"
                )
            notice_path = _notice_path(component, relative.as_posix())
            notices[notice_path] = stream.read()
    return notices


def wheel_inventory(
    wheel_paths: list[Path],
) -> tuple[list[dict[str, object]], dict[str, bytes], dict[str, str]]:
    components: list[dict[str, object]] = []
    notices: dict[str, bytes] = {}
    licenses: dict[str, str] = {}
    for path in sorted(wheel_paths):
        with zipfile.ZipFile(path) as wheel:
            metadata_names = [
                name
                for name in wheel.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ValueError(
                    f"{path.name}: expected one wheel METADATA file"
                )
            metadata = BytesParser().parsebytes(wheel.read(metadata_names[0]))
            name = metadata.get("Name")
            version = metadata.get("Version")
            if not name or not version:
                raise ValueError(
                    f"{path.name}: wheel metadata lacks name or version"
                )
            package_name = re.sub(r"[-_.]+", "-", name.lower())
            component: dict[str, object] = {
                "type": "library",
                "name": name,
                "version": version,
                "purl": (
                    f"pkg:pypi/{quote(package_name, safe='-.')}@"
                    f"{quote(version, safe='.+-')}"
                ),
                "hashes": [{"alg": "SHA-256", "content": sha256(path)}],
            }
            license_expression = metadata.get("License-Expression")
            license_name = metadata.get("License")
            license_value = license_expression or license_name
            if license_value:
                component["licenses"] = [{"license": {"name": license_value}}]
                licenses[name] = license_value
            else:
                licenses[name] = (
                    "No license metadata in wheel; review required"
                )
            components.append(component)

            for member in wheel.namelist():
                if ".dist-info/licenses/" not in member:
                    continue
                info = wheel.getinfo(member)
                if info.file_size > MAX_NOTICE_SIZE:
                    raise ValueError(
                        f"{path.name}:{member} exceeds notice size limit"
                    )
                content = wheel.read(info)
                relative = member.split(".dist-info/licenses/", 1)[1]
                if relative:
                    notices[_notice_path(name, relative)] = content
    return components, notices, licenses


def generate(
    source_lock: Path,
    source_dir: Path,
    wheel_dir: Path,
    manifest_path: Path,
    output_dir: Path,
) -> list[Path]:
    _, sources = parse_lock(source_lock.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wheel_paths = sorted(wheel_dir.glob("*.whl"))
    if not wheel_paths:
        raise ValueError(f"no wheels found in {wheel_dir}")

    components: list[dict[str, object]] = []
    notices: dict[str, bytes] = {}
    license_status: dict[str, str] = {}
    for source in sources:
        archive_path = source_dir / source.filename
        if not archive_path.is_file():
            raise FileNotFoundError(
                f"locked source archive is missing: {source.filename}"
            )
        actual_digest = sha256(archive_path)
        if actual_digest != source.sha256:
            raise ValueError(
                f"{source.filename}: sha256 {actual_digest} "
                f"does not match sources.lock"
            )
        components.append(
            {
                "type": "library",
                "name": source.name,
                "version": source.version,
                "purl": (
                    f"pkg:generic/{quote(source.name, safe='-._')}@"
                    f"{quote(source.version, safe='.+-')}"
                ),
                "hashes": [{"alg": "SHA-256", "content": source.sha256}],
                "externalReferences": [
                    {
                        "type": "distribution",
                        "url": source.url,
                    }
                ],
            }
        )
        native_notices = extract_native_notices(archive_path, source.name)
        notices.update(native_notices)
        license_status[source.name] = (
            "Bundled source license file(s): "
            + ", ".join(sorted(native_notices))
            if native_notices
            else "No license file found in source archive; review required"
        )

    python_components, python_notices, python_licenses = wheel_inventory(
        wheel_paths
    )
    expected_distributions = {
        "haste-gdal-runtime",
        "gdal",
        "rasterio",
        "fiona",
        "pyogrio",
        "pyproj",
    }
    actual_distributions = {
        str(component["name"]).casefold() for component in python_components
    }
    if actual_distributions != expected_distributions:
        raise ValueError(
            "runtime wheel set does not match expected distributions: "
            f"{sorted(actual_distributions)}"
        )
    components.extend(python_components)
    notices.update(python_notices)
    license_status.update(python_licenses)

    runtime_version = next(
        component["version"]
        for component in python_components
        if component["name"].casefold() == "haste-gdal-runtime"
    )
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "name": "haste-gdal-runtime-bundle",
                "version": str(runtime_version),
            },
            "properties": [
                {
                    "name": f"gdal_runtime.{key}",
                    "value": json.dumps(value, sort_keys=True),
                }
                for key, value in sorted(manifest.items())
            ],
        },
        "components": components,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_manifest = output_dir / "manifest.json"
    shutil.copyfile(manifest_path, artifact_manifest)
    bom_path = output_dir / "bom.cdx.json"
    bom_path.write_text(
        json.dumps(bom, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    notice_path = output_dir / "THIRD_PARTY_NOTICES.txt"
    with notice_path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(
            "HASTE GDAL runtime third-party notices\n"
            "=======================================\n\n"
            "Native source archives and Python binding wheels are pinned in "
            "the build inputs.\n"
            "License files discovered in those archives/wheels follow. "
            "Any missing license text requires review before publication.\n\n"
        )
        output.write("Component/license inventory\n")
        output.write("----------------------------\n")
        for component, status in sorted(license_status.items()):
            output.write(f"- {component}: {status}\n")
        output.write("\n")
        for member, content in sorted(notices.items()):
            output.write(f"\n----- {member} -----\n")
            output.write(content.decode("utf-8", errors="replace"))
            if not content.endswith(b"\n"):
                output.write("\n")

    checksum_paths = [
        *wheel_paths,
        artifact_manifest,
        bom_path,
        notice_path,
    ]
    checksums_path = output_dir / "SHA256SUMS"
    with checksums_path.open("w", encoding="utf-8", newline="\n") as output:
        for path in sorted(checksum_paths):
            output.write(f"{sha256(path)}  {path.name}\n")
    return [artifact_manifest, bom_path, notice_path, checksums_path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lock", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    for path in generate(
        args.source_lock,
        args.source_dir,
        args.wheel_dir,
        args.manifest,
        args.output_dir,
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
