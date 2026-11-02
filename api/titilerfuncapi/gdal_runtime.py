"""Shared GDAL runtime initialization for the TiTiler Function App."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# rio-tiler reprojects through in-memory VRTs, so the driver stays registered.
# Raw bands and Python pixel functions are off, and user-supplied VRT content
# is refused before GDAL opens it.
ALLOWED_DRIVERS = frozenset({"GTiff", "COG", "JPEG", "PNG", "MEM", "VRT"})


def secure_gdal_runtime() -> dict[str, Any] | None:
    """Configure and verify the shared runtime before importing TiTiler."""
    required_value = (
        os.environ.get("HASTE_GDAL_RUNTIME_REQUIRED", "").strip().lower()
    )
    if required_value in {"1", "true", "yes"}:
        required = True
    elif required_value in {"", "0", "false", "no"}:
        required = False
    else:
        raise ValueError("HASTE_GDAL_RUNTIME_REQUIRED must be a boolean value")

    if importlib.util.find_spec("haste_gdal_runtime") is None:
        if required:
            raise RuntimeError(
                "HASTE_GDAL_RUNTIME_REQUIRED is set but "
                "haste-gdal-runtime is not installed"
            )
        logger.warning(
            "haste-gdal-runtime is absent; TiTiler is using its current "
            "GDAL installation"
        )
        return None

    runtime = importlib.import_module("haste_gdal_runtime")
    manifest = runtime.load_manifest()
    expected_gdal = manifest.get("gdal_release")
    if not isinstance(expected_gdal, str) or not expected_gdal:
        raise RuntimeError("GDAL runtime manifest has no GDAL release")
    policy = runtime.Policy(
        expected_gdal=expected_gdal,
        allowed_drivers=ALLOWED_DRIVERS,
        required_bindings=("rasterio",),
    )
    runtime.configure(policy)
    report = runtime.secure_startup(policy)
    logger.info("verified TiTiler GDAL runtime: %s", report)
    return report
