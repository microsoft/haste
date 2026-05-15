# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Centralized allowlist for outbound imagery source URLs.

Used by both the ImageryDownloader (defense-in-depth at fetch time) and the
PutLayer API handler (reject bad URLs at submission time, so users get
immediate feedback instead of failed batch jobs).
"""
from urllib.parse import urlparse

# Human-readable description used in user-facing error messages. Keep in
# sync with the JS allowlist in ui/src/util/validation.js.
ALLOWED_HOST_DESCRIPTION = (
    "Azure Blob Storage (*.blob.core.windows.net) "
    "or AWS S3 (*.amazonaws.com)"
)


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

    raise ValueError(
        f"URL host {host!r} is not on the allowlist of permitted imagery sources"
    )
