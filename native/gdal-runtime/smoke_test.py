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


def binding_smoke_command(script: Path, python: str) -> list[str]:
    """Run the source smoke driver without shadowing installed packages.

    The driver is loaded by file path, but its directory is appended to
    ``sys.path`` so site-packages takes precedence for haste_gdal_runtime.
    """
    code = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        "script = sys.argv.pop(1)\n"
        "sys.path.append(str(Path(script).resolve().parent))\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    return [python, "-c", code, str(script)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", required=True, type=Path)
    parser.add_argument("--build", required=True)
    parser.add_argument("--expected-gdal", default="3.13.3")
    args = parser.parse_args(argv)

    distributions = {
        "haste-gdal-runtime": args.expected_gdal,
        "GDAL": args.expected_gdal,
        "rasterio": "1.4.4",
        "fiona": "1.10.1",
        "pyogrio": "0.13.0",
        "pyproj": "3.7.2",
    }
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
            *(
                f"{name}=={version}+haste.{args.build}"
                for name, version in distributions.items()
            ),
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
    ]
    for binding in (
        "osgeo.gdal",
        "rasterio",
        "fiona",
        "pyogrio",
        "pyproj",
    ):
        command.extend(["--require-binding", binding])
    for driver in DRIVERS:
        command.extend(["--allow-driver", driver])
    subprocess.run(command, check=True, cwd=args.wheel_dir.resolve())
    binding_smoke = Path(__file__).with_name("binding_workflow_smoke.py")
    subprocess.run(
        binding_smoke_command(binding_smoke, sys.executable),
        check=True,
        cwd=args.wheel_dir.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
