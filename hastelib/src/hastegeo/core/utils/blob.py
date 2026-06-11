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
import os
import tempfile
from typing import Tuple
from urllib.parse import urlparse


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


async def download_blob_to_tempfile(url: str, suffix: str = "") -> str:
    """Download the blob at ``url`` to a NamedTemporaryFile and return the path.

    Routes the download through the function-app-internal
    ``BLOB_CONNECTION_STRING`` (so requests stay on the docker network in
    dev) regardless of the container/blob URL the caller hands in. The
    caller is responsible for unlinking the returned path when done — use
    ``try/finally``.
    """
    # Imported here so this module stays cheap to import for callers that
    # only need split_blob_url(): azure-storage-blob brings in tens of
    # transitive imports.
    from azure.storage.blob import BlobServiceClient

    conn_str = os.environ.get("BLOB_CONNECTION_STRING", "")
    container_name, blob_name = split_blob_url(url)
    bsc = BlobServiceClient.from_connection_string(conn_str)
    blob_bytes = await asyncio.to_thread(
        lambda: bsc.get_container_client(container_name)
        .get_blob_client(blob_name)
        .download_blob()
        .readall()
    )
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(blob_bytes)
        return tmp.name
