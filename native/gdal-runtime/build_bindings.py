"""Build pinned Python bindings against the local native GDAL runtime.

The sdists must already be present in ``--sdist-dir`` and the two venvs must
already contain their hash-locked build requirements. This script uses
``--no-index`` and never resolves or installs packages.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tarfile
from pathlib import Path


def find_sdist(directory: Path, distribution: str, version: str) -> Path:
    prefix = f"{distribution}-{version}".lower().replace("_", "-")
    matches = [
        path
        for path in directory.iterdir()
        if path.name.lower().replace("_", "-").startswith(prefix)
        and path.name.endswith((".tar.gz", ".tgz"))
    ]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one sdist for {distribution} {version} "
            f"in {directory}, found {len(matches)}"
        )
    return matches[0]


def check_sdist(path: Path) -> None:
    if not tarfile.is_tarfile(path):
        raise ValueError(f"not a valid source archive: {path.name}")


def build_wheel(
    python: Path, sdist: Path, output: Path, env: dict[str, str]
) -> None:
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(output),
            str(sdist),
        ],
        check=True,
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--sdist-dir", required=True, type=Path)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--common-venv", required=True, type=Path)
    parser.add_argument("--fiona-venv", required=True, type=Path)
    args = parser.parse_args(argv)

    version = subprocess.run(
        [
            str(args.python),
            "-c",
            "import sys; print('.'.join(map(str, sys.version_info[:2])))",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if version != "3.11":
        raise RuntimeError(
            f"binding builds require CPython 3.11, got {version}"
        )
    source_dir = args.sdist_dir.resolve()
    wheel_dir = args.wheel_dir.resolve()
    prefix = args.prefix.resolve()
    wheel_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GDAL_CONFIG"] = str(prefix / "bin" / "gdal-config")
    env["PROJ_DIR"] = str(prefix)
    env["PROJ_VERSION"] = env.get("PROJ_VERSION", "")
    env["PATH"] = str(prefix / "bin") + os.pathsep + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        filter(
            None,
            [
                str(prefix / "lib"),
                env.get("LD_LIBRARY_PATH", ""),
            ],
        )
    )
    env["CMAKE_PREFIX_PATH"] = os.pathsep.join(
        filter(
            None,
            [
                str(prefix),
                env.get("CMAKE_PREFIX_PATH", ""),
            ],
        )
    )

    bindings = (
        ("GDAL", "3.13.3", args.common_venv / "bin" / "python"),
        ("rasterio", "1.4.4", args.common_venv / "bin" / "python"),
        ("fiona", "1.10.1", args.fiona_venv / "bin" / "python"),
        ("pyogrio", "0.13.0", args.common_venv / "bin" / "python"),
        ("pyproj", "3.7.2", args.common_venv / "bin" / "python"),
    )
    for distribution, version, python in bindings:
        sdist = find_sdist(source_dir, distribution, version)
        check_sdist(sdist)
        print(f"building {distribution} {version}", flush=True)
        build_wheel(python, sdist, wheel_dir, env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
