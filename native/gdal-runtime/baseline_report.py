"""Capture GDAL bindings, native libraries, drivers, VSI handlers and config."""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

from haste_gdal_runtime._native import NativeGdal, mapped_libraries

BINDING_MODULES = (
    "osgeo.gdal",
    "rasterio",
    "fiona",
    "pyogrio",
    "pyproj",
)
CONFIG_KEYS = (
    "GDAL_VRT_ENABLE_RAWRASTERBAND",
    "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE",
    "GDAL_VRT_ENABLE_PYTHON",
    "GDAL_VRT_PYTHON_TRUSTED_MODULES",
    "GDAL_DRIVER_PATH",
    "GDAL_PYTHON_DRIVER_PATH",
    "GDAL_DISABLE_READDIR_ON_OPEN",
    "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED",
    "GDAL_DATA",
    "PROJ_DATA",
    "PROJ_LIB",
    "GDAL_SKIP",
)


def _binding_info(name: str, module: Any) -> dict[str, str]:
    info = {"version": str(getattr(module, "__version__", ""))}
    if name == "osgeo.gdal":
        info["gdal"] = module.VersionInfo("RELEASE_NAME")
    elif name in ("rasterio", "fiona"):
        info["gdal"] = str(module.__gdal_version__)
    elif name == "pyogrio":
        info["gdal"] = str(module.__gdal_version_string__)
    elif name == "pyproj":
        info["proj"] = str(
            getattr(module, "__proj_version__", None)
            or module.proj_version_str
        )
    return info


def collect_report(maps_text: str | None = None) -> dict[str, Any]:
    bindings: dict[str, dict[str, str]] = {}
    import_errors: dict[str, str] = {}
    for name in BINDING_MODULES:
        try:
            module = importlib.import_module(name)
        except (ImportError, OSError, RuntimeError) as error:
            import_errors[name] = f"{type(error).__name__}: {error}"
        else:
            bindings[name] = _binding_info(name, module)

    libraries = {
        stem: mapped_libraries(stem, maps_text)
        for stem in ("libgdal", "libproj")
    }
    native_report: dict[str, Any] = {
        "library": None,
        "version": None,
        "drivers": [],
        "vsi_prefixes": [],
        "config": {},
        "error": None,
    }
    gdal_libraries = libraries["libgdal"]
    if gdal_libraries:
        try:
            native = NativeGdal(Path(gdal_libraries[0]))
            native_report.update(
                {
                    "library": str(native.path),
                    "version": native.version_info("RELEASE_NAME"),
                    "drivers": native.drivers(),
                    "vsi_prefixes": native.vsi_prefixes(),
                    "config": {key: native.config(key) for key in CONFIG_KEYS},
                }
            )
        except (OSError, AttributeError, RuntimeError) as error:
            native_report["error"] = f"{type(error).__name__}: {error}"

    return {
        "python": sys.version,
        "platform": platform.platform(),
        "bindings": bindings,
        "import_errors": import_errors,
        "libraries": libraries,
        "native": native_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    output = json.dumps(collect_report(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
