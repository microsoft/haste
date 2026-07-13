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

import logging
import os

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


def harden_gdal(*, force: bool = False) -> None:
    """Restrict GDAL/OGR to :data:`ALLOWED_RASTER_DRIVERS` +
    :data:`ALLOWED_VECTOR_DRIVERS` by deregistering every other driver.

    Idempotent: a no-op after the first successful run unless ``force`` is
    set. Safe to call from many import sites. If ``osgeo`` is unavailable
    (e.g. a bare host running non-GDAL tests) it logs and returns without
    error.
    """
    global _hardened
    if _hardened and not force:
        return

    try:
        from osgeo import gdal, ogr
    except ImportError:
        logger.warning("osgeo (GDAL) not importable; skipping harden_gdal()")
        return

    gdal.UseExceptions()
    ogr.UseExceptions()

    # Belt-and-suspenders: make any later (re)registration or subprocess
    # honor the denylist too. Respect an operator-provided GDAL_SKIP.
    os.environ.setdefault("GDAL_SKIP", DISABLED_DRIVERS_ENV)
    gdal.SetConfigOption("GDAL_SKIP", os.environ["GDAL_SKIP"])

    allowed = ALLOWED_RASTER_DRIVERS | ALLOWED_VECTOR_DRIVERS

    # Collect first — deregistering mutates the driver manager and shifts
    # indices. In GDAL 3.x the manager is unified (one list for raster +
    # vector), so a single pass covers OGR drivers too.
    drivers = [
        gdal.GetDriver(i)
        for i in range(gdal.GetDriverCount())
        if gdal.GetDriver(i) is not None
    ]

    removed: list[str] = []
    for drv in drivers:
        name = drv.ShortName
        if name not in allowed:
            try:
                drv.Deregister()
                removed.append(name)
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    "harden_gdal: failed to deregister driver %s", name
                )

    _hardened = True
    logger.info(
        "harden_gdal: disabled %d GDAL/OGR drivers; kept %s; GDAL_SKIP=%r",
        len(removed),
        sorted(allowed),
        os.environ.get("GDAL_SKIP"),
    )
    logger.debug("harden_gdal: disabled drivers: %s", sorted(removed))


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


def _int_env(name: str, default: int) -> int:
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
    return _int_env("HASTE_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES)


def max_download_bytes() -> int:
    """Max remote imagery fetch size
    (``HASTE_MAX_IMAGERY_DOWNLOAD_BYTES``)."""
    return _int_env(
        "HASTE_MAX_IMAGERY_DOWNLOAD_BYTES", _DEFAULT_MAX_DOWNLOAD_BYTES
    )
