"""Install and verify the GDAL runtime and binding wheels offline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DRIVERS = (
    "GTiff",
    "COG",
    "VRT",
    "MEM",
    "PNG",
    "JPEG",
    "GeoJSON",
    "GeoJSONSeq",
    "ESRIJSON",
    "TopoJSON",
    "GPKG",
    "SQLite",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--build", required=True)
    parser.add_argument("--expected-gdal", default="3.13.3")
    args = parser.parse_args(argv)

    local_version = f"{args.expected_gdal}+haste.{args.build}"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--isolated",
            "--no-index",
            "--no-deps",
            "--find-links",
            str(args.wheel_dir),
            f"haste-gdal-runtime=={local_version}",
            f"GDAL=={local_version}",
        ],
        check=True,
    )
    command = [
        sys.executable,
        "-m",
        "haste_gdal_runtime",
        "verify",
        "--expected-gdal",
        args.expected_gdal,
        "--require-binding",
        "osgeo.gdal",
    ]
    for driver in DRIVERS:
        command.extend(["--allow-driver", driver])
    subprocess.run(command, check=True, cwd=args.wheel_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
