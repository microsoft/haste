# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Small blob-storage helpers used by API and worker code.

These exist because the Azure SDK's :func:`azure.storage.blob.BlobClient.from_blob_url`
only recognizes hosts matching ``*.blob.core.windows.net``, ``localhost``,
and ``127.0.0.1``. For the docker-internal Azurite host name (``azurite``,
which is what ``BLOB_CONNECTION_STRING`` resolves to inside the function-app
container in our dev compose), the SDK falls into a wrong-shape parse that
treats the second-to-last path segment as the container name and downloads
produce ``ContainerNotFound``.

The helpers in this module sidestep that by detecting URL shape from the
host themselves, then routing the actual download through a function-app-
internal ``BlobServiceClient`` so requests stay on the docker network in
dev (and on the Azure backbone in prod).
"""

from __future__ import annotations

import asyncio
import functools
import os
import re
import tempfile
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

_USER_DELEGATION_KEYS = OrderedDict()
_USER_DELEGATION_KEY_CACHE_SIZE = 8
_USER_DELEGATION_KEYS_LOCK = threading.Lock()


@functools.lru_cache(maxsize=8)
def get_blob_service_client(
    connection_string: str | None = None,
    account_url: str | None = None,
):
    """Return a process-wide ``BlobServiceClient`` for one storage account.

    Azure SDK clients are thread-safe and designed for reuse; creating one per
    call re-parses credentials and re-establishes the connection pool. Caching
    by credential target keeps that setup cost one-time per process.
    """
    from azure.storage.blob import BlobServiceClient

    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)
    if account_url:
        from azure.identity import DefaultAzureCredential

        return BlobServiceClient(
            account_url=account_url, credential=DefaultAzureCredential()
        )
    raise ValueError("A connection string or account URL is required")


def get_app_blob_service_client():
    """Return the shared client for the app's own storage account.

    ``BLOB_CONNECTION_STRING`` wins when set because the docker dev stack
    points it at the emulator. In Azure it is absent and the app's managed
    identity is used through ``BLOB_ACCOUNT_URL``.

    Raises:
        ValueError: If neither setting exists, so the error names both.
    """
    connection_string = os.environ.get("BLOB_CONNECTION_STRING", "")
    account_url = os.environ.get("BLOB_ACCOUNT_URL", "")
    if not connection_string and not account_url:
        raise ValueError(
            "Neither BLOB_CONNECTION_STRING nor BLOB_ACCOUNT_URL is set; "
            "cannot reach blob storage."
        )
    return get_blob_service_client(
        connection_string=connection_string or None,
        account_url=account_url or None,
    )


def get_cached_user_delegation_key(
    blob_service_client,
    now: datetime | None = None,
    min_remaining: timedelta = timedelta(minutes=15),
):
    """Return a reusable user-delegation key with a safe refresh margin.

    ``min_remaining`` is how long the key must still be valid; callers that
    sign a token must pass at least that token's lifetime.
    """
    current_time = now or datetime.now(timezone.utc)
    cache_key = blob_service_client
    with _USER_DELEGATION_KEYS_LOCK:
        cached = _USER_DELEGATION_KEYS.get(cache_key)
        if cached is not None:
            delegation_key, expires_at = cached
            if expires_at > current_time + min_remaining:
                _USER_DELEGATION_KEYS.move_to_end(cache_key)
                return delegation_key

        expires_at = current_time + timedelta(hours=2)
        delegation_key = blob_service_client.get_user_delegation_key(
            current_time - timedelta(minutes=5), expires_at
        )
        _USER_DELEGATION_KEYS[cache_key] = (delegation_key, expires_at)
        _USER_DELEGATION_KEYS.move_to_end(cache_key)
        while len(_USER_DELEGATION_KEYS) > _USER_DELEGATION_KEY_CACHE_SIZE:
            _USER_DELEGATION_KEYS.popitem(last=False)
        return delegation_key


def clear_blob_client_caches() -> None:
    """Clear cached Blob clients and delegation keys for isolated tests."""
    get_blob_service_client.cache_clear()
    with _USER_DELEGATION_KEYS_LOCK:
        _USER_DELEGATION_KEYS.clear()


def split_blob_url(url: str) -> Tuple[str, str]:
    """Extract ``(container_name, blob_name)`` from a blob URL.

    Handles both real-Azure URLs (``https://<account>.blob.core.windows.net
    /<container>/<blob>?<sas>``) and Azurite path-style URLs
    (``http://<host>:<port>/<account>/<container>/<blob>?<sas>``), including
    the docker-internal ``http://azurite:10000/...`` form.

    Detection: any host outside ``*.blob.core.windows.net`` is treated as
    Azurite-style and the first path segment is consumed as the account
    name. This matches the URLs ``MetadataProcessor`` produces in both
    dev (azurite:10000 / devstoreaccount1) and prod (Azure Blob).

    Raises:
        ValueError: when the URL has too few path segments to extract
            container and blob.
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    host = (parsed.hostname or "").lower()
    if host.endswith(".blob.core.windows.net"):
        # Real Azure: /<container>/<blob...>
        if len(parts) < 2:
            raise ValueError(f"Blob URL missing container/blob: {url}")
        return parts[0], "/".join(parts[1:])
    # Azurite path-style: /<account>/<container>/<blob...>
    if len(parts) < 3:
        raise ValueError(
            f"Azurite-style blob URL missing account/container/blob: {url}"
        )
    return parts[1], "/".join(parts[2:])


def fetch_url_text(
    url: Optional[str], timeout: int = 30, *, strict: bool = False
) -> Optional[str]:
    """Return the text body at ``url``, or ``None`` if it cannot be read.

    Used to recover a task's output files from the copy Azure Batch uploaded to
    blob storage when the compute node that ran the task is no longer able to
    serve them. By default this is best effort: transport and HTTP errors
    return ``None``, preserving the behavior of existing optional readers.

    With ``strict=True``, HTTP 404 still returns ``None``, but all other
    HTTP/transport or unexpected errors propagate. Required-output readers
    can then distinguish a missing file from a failed retrieval and retry.
    Callers must sanitize exceptions before logging: requests errors may
    contain the URL, including SAS credentials.

    Only ``http(s)`` locations are fetched; a data layer that resolves to a
    local filesystem path (the docker dev stack) returns ``None``.
    """
    if not url or not urlparse(url).scheme.startswith("http"):
        return None
    # Imported lazily to keep this module cheap for callers that only need
    # split_blob_url().
    import requests

    try:
        response = requests.get(url, timeout=timeout)
        if strict and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    except Exception:
        if strict:
            raise
        return None


async def download_blob_to_tempfile(
    url: str,
    suffix: str = "",
    max_bytes: Optional[int] = None,
) -> str:
    """Download the blob at ``url`` to a NamedTemporaryFile and return the path.

    Routes the download through the function app's own credential (see
    :func:`get_app_blob_service_client`) regardless of the container/blob URL
    the caller hands in. The caller is responsible for unlinking the returned
    path when done — use ``try/finally``.
    """
    container_name, blob_name = split_blob_url(url)
    bsc = get_app_blob_service_client()
    if max_bytes is not None and max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    def download() -> str:
        blob_client = bsc.get_container_client(container_name).get_blob_client(
            blob_name
        )
        if max_bytes is not None:
            size = blob_client.get_blob_properties().size
            if size > max_bytes:
                raise ValueError("Blob exceeds the allowed download size")

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False
            ) as temp_file:
                temp_path = temp_file.name
                downloaded_bytes = 0
                for chunk in blob_client.download_blob().chunks():
                    downloaded_bytes += len(chunk)
                    if max_bytes is not None and downloaded_bytes > max_bytes:
                        raise ValueError(
                            "Blob exceeds the allowed download size"
                        )
                    temp_file.write(chunk)
            return temp_path
        except Exception:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise

    return await asyncio.to_thread(download)


def blob_url_without_query(url: Optional[str]) -> Optional[str]:
    """Return ``url`` without its query string, or ``None`` for a falsy url.

    Stored blob URLs are kept unsigned: tokens are short-lived and minted
    when a URL is handed out.
    """
    if not url:
        return None
    return url.split("?", 1)[0]


def _internal_blob_client(url: str):
    """Return the app's blob client when ``url`` points at its own storage."""
    if not (
        os.environ.get("BLOB_CONNECTION_STRING")
        or os.environ.get("BLOB_ACCOUNT_URL")
    ):
        return None
    candidate = urlparse(url)
    if candidate.scheme not in {"http", "https"} or not candidate.hostname:
        return None
    client = get_app_blob_service_client()
    account = urlparse(client.url)
    if (candidate.scheme, candidate.hostname.lower(), candidate.port) != (
        account.scheme,
        (account.hostname or "").lower(),
        account.port,
    ):
        return None
    return client


def sign_internal_blob_url(url: Optional[str], minutes: int = 60):
    """Return ``url`` with a fresh read-only token when it is internal.

    Only blobs in the app's own storage account and ``BLOB_CONTAINER`` are
    signed, with any old query replaced by a token scoped to that one blob.
    Anything else (provider URLs, other accounts or containers) is returned
    untouched. An account key (Azurite, dev) signs directly; otherwise the
    app identity's cached user delegation key does.
    """
    if not url:
        return url
    client = _internal_blob_client(url)
    if client is None:
        return url
    from .blob_sas import DELEGATION_KEY_MARGIN, blob_read_sas

    container_name, blob_name = split_blob_url(blob_url_without_query(url))
    if container_name != os.environ.get("BLOB_CONTAINER", "data"):
        return url
    blob_name = unquote(blob_name)
    credential = getattr(client, "credential", None)
    account_key = getattr(credential, "account_key", None)
    user_delegation_key = None
    if not account_key:
        user_delegation_key = get_cached_user_delegation_key(
            client, min_remaining=DELEGATION_KEY_MARGIN
        )
    token = blob_read_sas(
        account_name=client.account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        user_delegation_key=user_delegation_key,
        minutes=minutes,
    )
    blob_url = client.get_blob_client(container_name, blob_name).url
    return f"{blob_url}?{token}"


_TILE_SOURCE_PARAM = re.compile(r"(?<=[?&]url=)[^&#]*")


def sign_titiler_tile_url(tile_url: Optional[str]) -> Optional[str]:
    """Sign the blob URL nested in a TiTiler tile URL's ``url`` parameter."""
    if not tile_url:
        return tile_url

    def _sign(match: re.Match) -> str:
        source = unquote(match.group(0))
        signed = sign_internal_blob_url(source)
        return quote(signed, safe="") if signed != source else match.group(0)

    return _TILE_SOURCE_PARAM.sub(_sign, tile_url)


_LABEL_TILE_FIELDS = ("tileUrl", "preEventTileUrl", "postEventTileUrl")
_PREVIEW_FIELDS = ("preEventPreviewUrls", "postEventPreviewUrls")
_LAYER_DOWNLOAD_FIELDS = ("labelsUrl",)
_MODEL_DOWNLOAD_FIELDS = ("labelsUrl", "trainingZipUrl", "inferenceZipUrl")


def sign_project_details_urls(project: dict) -> dict:
    """Sign blob URLs in a project-details dict in place and return it.

    Covers layer previews and label downloads, and each model's label and
    zip downloads. Stored values are never written back; callers sign the
    response copy only.
    """
    for layer in project.get("imageLayer") or []:
        for field in _PREVIEW_FIELDS:
            if layer.get(field):
                layer[field] = [
                    sign_internal_blob_url(url) for url in layer[field]
                ]
        for field in _LAYER_DOWNLOAD_FIELDS:
            if layer.get(field):
                layer[field] = sign_internal_blob_url(layer[field])
        for model in layer.get("models") or []:
            for field in _MODEL_DOWNLOAD_FIELDS:
                if model.get(field):
                    model[field] = sign_internal_blob_url(model[field])
    return project


def sign_label_project_urls(label_project: dict) -> dict:
    """Return a copy of a label project with its tile URLs freshly signed."""
    imagery = label_project.get("imagery")
    if not isinstance(imagery, dict):
        return label_project
    signed = dict(imagery)
    for field in _LABEL_TILE_FIELDS:
        if signed.get(field):
            signed[field] = sign_titiler_tile_url(signed[field])
    return {**label_project, "imagery": signed}


class BlobRange(NamedTuple):
    """A slice of a blob plus the metadata needed to build HTTP headers."""

    data: bytes
    total_size: int
    content_type: str
    etag: Optional[str]


def parse_byte_range(
    value: Optional[str],
) -> Tuple[int, Optional[int], bool]:
    """Parse a single HTTP ``Range`` header of the form ``bytes=start-end``.

    Returns ``(offset, length, is_range)``. ``length`` is ``None`` for an
    open-ended ``bytes=start-`` range (read to EOF); ``is_range`` is
    ``False`` when no Range header is present.

    Raises:
        ValueError: for suffix ranges (``bytes=-N``), multi-range values,
            or otherwise malformed syntax. The caller decides how to reject
            unsupported ranges; PMTiles must not fall back to a full download.
    """
    if not value:
        return 0, None, False
    match = re.match(r"^bytes=(\d*)-(\d*)$", value.strip())
    if not match:
        raise ValueError(f"Unsupported Range header: {value!r}")
    start_s, end_s = match.group(1), match.group(2)
    if start_s == "":
        # Suffix range (last N bytes) — not emitted by pmtiles.js.
        raise ValueError(f"Suffix Range unsupported: {value!r}")
    offset = int(start_s)
    if end_s == "":
        return offset, None, True
    end = int(end_s)
    if end < offset:
        raise ValueError(f"Invalid Range bounds: {value!r}")
    return offset, end - offset + 1, True


async def read_blob_range(
    url: str, offset: int = 0, length: Optional[int] = None
) -> BlobRange:
    """Read ``length`` bytes from ``offset`` of the blob at ``url``.

    Routes the read through the function app's own credential (see
    :func:`get_app_blob_service_client`); only the container/blob path is
    taken from ``url`` — its host and SAS are ignored. ``length=None``
    reads to EOF. ``data`` is clamped to the blob size; an ``offset`` at
    or past EOF yields empty ``data`` (callers should answer ``416``).
    """
    container_name, blob_name = split_blob_url(url)

    def _read() -> BlobRange:
        bsc = get_app_blob_service_client()
        blob_client = bsc.get_container_client(container_name).get_blob_client(
            blob_name
        )
        props = blob_client.get_blob_properties()
        total = props.size or 0
        settings = props.content_settings
        content_type = (
            settings.content_type if settings else None
        ) or "application/octet-stream"
        if total == 0 or offset >= total:
            return BlobRange(b"", total, content_type, props.etag)
        if length is None:
            downloader = blob_client.download_blob(offset=offset)
        else:
            clamped = max(0, min(length, total - offset))
            downloader = blob_client.download_blob(
                offset=offset, length=clamped
            )
        return BlobRange(downloader.readall(), total, content_type, props.etag)

    return await asyncio.to_thread(_read)
