# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Centralized allowlist for outbound imagery source URLs.

Used by both the ImageryDownloader (defense-in-depth at fetch time) and the
PutLayer API handler (reject bad URLs at submission time, so users get
immediate feedback instead of failed batch jobs).
"""
import logging
import os
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Human-readable description used in user-facing error messages. Keep in
# sync with the JS allowlist in ui/src/util/validation.js.
ALLOWED_HOST_DESCRIPTION = (
    "Azure Blob Storage (*.blob.core.windows.net), "
    "AWS S3 (*.amazonaws.com), "
    "or Source Cooperative (data.source.coop)"
)

# Building-footprint URLs additionally permit the host of the configured
# local upload endpoint (read from ``BLOB_ACCOUNT_URL``) so the URLs
# returned by the chunked file uploader work end-to-end in local dev.
# When ``BLOB_ACCOUNT_URL`` is unset, local hosts (azurite/localhost/
# 127.0.0.1) are rejected by default — operators must explicitly opt in
# via ``HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS=1`` to allow them. This is a
# deliberate SSRF guard: a misconfigured production deployment must not
# silently accept loopback URLs that the workflow then fetches.
FOOTPRINT_ALLOWED_HOST_DESCRIPTION = (
    f"{ALLOWED_HOST_DESCRIPTION} or the configured local upload host"
)

_AZURITE_DEV_HOSTS = ("azurite", "localhost", "127.0.0.1")


def validate_imagery_url(url: str) -> str:
    """Validate a remote imagery URL against the allowlist of permitted hosts.

    Returns a string identifying the source type ('azureblobstorage' or
    'awss3'). Raises ValueError if the URL is malformed or the host is not
    on the allowlist — callers must treat this as a hard rejection.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise ValueError("URL is missing host component")

    if host == "blob.core.windows.net" or host.endswith(
        ".blob.core.windows.net"
    ):
        return "azureblobstorage"

    if (
        host == "s3.amazonaws.com"
        or host.endswith(".s3.amazonaws.com")
        or host.endswith(".amazonaws.com")
    ):
        return "awss3"

    # Source Cooperative — Planet Open Data STAC catalogs and COGs surfaced
    # by the Open Data Catalog explorer are served from data.source.coop.
    # This is a public, well-known open-data host (not user-controlled),
    # so allowlisting it does not meaningfully widen SSRF exposure.
    if host == "data.source.coop" or host.endswith(".source.coop"):
        return "sourcecoop"

    raise ValueError(
        f"URL host {host!r} is not on the allowlist of permitted imagery sources"
    )


def _parse_local_upload_endpoint() -> tuple[str, str, int | None] | None:
    """Parse ``BLOB_ACCOUNT_URL`` into (scheme, hostname, port).

    Returns ``None`` if the env var is unset or unparseable. Used to
    exact-match local-dev upload URLs (e.g. ``http://azurite:10000/...``)
    so the chunked uploader output can flow through the footprint URL
    allowlist without opening a broader hole.
    """
    raw = os.environ.get("BLOB_ACCOUNT_URL")
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if not parsed.hostname or parsed.scheme not in ("http", "https"):
        return None
    return parsed.scheme, parsed.hostname.lower(), parsed.port


def validate_footprint_url(url: str) -> str:
    """Validate a user-supplied building-footprint URL.

    Permits the same hosts as :func:`validate_imagery_url` PLUS the host
    of the configured local upload endpoint (so URLs returned by the
    chunked uploader in dev work end-to-end). Returns a source-type label
    matching :func:`validate_imagery_url`'s vocabulary, plus the literal
    ``'localupload'`` for the configured-endpoint case.

    Raises ValueError on rejection — callers must treat this as a hard
    failure (just like :func:`validate_imagery_url`).

    Security note: when ``BLOB_ACCOUNT_URL`` is unset we deliberately do
    NOT fall back to allowing ``localhost``/``127.0.0.1``/``azurite``,
    because the workflow fetches these URLs server-side. A misconfigured
    production deployment without an explicit endpoint must reject all
    local hosts to avoid acting as an SSRF gadget against loopback or
    internal services. Operators who want the loopback fallback must
    explicitly opt in via ``HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS=1`` (the
    docker-compose dev stack sets this), and even then only the exact
    Azurite hosts are permitted — never arbitrary loopback addresses
    with arbitrary ports/paths.
    """
    try:
        return validate_imagery_url(url)
    except ValueError:
        # Fall through to the local-upload exception below; reraise if
        # nothing matches so the caller sees a single, consistent error.
        pass

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL is missing host component")

    endpoint = _parse_local_upload_endpoint()
    if endpoint is not None:
        e_scheme, e_host, e_port = endpoint
        if (
            parsed.scheme == e_scheme
            and host == e_host
            and (parsed.port or None) == e_port
        ):
            return "localupload"

    # Opt-in dev fallback: only allow conventional Azurite hostnames when
    # the operator has explicitly enabled it. Never enabled by default,
    # so a misconfigured production stack can't be tricked into SSRF
    # against loopback/internal services via this branch.
    if (
        os.environ.get("HASTE_ALLOW_LOCAL_FOOTPRINT_HOSTS", "").strip()
        in ("1", "true", "True", "yes")
        and host in _AZURITE_DEV_HOSTS
    ):
        return "localupload"

    raise ValueError(
        f"URL host {host!r} is not on the allowlist of permitted building-footprint sources"
    )


# ──────────────────────────────────────────────────────────────────────────
# ImageLayer-level convenience wrappers.
#
# These belong here (not in api/hastefuncapi/function_app.py) because they
# operate on an ImageLayer Pydantic model — not on a func.HttpRequest /
# HttpResponse — and AGENTS.md reserves function_app.py for top-level
# HTTP handlers only. PutLayer (and any future endpoint that needs to
# pre-validate a layer's URLs at submission time) imports from here.
#
# The ImageLayer type is referenced as a forward-string annotation to
# avoid pulling hastegeo.core.models.projects at import time (would create
# an import cycle: models.projects ← processors.imagery ← utils.url_allowlist).
# ──────────────────────────────────────────────────────────────────────────
def validate_image_layer_imagery_urls(image_layer) -> Optional[str]:
    """Validate the imagery URLs on an ImageLayer against the allowlist.

    Returns a user-facing error message if any URL is not on the
    allowlist, or ``None`` if all URLs validate. Full URLs are logged
    server-side via the module logger; only rejected hostnames are
    surfaced to the caller for use in HTTP responses.

    Args:
        image_layer: An ``ImageLayer`` Pydantic instance whose
            ``preEventImageryUrls`` / ``postEventImageryUrls`` to check.
    """
    rejected_hosts: list[str] = []
    for field_name in ("preEventImageryUrls", "postEventImageryUrls"):
        urls = getattr(image_layer, field_name, None) or []
        for idx, url in enumerate(urls):
            if not url:
                continue
            try:
                validate_imagery_url(url)
            except ValueError:
                host = urlparse(url).hostname or "<unparseable>"
                logger.warning(
                    "Rejected imagery URL not on allowlist: "
                    "field=%s index=%d host=%s",
                    field_name,
                    idx,
                    host,
                )
                rejected_hosts.append(host)
    if rejected_hosts:
        unique_hosts = sorted(set(rejected_hosts))
        return (
            "One or more imagery URLs are not on the allowlist of permitted "
            f"hosts ({ALLOWED_HOST_DESCRIPTION}). "
            f"Rejected host(s): {', '.join(unique_hosts)}."
        )
    return None


def validate_image_layer_user_footprints_url(image_layer) -> Optional[str]:
    """Validate the optional user-supplied building-footprint URL.

    Returns a user-facing error message if the URL is set but not on the
    footprint allowlist, or ``None`` otherwise. As with imagery URLs,
    the full URL is logged server-side and only the rejected hostname is
    surfaced to the caller.

    Args:
        image_layer: An ``ImageLayer`` Pydantic instance whose
            ``userBuildingFootprintsUrl`` to check.
    """
    url = getattr(image_layer, "userBuildingFootprintsUrl", None)
    if not url:
        return None
    try:
        validate_footprint_url(url)
    except ValueError:
        host = urlparse(url).hostname or "<unparseable>"
        logger.warning(
            "Rejected userBuildingFootprintsUrl not on allowlist: host=%s",
            host,
        )
        return (
            "The user-supplied building-footprints URL is not on the "
            f"allowlist of permitted hosts ({FOOTPRINT_ALLOWED_HOST_DESCRIPTION}). "
            f"Rejected host: {host}."
        )
    return None


def validate_clip_bbox(image_layer) -> Optional[str]:
    """Validate the optional server-side clip AOI on an ImageLayer.

    Returns a user-facing error message if ``clipBbox`` is set but malformed,
    or ``None`` when it is absent or valid. Expected shape:
    ``[west, south, east, north]`` in EPSG:4326 with ``west < east``,
    ``south < north`` and coordinates within valid lon/lat ranges. Callers
    (PutLayer) treat a non-None return as a hard 400.

    Lives here (not in utils/aoi.py) so the lightweight PutLayer validation
    path doesn't pull rasterio/GDAL into the API process just to bounds-check
    four numbers.
    """
    bbox = getattr(image_layer, "clipBbox", None)
    if bbox is None:
        return None
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return "clipBbox must be a [west, south, east, north] array."
    try:
        west, south, east, north = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return "clipBbox values must be numbers."
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        return "clipBbox longitudes must be within [-180, 180]."
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        return "clipBbox latitudes must be within [-90, 90]."
    if west >= east or south >= north:
        return "clipBbox must have west < east and south < north."
    return None
