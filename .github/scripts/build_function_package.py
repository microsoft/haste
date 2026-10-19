#!/usr/bin/env python3
"""Build a build-once Azure Functions package against the HASTE GDAL wheels."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

RUNTIME_BINDINGS = {
    "gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
    "haste-gdal-runtime",
}
FUNCTION_APP_MODULES = {
    "hastefuncapi": "function_app",
    "hastefuncqueues": "function_app",
    "titilerfuncapi": "app",
    "imageryprep-smoke": "hastegeo.workflows.prepare_imagery",
}
HASTEGEO_CONSUMERS = {"hastefuncapi", "hastefuncqueues"}


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as wheel:
        metadata_files = [
            name
            for name in wheel.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name}: expected one wheel METADATA file")
        metadata = BytesParser().parsebytes(wheel.read(metadata_files[0]))
    name = metadata.get("Name")
    version = metadata.get("Version")
    if not name or not version:
        raise ValueError(f"{path.name}: missing distribution name or version")
    return normalized_name(name), version


def runtime_wheel_requirements(wheel_dir: Path) -> list[str]:
    wheels = sorted(wheel_dir.glob("*.whl"))
    if len(wheels) != 6:
        raise ValueError(f"expected six runtime wheels, found {len(wheels)}")
    requirements: dict[str, str] = {}
    for wheel in wheels:
        name, version = wheel_metadata(wheel)
        if name in requirements:
            raise ValueError(f"duplicate runtime wheel for {name}")
        requirements[name] = version
    if set(requirements) != RUNTIME_BINDINGS:
        raise ValueError(
            "runtime wheel set mismatch: "
            f"missing={sorted(RUNTIME_BINDINGS - set(requirements))}, "
            f"unexpected={sorted(set(requirements) - RUNTIME_BINDINGS)}"
        )
    return [f"{name}=={requirements[name]}" for name in sorted(requirements)]


def _requirement_name(line: str) -> str | None:
    content = line.strip()
    if not content or content.startswith("#") or content.startswith("-"):
        return None
    match = re.match(r"([A-Za-z0-9_.-]+)(?=\s|[<=>!~;\[]|$)", content)
    return normalized_name(match.group(1)) if match else None


def prepare_requirements(
    source: Path,
    output: Path,
    wheel_dir: Path,
    hastegeo_wheel: Path | None,
) -> None:
    """Replace legacy GDAL bindings and editable hastegeo with the built wheels."""
    lines = source.read_text(encoding="utf-8").splitlines()
    retained = []
    for line in lines:
        name = _requirement_name(line)
        if name in RUNTIME_BINDINGS or (
            name == "hastegeo" or line.strip().startswith("-e ")
        ):
            continue
        retained.append(line)
    additions = runtime_wheel_requirements(wheel_dir)
    if hastegeo_wheel is not None:
        additions.append(f"hastegeo @ {hastegeo_wheel.resolve().as_uri()}")
    output.write_text(
        "\n".join(
            [
                *retained,
                "",
                "# Exact wheel versions from this build; the lock records hashes.",
                *additions,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _pip_index_arguments() -> list[str]:
    index_url = os.environ.get("PIP_INDEX_URL", "https://pypi.org/simple")
    return ["--index-url", index_url]


def write_lock(wheelhouse: Path, path: Path) -> None:
    entries: dict[str, tuple[str, str]] = {}
    for wheel in sorted(wheelhouse.glob("*.whl")):
        name, version = wheel_metadata(wheel)
        if name in entries:
            raise ValueError(f"wheelhouse has duplicate distributions: {name}")
        entries[name] = (version, sha256(wheel))
    if not entries:
        raise ValueError("dependency resolver produced an empty wheelhouse")
    path.write_text(
        "".join(
            f"{name}=={version} --hash=sha256:{digest}\n"
            for name, (version, digest) in sorted(entries.items())
        ),
        encoding="utf-8",
    )


def _copy_function_source(source: Path, target: Path) -> None:
    ignored = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".venv",
        "venv",
        ".python_packages",
    )
    shutil.copytree(source, target, ignore=ignored, dirs_exist_ok=True)


def _write_zip(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def build_package(
    *,
    app_name: str,
    source_dir: Path,
    requirements: Path,
    wheel_dir: Path,
    hastegeo_wheel: Path | None,
    output_dir: Path,
) -> Path:
    if app_name not in FUNCTION_APP_MODULES:
        raise ValueError(f"unsupported Function App: {app_name}")
    if (app_name in HASTEGEO_CONSUMERS) != (hastegeo_wheel is not None):
        raise ValueError(
            f"{app_name} requires hastegeo wheel input "
            f"={app_name in HASTEGEO_CONSUMERS}"
        )
    if not source_dir.is_dir() or not requirements.is_file():
        raise FileNotFoundError(
            "Function source or requirements file is missing"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"haste-{app_name}-") as temporary:
        root = Path(temporary)
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir()
        target = root / ".python_packages" / "lib" / "site-packages"
        target.mkdir(parents=True)
        generated_requirements = root / "requirements.in"
        lock_file = root / "requirements.lock"
        prepare_requirements(
            requirements, generated_requirements, wheel_dir, hastegeo_wheel
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--isolated",
                *_pip_index_arguments(),
                "--only-binary=:all:",
                "--find-links",
                str(wheel_dir.resolve()),
                "--dest",
                str(wheelhouse),
                "-r",
                str(generated_requirements),
            ],
            check=True,
        )
        write_lock(wheelhouse, lock_file)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--isolated",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "--only-binary=:all:",
                "--require-hashes",
                "--target",
                str(target),
                "-r",
                str(lock_file),
            ],
            check=True,
        )

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(target)
        environment["HASTE_GDAL_RUNTIME_REQUIRED"] = "true"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "check",
            ],
            check=True,
            env=environment,
        )
        application_environment = environment.copy()
        application_environment["PYTHONPATH"] = os.pathsep.join(
            [str(target), str(source_dir.resolve())]
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                f"import {FUNCTION_APP_MODULES[app_name]}",
            ],
            check=True,
            cwd=source_dir,
            env=application_environment,
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import hastegeo; import haste_gdal_runtime; "
                "print(haste_gdal_runtime.verify_or_raise("
                "haste_gdal_runtime.Policy("
                "expected_gdal='3.13.3', "
                "required_bindings=('osgeo.gdal','rasterio','fiona',"
                "'pyogrio','pyproj'))))",
            ],
            check=True,
            env=environment,
        )

        package_root = root / "package"
        package_root.mkdir()
        _copy_function_source(source_dir, package_root)
        destination_packages = (
            package_root / ".python_packages" / "lib" / "site-packages"
        )
        destination_packages.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, destination_packages)
        shutil.copyfile(lock_file, package_root / "requirements.lock")
        shutil.copyfile(lock_file, package_root / "requirements.txt")
        shutil.copyfile(
            wheel_dir / "manifest.json",
            package_root / "gdal-runtime-manifest.json",
        )
        archive_path = output_dir / f"{app_name}.zip"
        _write_zip(package_root, archive_path)
        (output_dir / f"{app_name}.sha256").write_text(
            f"{sha256(archive_path)}  {archive_path.name}\n",
            encoding="utf-8",
        )
        return archive_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--hastegeo-wheel", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    archive = build_package(
        app_name=args.app_name,
        source_dir=args.source_dir,
        requirements=args.requirements,
        wheel_dir=args.wheel_dir,
        hastegeo_wheel=args.hastegeo_wheel,
        output_dir=args.output_dir,
    )
    print(f"Built {archive} ({sha256(archive)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
