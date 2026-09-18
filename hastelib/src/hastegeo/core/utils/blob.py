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
from urllib.parse import urlparse

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


def get_cached_user_delegation_key(
    blob_service_client,
    now: datetime | None = None,
):
    """Return a reusable user-delegation key with a safe refresh margin."""
    current_time = now or datetime.now(timezone.utc)
    cache_key = blob_service_client
    with _USER_DELEGATION_KEYS_LOCK:
        cached = _USER_DELEGATION_KEYS.get(cache_key)
        if cached is not None:
            delegation_key, expires_at = cached
            if expires_at > current_time + timedelta(minutes=15):
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


def fetch_url_text(url: str, timeout: int = 30) -> Optional[str]:
    """Return the text body at ``url``, or ``None`` if it cannot be read.

    Used to recover a task's output files from the copy Azure Batch uploaded to
    blob storage when the compute node that ran the task is no longer able to
    serve them. Callers treat this as a best-effort fallback, so transport and
    HTTP errors are reported as ``None`` rather than raised — a failure here
    must never mask the original reason the node read failed.

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
        response.raise_for_status()
        return response.text
    except Exception:
        return None


async def download_blob_to_tempfile(
    url: str,
    suffix: str = "",
    max_bytes: Optional[int] = None,
) -> str:
    """Download the blob at ``url`` to a NamedTemporaryFile and return the path.

    Routes the download through the function-app-internal
    ``BLOB_CONNECTION_STRING`` (so requests stay on the docker network in
    dev) regardless of the container/blob URL the caller hands in. The
    caller is responsible for unlinking the returned path when done — use
    ``try/finally``.
    """
    conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
    container_name, blob_name = split_blob_url(url)
    bsc = get_blob_service_client(connection_string=conn_str)
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
            or otherwise malformed syntax. Callers should fall back to a
            full ``200`` response in that case.
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

    Routes the read through the function-app-internal
    ``BLOB_CONNECTION_STRING`` (so it stays on the docker network in dev
    and on the Azure backbone in prod); only the container/blob path is
    taken from ``url`` — its host and SAS are ignored. ``length=None``
    reads to EOF. ``data`` is clamped to the blob size; an ``offset`` at
    or past EOF yields empty ``data`` (callers should answer ``416``).
    """
    conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
    container_name, blob_name = split_blob_url(url)

    def _read() -> BlobRange:
        bsc = get_blob_service_client(connection_string=conn_str)
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
