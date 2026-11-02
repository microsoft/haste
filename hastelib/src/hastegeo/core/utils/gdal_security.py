# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""GDAL/OGR hardening + ingestion-boundary helpers.

Compensating controls for the deferred GDAL 3.9.2 dependency exception
(see ``docs/known-vulnerabilities.md`` Root Cause C and
``spec/architecture/decisions/0004-gdal-driver-allowlist.md``).

GDAL 3.9.2 carries unpatched memory-safety CVEs, the worst a heap overflow
in the HDF4/HDF-EOS driver (CVE-2026-8087). Because GDAL dispatches by
*sniffing file content* — not the extension — an extension check alone is
bypassable. The primary control is therefore to register only the drivers
HASTE actually uses and **deregister everything else at process startup**,
so a malicious HDF4/HDF5/netCDF file can never be dispatched to the
vulnerable parser by any ``gdal.Open`` / ``rasterio.open`` / ``pyogrio``
read in this process. A ``GDAL_SKIP`` denylist env complements this for
subprocess GDAL CLI tools (``gdalwarp``/``gdal_translate``), where only a
denylist is expressible.

This module is import-safe without GDAL: the pure-Python helpers
(``sniff_file_type``, the size/format helpers) work on any host, and only
:func:`harden_gdal` needs ``osgeo``.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Driver allowlist (audited against every gdal.Open/rasterio/pyogrio/
# fiona read+write in hastegeo + docker/training/code). GPKG is a unified
# raster+vector driver, so the union is what we keep. ────────────────────
ALLOWED_RASTER_DRIVERS = frozenset(
    {"GTiff", "COG", "VRT", "JPEG", "PNG", "MEM"}
)
ALLOWED_VECTOR_DRIVERS = frozenset({"GPKG", "GeoJSON", "Memory"})

# Denylist for the GDAL_SKIP env (subprocess CLI + any fresh registration).
# These are the CVE-relevant driver families; an allowlist can't be
# expressed via GDAL_SKIP, so we skip the known-dangerous ones explicitly.
DISABLED_DRIVERS_ENV = "HDF4 HDF4Image HDF5 HDF5Image netCDF"
LEGACY_REQUIRED_CONFIG = {
    "GDAL_VRT_ENABLE_RAWRASTERBAND": "NO",
    "GDAL_VRT_ENABLE_PYTHON": "NO",
    "GDAL_DRIVER_PATH": "disable",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED": "NO",
}

# ── Ingestion size caps (env-tunable; generous because satellite COGs are
# legitimately large — the goal is to bound pathological/hostile inputs). ─
_DEFAULT_MAX_UPLOAD_BYTES = 5 * 1024**3
_DEFAULT_MAX_DOWNLOAD_BYTES = 8 * 1024**3

# Declared chunked-upload formats → the content type we expect to sniff.
_FORMAT_TO_SNIFF = {
    "tif": "tiff",
    "tiff": "tiff",
    "geotiff": "tiff",
    "gpkg": "gpkg",
}

_hardened = False


def _harden_legacy_gdal() -> bool:
    for key, expected in LEGACY_REQUIRED_CONFIG.items():
        os.environ.setdefault(key, expected)
        actual = os.environ[key].strip()
        if actual.casefold() != expected.casefold():
            raise RuntimeError(
                f"{key}={actual!r} weakens GDAL hardening; "
                f"expected {expected!r}"
            )

    forbidden = {
        "GDAL_VRT_RAWRASTERBAND_ALLOWED_SOURCE": "ALL",
        "GDAL_VRT_PYTHON_TRUSTED_MODULES": None,
        "GDAL_PYTHON_DRIVER_PATH": None,
        "GDAL_HTTP_UNSAFESSL": "YES",
    }
    for key, forbidden_value in forbidden.items():
        actual = os.environ.get(key)
        if actual is None:
            continue
        if forbidden_value is None and actual.strip():
            raise RuntimeError(f"{key} must be unset for GDAL hardening")
        if (
            forbidden_value
            and actual.strip().casefold() == forbidden_value.casefold()
        ):
            raise RuntimeError(f"{key}={actual!r} weakens GDAL hardening")

    existing_skip = [
        name
        for name in re.split(
            r"[,\s]+", os.environ.get("GDAL_SKIP", "").strip()
        )
        if name
    ]
    required_skip = DISABLED_DRIVERS_ENV.split()
    os.environ["GDAL_SKIP"] = " ".join(
        dict.fromkeys([*existing_skip, *required_skip])
    )

    try:
        from osgeo import gdal, ogr
    except ModuleNotFoundError as exc:
        if exc.name != "osgeo":
            raise
        logger.warning(
            "osgeo (GDAL) not importable; skipping legacy hardening"
        )
        return False

    gdal.UseExceptions()
    ogr.UseExceptions()
    gdal.SetConfigOption("GDAL_SKIP", os.environ["GDAL_SKIP"])

    allowed = ALLOWED_RASTER_DRIVERS | ALLOWED_VECTOR_DRIVERS
    removed = _deregister_disallowed_legacy_drivers(gdal, allowed)

    logger.info(
        "harden_gdal: disabled %d legacy GDAL/OGR drivers; kept %s; "
        "GDAL_SKIP=%r",
        len(removed),
        sorted(allowed),
        os.environ.get("GDAL_SKIP"),
    )
    logger.debug("harden_gdal: disabled legacy drivers: %s", sorted(removed))
    return True


def _deregister_disallowed_legacy_drivers(
    gdal: Any, allowed: frozenset[str]
) -> list[str]:
    def registered_drivers() -> list[Any]:
        drivers = []
        for index in range(gdal.GetDriverCount()):
            driver = gdal.GetDriver(index)
            if driver is not None:
                drivers.append(driver)
        return drivers

    removed = []
    for driver in registered_drivers():
        name = driver.ShortName
        if name not in allowed:
            try:
                driver.Deregister()
            except Exception as exc:
                raise RuntimeError(
                    f"failed to deregister disallowed GDAL driver {name}"
                ) from exc
            removed.append(name)

    remaining = sorted(
        driver.ShortName
        for driver in registered_drivers()
        if driver.ShortName not in allowed
    )
    if remaining:
        raise RuntimeError(
            "disallowed GDAL drivers remain registered: "
            + ", ".join(remaining)
        )
    return removed


def harden_gdal(
    *, force: bool = False, require_runtime: bool | None = None
) -> None:
    """Restrict GDAL/OGR to :data:`ALLOWED_RASTER_DRIVERS` +
    :data:`ALLOWED_VECTOR_DRIVERS` by deregistering every other driver.

    Idempotent: a no-op after the first successful run unless ``force`` is
    set. When the shared runtime is installed, verify it before importing
    any GDAL binding. Set ``require_runtime`` or the
    HASTE_GDAL_RUNTIME_REQUIRED environment variable to fail closed if the
    shared runtime is missing.
    """
    global _hardened
    if _hardened and not force:
        return

    if require_runtime is None:
        value = (
            os.environ.get("HASTE_GDAL_RUNTIME_REQUIRED", "").strip().lower()
        )
        if value in {"1", "true", "yes"}:
            require_runtime = True
        elif value in {"", "0", "false", "no"}:
            require_runtime = False
        else:
            raise ValueError(
                "HASTE_GDAL_RUNTIME_REQUIRED must be a boolean value"
            )

    if importlib.util.find_spec("haste_gdal_runtime") is None:
        if require_runtime:
            raise RuntimeError(
                "HASTE_GDAL_RUNTIME_REQUIRED is set but "
                "haste-gdal-runtime is not installed"
            )
        logger.warning(
            "haste-gdal-runtime is absent; applying legacy GDAL hardening"
        )
        if _harden_legacy_gdal():
            _hardened = True
        return

    runtime = importlib.import_module("haste_gdal_runtime")
    manifest = runtime.load_manifest()
    expected_gdal = manifest.get("gdal_release")
    if not isinstance(expected_gdal, str) or not expected_gdal:
        raise RuntimeError("GDAL runtime manifest has no GDAL release")
    policy = runtime.Policy(
        expected_gdal=expected_gdal,
        allowed_drivers=ALLOWED_RASTER_DRIVERS | ALLOWED_VECTOR_DRIVERS,
        required_bindings=("osgeo.gdal",),
    )
    runtime.configure(policy)
    report = runtime.secure_startup(policy)
    for binding in ("osgeo.gdal", "osgeo.ogr"):
        importlib.import_module(binding).UseExceptions()
    logger.info("verified HASTE GDAL runtime: %s", report)
    _hardened = True


def sniff_file_type(path: str) -> str | None:
    """Return a coarse content type from the file's magic bytes.

    One of ``"tiff"`` (incl. BigTIFF / GeoTIFF / COG), ``"gpkg"``,
    ``"sqlite"`` (SQLite that is not a GeoPackage), ``"png"``, ``"jpeg"``,
    ``"geojson"`` (JSON-looking text), or ``None`` if unrecognized.
    """
    try:
        with open(path, "rb") as fh:
            head = fh.read(72)
    except OSError:
        return None

    return _sniff_file_header(head)


def _sniff_file_header(head: bytes) -> str | None:
    if len(head) < 4:
        return None

    magic4 = head[:4]
    # TIFF (II*\0 / MM\0*) and BigTIFF (II+\0 / MM\0+). GeoTIFF + COG are
    # TIFF-based, so they all classify as "tiff".
    if magic4 in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "tiff"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:16] == b"SQLite format 3\x00":
        # GeoPackage application_id lives big-endian at byte offset 68.
        appid = head[68:72] if len(head) >= 72 else b""
        if appid in (b"GPKG", b"GP10"):
            return "gpkg"
        return "sqlite"
    stripped = head.lstrip()
    if stripped[:1] in (b"{", b"["):
        return "geojson"
    return None


def assert_matches_declared_bytes(data: bytes, declared: str) -> None:
    """Validate an upload's first chunk before it is persisted.

    GeoPackage detection needs its application identifier at byte offset 68,
    so the first chunk must contain at least 72 bytes.
    """
    norm = assert_allowed_upload_format(declared)
    expected = _FORMAT_TO_SNIFF[norm]
    if expected == "gpkg" and len(data) < 72:
        raise ValueError(
            "First upload chunk must contain at least 72 bytes to validate "
            "GeoPackage content."
        )
    actual = _sniff_file_header(data[:72])
    if actual != expected:
        raise ValueError(
            f"Uploaded file content ({actual!r}) does not match the "
            f"declared format {declared!r} (expected {expected!r})."
        )


def assert_allowed_upload_format(declared: str) -> str:
    """Normalize and validate a declared chunked-upload format.

    Returns the normalized lowercase format. Raises ``ValueError`` for
    anything outside the allowlist (``tif``/``tiff``/``geotiff``/``gpkg``).
    """
    norm = (declared or "").strip().lower()
    if norm not in _FORMAT_TO_SNIFF:
        raise ValueError(f"Unsupported upload format: {declared!r}")
    return norm


def assert_matches_declared(path: str, declared: str) -> None:
    """Reject a file whose actual content does not match ``declared``.

    Defense against a hostile client uploading e.g. an HDF4 file with a
    ``.tif`` extension/``data_format`` so it reaches the vulnerable GDAL
    parser. Raises ``ValueError`` on mismatch.
    """
    norm = assert_allowed_upload_format(declared)
    expected = _FORMAT_TO_SNIFF[norm]
    actual = sniff_file_type(path)
    if actual != expected:
        raise ValueError(
            f"Uploaded file content ({actual!r}) does not match the "
            f"declared format {declared!r} (expected {expected!r})."
        )


# Named to match the `_get_*env` typed-wrapper convention (see
# `_get_bounded_int_env` in hastegeo.core.config): the env-drift check in
# .github/scripts/check_env_drift.py only recognises readers on that shape,
# and reports the setting as dead config otherwise.
def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def max_upload_bytes() -> int:
    """Max assembled chunked-upload size (``HASTE_MAX_UPLOAD_BYTES``)."""
    return _get_int_env("HASTE_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES)


def max_download_bytes() -> int:
    """Max remote imagery fetch size
    (``HASTE_MAX_IMAGERY_DOWNLOAD_BYTES``)."""
    return _get_int_env(
        "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES", _DEFAULT_MAX_DOWNLOAD_BYTES
    )
