"""Merge native bindings, auditwheel once, then split immutable wheels.

This script consumes locally built binding wheels and the runtime package.
It performs no package resolution and passes no index URL to pip.
"""

from __future__ import annotations

import argparse
import atexit
import base64
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

RUNTIME_NAME = "haste-gdal-runtime"
RUNTIME_WHEEL_TAG = "py3-none-manylinux_2_28_x86_64"
STAGING_TAG = "cp311-cp311-linux_x86_64"
TARGET_TAG = "cp311-cp311-manylinux_2_28_x86_64"
REQUIRED_BINDINGS = {"GDAL", "rasterio", "fiona", "pyogrio", "pyproj"}
BINDING_MODULES = {
    "gdal": "osgeo.gdal",
    "rasterio": "rasterio",
    "fiona": "fiona",
    "pyogrio": "pyogrio",
    "pyproj": "pyproj",
}


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value).lower()


def read_metadata_fields(content: bytes) -> tuple[str, str]:
    name = ""
    version = ""
    for line in content.decode("utf-8").splitlines():
        if line.startswith("Name: "):
            name = line[6:].strip()
        elif line.startswith("Version: "):
            version = line[9:].strip()
        if name and version:
            break
    if not name or not version:
        raise ValueError("wheel METADATA must contain Name and Version")
    return name, version


def local_version(version: str, build: str) -> str:
    return f"{version.split('+', 1)[0]}+haste.{build}"


def replace_header(content: bytes, key: str, value: str) -> bytes:
    lines = content.decode("utf-8").splitlines()
    prefix = f"{key}: "
    found = False
    output = []
    for line in lines:
        if line.startswith(prefix):
            output.append(prefix + value)
            found = True
        else:
            output.append(line)
    if not found:
        output.insert(0, prefix + value)
    return ("\n".join(output) + "\n").encode("utf-8")


def update_metadata(
    content: bytes, version: str, runtime_version: str | None
) -> bytes:
    text = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    header_text, separator, body = text.partition("\n\n")
    lines = header_text.splitlines()
    output: list[str] = []
    saw_version = False
    index = 0
    while index < len(lines):
        line = lines[index]
        field, delimiter, value = line.partition(":")
        field_name = field.casefold()
        if delimiter and field_name == "version":
            output.append(f"{field}: {version}")
            saw_version = True
        elif delimiter and field_name == "requires-dist":
            field_lines = [line]
            index += 1
            while index < len(lines) and lines[index][:1] in {" ", "\t"}:
                field_lines.append(lines[index])
                index += 1
            requirement = " ".join(
                [value.strip(), *(part.strip() for part in field_lines[1:])]
            )
            if not re.match(
                r"haste[-_.]gdal[-_.]runtime(?:\s|[<>=!~;\[]|$)",
                requirement,
                re.IGNORECASE,
            ):
                output.extend(field_lines)
            continue
        else:
            output.append(line)
        index += 1
    if not saw_version:
        raise ValueError("wheel METADATA is missing Version")
    if runtime_version:
        output.append(f"Requires-Dist: {RUNTIME_NAME}=={runtime_version}")
    updated_header = "\n".join(output)
    updated = (
        f"{updated_header}\n\n{body}" if separator else f"{updated_header}\n"
    )
    return updated.encode("utf-8")


def rewrite_data_path(path: str, staging_data_prefix: str) -> str:
    """Map a wheel's .data tree into the staging wheel's .data tree."""
    match = re.match(r"[^/]+\.data/(.+)$", path)
    if match:
        return f"{staging_data_prefix}/{match.group(1)}"
    return path


def restore_data_path(path: str, name: str, version: str) -> str:
    """Give a .data member the matching output wheel's name and version."""
    match = re.match(r"[^/]+\.data/(.+)$", path)
    if match:
        prefix = f"{normalized_name(name)}-{version}.data"
        return f"{prefix}/{match.group(1)}"
    return path


def wheel_record(files: dict[str, bytes], record_path: str) -> bytes:
    rows = []
    for path, content in sorted(files.items()):
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        rows.append((path, f"sha256={digest}", str(len(content))))
    rows.append((record_path, "", ""))
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


@dataclass
class WheelInput:
    name: str
    version: str
    archive: Path
    dist_info: str
    metadata_files: dict[str, bytes] = field(default_factory=dict)
    stage_members: dict[str, str] = field(default_factory=dict)


def inspect_wheel(path: Path, stage_prefix: str) -> WheelInput:
    with zipfile.ZipFile(path) as archive:
        infos = {
            name.rsplit("/", 1)[0]
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        }
        if len(infos) != 1:
            raise ValueError(f"{path.name}: expected one dist-info directory")
        dist_info = infos.pop()
        metadata = archive.read(f"{dist_info}/METADATA")
        name, version = read_metadata_fields(metadata)
        result = WheelInput(name, version, path, dist_info)
        for member in archive.namelist():
            if member.endswith("/"):
                continue
            if member.startswith(f"{dist_info}/"):
                relative = member[len(dist_info) + 1 :]
                if relative not in {"RECORD", "METADATA", "WHEEL"}:
                    result.metadata_files[relative] = archive.read(member)
                continue
            stage_member = rewrite_data_path(member, stage_prefix)
            result.stage_members[member] = stage_member
        return result


def read_wheel_payload(wheel: WheelInput) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel.archive) as archive:
        return {
            stage_member: archive.read(source_member)
            for source_member, stage_member in wheel.stage_members.items()
        }


def read_runtime_package(runtime_package: Path) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    for path in sorted(runtime_package.rglob("*")):
        if path.is_file():
            relative = path.relative_to(runtime_package).as_posix()
            payload[f"haste_gdal_runtime/{relative}"] = path.read_bytes()
    return payload


def binding_versions(wheels: list[WheelInput]) -> dict[str, str]:
    """Return import-module version expectations from the binding wheel set."""
    versions = {}
    for wheel in wheels:
        module = BINDING_MODULES.get(normalized_name(wheel.name))
        if module is None:
            continue
        versions[module] = wheel.version.split("+", 1)[0]
    if set(versions) != set(BINDING_MODULES.values()):
        raise ValueError(
            "binding wheel set does not define every binding version"
        )
    return versions


def runtime_metadata_files(version: str, tag: str) -> dict[str, bytes]:
    license_path = Path(__file__).resolve().parents[2] / "LICENSE"
    if not license_path.is_file():
        raise FileNotFoundError(
            f"runtime package license is missing: {license_path}"
        )
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {RUNTIME_NAME}\n"
        f"Version: {version}\n"
        "Summary: HASTE's pinned GDAL native runtime\n"
        "Requires-Python: >=3.11\n"
        "License-Expression: MIT\n"
        "License-File: licenses/LICENSE\n\n"
    ).encode("utf-8")
    wheel = (
        "Wheel-Version: 1.0\n"
        "Generator: haste-gdal-runtime\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {tag}\n"
    ).encode("utf-8")
    return {
        "METADATA": metadata,
        "WHEEL": wheel,
        "licenses/LICENSE": license_path.read_bytes(),
    }


def write_wheel(
    destination: Path,
    payload: dict[str, bytes],
    metadata_files: dict[str, bytes],
    *,
    name: str,
    version: str,
    tag: str,
    pure: bool,
) -> None:
    dist_info = f"{normalized_name(name)}-{version}.dist-info"
    files = dict(payload)
    for relative, content in metadata_files.items():
        files[f"{dist_info}/{relative}"] = content
    files[f"{dist_info}/METADATA"] = metadata_files["METADATA"]
    wheel_metadata = replace_header(
        metadata_files["WHEEL"], "Root-Is-Purelib", "true" if pure else "false"
    )
    wheel_lines = [
        line
        for line in wheel_metadata.decode("utf-8").splitlines()
        if not line.startswith("Tag: ")
    ]
    wheel_lines.append(f"Tag: {tag}")
    files[f"{dist_info}/WHEEL"] = ("\n".join(wheel_lines) + "\n").encode()
    record_path = f"{dist_info}/RECORD"
    files[record_path] = wheel_record(files, record_path)

    filename_name = normalized_name(name)
    wheel_path = destination / (f"{filename_name}-{version}-{tag}.whl")
    with zipfile.ZipFile(
        wheel_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as out:
        for path, content in sorted(files.items()):
            out.writestr(path, content)


def merge_and_repair(
    binding_wheels: list[Path],
    runtime_package: Path,
    output: Path,
    build: str,
    gdal_version: str,
    prefix: Path,
) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    runtime_version = local_version(gdal_version, build)
    stage_prefix = f"{normalized_name(RUNTIME_NAME)}-{runtime_version}.data"
    inputs = [inspect_wheel(path, stage_prefix) for path in binding_wheels]
    names = {wheel.name for wheel in inputs}
    if names != REQUIRED_BINDINGS:
        missing = sorted(REQUIRED_BINDINGS - names)
        unexpected = sorted(names - REQUIRED_BINDINGS)
        raise ValueError(
            f"binding wheel set mismatch: missing={missing}, "
            f"unexpected={unexpected}"
        )

    owners: dict[str, dict[str, str]] = {}
    payload: dict[str, bytes] = {}
    for wheel in inputs:
        owners[wheel.name] = wheel.stage_members
        for stage_member, content in read_wheel_payload(wheel).items():
            previous = payload.get(stage_member)
            if previous is not None and previous != content:
                raise ValueError(
                    "wheel payload collision with different content: "
                    f"{stage_member}"
                )
            payload[stage_member] = content

    runtime_payload = read_runtime_package(runtime_package)
    manifest_member = "haste_gdal_runtime/manifest.json"
    manifest = json.loads(runtime_payload[manifest_member])
    manifest["binding_versions"] = binding_versions(inputs)
    runtime_payload[manifest_member] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    runtime_members = {member: member for member in runtime_payload}
    for member, content in runtime_payload.items():
        previous = payload.get(member)
        if previous is not None and previous != content:
            raise ValueError(f"runtime package payload collision: {member}")
        payload[member] = content
    owners[RUNTIME_NAME] = runtime_members

    staging_metadata = runtime_metadata_files(runtime_version, STAGING_TAG)
    staging_temp = tempfile.TemporaryDirectory(prefix="haste-gdal-assemble-")
    atexit.register(staging_temp.cleanup)
    staging = Path(staging_temp.name)
    stage_payload = dict(payload)
    staging_dist_info = (
        f"{normalized_name(RUNTIME_NAME)}-{runtime_version}.dist-info"
    )
    staging_record = f"{staging_dist_info}/RECORD"
    for relative, content in staging_metadata.items():
        stage_payload[f"{staging_dist_info}/{relative}"] = content
    stage_payload[staging_record] = wheel_record(stage_payload, staging_record)
    staging_wheel = staging / (
        f"{normalized_name(RUNTIME_NAME)}-{runtime_version}-{STAGING_TAG}.whl"
    )
    with zipfile.ZipFile(
        staging_wheel, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for member, content in sorted(stage_payload.items()):
            archive.writestr(member, content)

    repaired_dir = staging / "repaired"
    repaired_dir.mkdir()
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        filter(None, [str(prefix / "lib"), env.get("LD_LIBRARY_PATH", "")])
    )
    subprocess.run(
        [
            "auditwheel",
            "repair",
            "--plat",
            "manylinux_2_28_x86_64",
            "--wheel-dir",
            str(repaired_dir),
            str(staging_wheel),
        ],
        check=True,
        env=env,
    )
    repaired_wheels = list(repaired_dir.glob("*.whl"))
    if len(repaired_wheels) != 1:
        raise RuntimeError(
            f"auditwheel produced {len(repaired_wheels)} wheels, expected one"
        )
    repaired_path = repaired_wheels[0]
    with zipfile.ZipFile(repaired_path) as archive:
        repaired_names = archive.namelist()
        dist_info = next(
            name.rsplit("/", 1)[0]
            for name in repaired_names
            if name.endswith(".dist-info/WHEEL")
        )
        wheel_text = archive.read(f"{dist_info}/WHEEL").decode("utf-8")
        tags = [
            line[5:].strip()
            for line in wheel_text.splitlines()
            if line.startswith("Tag: ")
        ]
        if TARGET_TAG not in tags:
            raise RuntimeError(
                f"auditwheel did not produce required tag {TARGET_TAG}: {tags}"
            )
        libraries = {
            name: archive.read(name)
            for name in repaired_names
            if name.startswith(f"{normalized_name(RUNTIME_NAME)}.libs/")
            and not name.endswith("/")
        }
        if not libraries:
            raise RuntimeError("auditwheel did not graft native libraries")

        outputs = []
        for wheel in inputs:
            version = local_version(wheel.version, build)
            source_metadata = zipfile.ZipFile(wheel.archive)
            original_metadata = source_metadata.read(
                f"{wheel.dist_info}/METADATA"
            )
            original_wheel = source_metadata.read(f"{wheel.dist_info}/WHEEL")
            source_metadata.close()
            meta_files = dict(wheel.metadata_files)
            meta_files["METADATA"] = update_metadata(
                original_metadata, version, runtime_version
            )
            tags_in_wheel = [f"Tag: {tag}" for tag in tags]
            wheel_lines = [
                line
                for line in original_wheel.decode("utf-8").splitlines()
                if not line.startswith("Tag: ")
                and not line.startswith("Root-Is-Purelib: ")
            ]
            wheel_lines.extend(["Root-Is-Purelib: false", *tags_in_wheel])
            meta_files["WHEEL"] = ("\n".join(wheel_lines) + "\n").encode()
            contents = {
                restore_data_path(
                    output_member, wheel.name, version
                ): archive.read(stage_member)
                for output_member, stage_member in wheel.stage_members.items()
            }
            wheel_output = (
                output
                / f"{normalized_name(wheel.name)}-{version}-{TARGET_TAG}.whl"
            )
            write_wheel(
                output,
                contents,
                meta_files,
                name=wheel.name,
                version=version,
                tag=TARGET_TAG,
                pure=False,
            )
            outputs.append(wheel_output)

        runtime_contents = {
            output_member: archive.read(stage_member)
            for output_member, stage_member in runtime_members.items()
        }
        runtime_contents.update(libraries)
        runtime_meta = runtime_metadata_files(
            runtime_version, RUNTIME_WHEEL_TAG
        )
        write_wheel(
            output,
            runtime_contents,
            runtime_meta,
            name=RUNTIME_NAME,
            version=runtime_version,
            tag=RUNTIME_WHEEL_TAG,
            pure=False,
        )
        outputs.append(
            output / f"{normalized_name(RUNTIME_NAME)}-{runtime_version}-"
            f"{RUNTIME_WHEEL_TAG}.whl"
        )
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--runtime-package", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--build", required=True)
    parser.add_argument("--gdal-version", required=True)
    parser.add_argument("--prefix", required=True, type=Path)
    args = parser.parse_args(argv)

    binding_wheels = sorted(args.wheel_dir.glob("*.whl"))
    outputs = merge_and_repair(
        binding_wheels,
        args.runtime_package,
        args.output_dir,
        args.build,
        args.gdal_version,
        args.prefix,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
