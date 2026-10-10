# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""GDAL configuration the tile server always runs with.

Applied to the process environment at import time (before rasterio
registers drivers on its first open) and again as the per-request GDAL
environment, so neither app settings nor a later config call can relax
them. Options a given GDAL build does not know are ignored by GDAL.
"""

import os

GDAL_HARDENING = {
    # No plugin drivers from disk.
    "GDAL_DRIVER_PATH": "disable",
    # Don't list or probe sibling files (.aux.xml, .ovr, .msk, ...).
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    # Don't read or write .aux.xml side-car metadata.
    "GDAL_PAM_ENABLED": "NO",
    # VRT pixel functions written in Python.
    "GDAL_VRT_ENABLE_PYTHON": "NO",
    # VRT bands backed by raw files (GDAL >= 3.12 honours this).
    "GDAL_VRT_ENABLE_RAWRASTERBAND": "NO",
    # Header files and netrc are local-file reads driven by config.
    "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED": "NO",
    "GDAL_HTTP_NETRC": "NO",
}

# Settings that would undo the above if present in the environment.
_UNSAFE = (
    "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE",
    "GDAL_VRT_PYTHON_TRUSTED_MODULES",
    "GDAL_HTTP_HEADER_FILE",
    "GDAL_HTTP_HEADERS",
    "GDAL_HTTP_COOKIEFILE",
    "GDAL_HTTP_UNSAFESSL",
)


def apply_gdal_hardening(environ=os.environ) -> None:
    """Force the hardening values into ``environ``."""
    for name in _UNSAFE:
        environ.pop(name, None)
    environ.update(GDAL_HARDENING)


def gdal_environment() -> dict:
    """Per-request GDAL options (TiTiler ``environment_dependency``)."""
    return dict(GDAL_HARDENING)
