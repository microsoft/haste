"""Fail the native build if its GDAL manifest misses the approved baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXPECTED_DRIVERS = {
    "COG",
    "GTiff",
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
}


def validate(manifest: dict[str, object]) -> list[str]:
    errors = []
    if manifest.get("gdal_release") != "3.13.3":
        errors.append(
            "GDAL release is "
            f"{manifest.get('gdal_release')!r}, expected 3.13.3"
        )
    if manifest.get("proj_release") != "9.8.1":
        errors.append(
            "PROJ release is "
            f"{manifest.get('proj_release')!r}, expected 9.8.1"
        )
    if manifest.get("vrt_raw_band_compiled") is not False:
        errors.append("VRTRawRasterBand is compiled into libgdal")

    drivers = set(manifest.get("drivers", []))
    if drivers != EXPECTED_DRIVERS:
        errors.append(
            "GDAL driver inventory differs: "
            f"missing={sorted(EXPECTED_DRIVERS - drivers)}, "
            f"unexpected={sorted(drivers - EXPECTED_DRIVERS)}"
        )

    probes = manifest.get("probes_permissive", {})
    if not isinstance(probes, dict):
        errors.append("manifest has no permissive VRT probe results")
    else:
        for name in ("raw_band", "python_pixel_function"):
            if probes.get(name) not in ("rejected", "read-failed"):
                errors.append(
                    f"permissive {name} probe returned {probes.get(name)!r}"
                )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: verify_build_manifest.py MANIFEST.json", file=sys.stderr)
        return 2
    manifest = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    errors = validate(manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("GDAL build manifest meets the approved baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
