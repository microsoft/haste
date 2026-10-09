# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Validation of the dataset ``url`` callers pass to the tile server.

Every value accepted here is handed to rasterio/GDAL, which treats many
strings as something other than a remote file: inline XML (VRT), local
paths, ``/vsi*`` virtual file systems, archive members and so on. So the
policy is an allowlist, not a blocklist: only plain ``https://`` URLs on
an exact, configured host list get through, and anything ambiguous is
rejected before GDAL sees it.

This module is stdlib-only on purpose. The tile server does not depend on
hastegeo, and importing it here would load a second GDAL build into the
process.
"""

import ipaddress
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Mapping
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

# Public open-data hosts the Open Data Catalog explorer previews. Exact
# hostnames only: a wildcard such as *.amazonaws.com or
# *.blob.core.windows.net would admit buckets and accounts anyone can
# create and fill with whatever content they like.
DEFAULT_PUBLIC_HOSTS = frozenset(
    {
        "vantor-opendata.s3.amazonaws.com",
        "data.source.coop",
    }
)

# Comma-separated exact hostnames, e.g. the deployment's own blob endpoint.
# These may resolve to private addresses (private endpoints).
ALLOWED_HOSTS_ENV = "TITILER_ALLOWED_HOSTS"

# Comma-separated origins (scheme://host:port) accepted over plain http.
# Local docker-compose only (Azurite); deployments must never set it.
DEV_ORIGINS_ENV = "TITILER_DEV_ALLOWED_ORIGINS"

MAX_URL_LENGTH = 4096

USER_AGENT = "haste-titiler"

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)"
    r"(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
# Printable ASCII without space or backslash. Rejects control characters,
# whitespace, newlines and non-ASCII before any parsing happens.
_URL_CHARS_RE = re.compile(r"^[\x21-\x5b\x5d-\x7e]+$")


class DatasetUrlError(ValueError):
    """The dataset URL is not an approved source."""


@dataclass(frozen=True)
class DatasetUrlPolicy:
    """Which origins a dataset URL may point at."""

    public_hosts: frozenset = DEFAULT_PUBLIC_HOSTS
    configured_hosts: frozenset = frozenset()
    dev_origins: frozenset = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ):
        configured = frozenset(
            _parse_host(h) for h in _split(env.get(ALLOWED_HOSTS_ENV, ""))
        )
        dev = frozenset(
            _parse_dev_origin(o) for o in _split(env.get(DEV_ORIGINS_ENV, ""))
        )
        return cls(configured_hosts=configured, dev_origins=dev)

    def allows_private_addresses(self, host: str) -> bool:
        """Only operator-configured hosts may sit behind private endpoints."""
        return host in self.configured_hosts or any(
            host == origin[1] for origin in self.dev_origins
        )


def _split(raw: str) -> list:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_host(raw: str) -> str:
    host = raw.lower()
    if not _HOSTNAME_RE.match(host) or _is_ip_literal(host):
        raise ValueError(f"{ALLOWED_HOSTS_ENV}: invalid hostname {raw!r}")
    return host


def _parse_dev_origin(raw: str) -> tuple:
    parts = urlsplit(raw)
    if parts.scheme != "http" or not parts.port or parts.path not in ("", "/"):
        raise ValueError(f"{DEV_ORIGINS_ENV}: expected http://host:port")
    return ("http", parts.hostname, parts.port)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def validate_dataset_url(url: str, policy: DatasetUrlPolicy) -> str:
    """Return ``url`` unchanged if it is an approved dataset reference.

    Raises DatasetUrlError otherwise. The URL is never rewritten: SAS
    signatures cover the exact string.
    """
    if not isinstance(url, str) or not url:
        raise DatasetUrlError("empty url")
    if len(url) > MAX_URL_LENGTH:
        raise DatasetUrlError("url too long")
    if not _URL_CHARS_RE.match(url):
        raise DatasetUrlError("url contains disallowed characters")

    if url.startswith("https://"):
        scheme = "https"
    elif url.startswith("http://") and policy.dev_origins:
        scheme = "http"
    else:
        # Covers inline XML, local and relative paths, file:, /vsi*,
        # rasterio's zip+https:// style schemes and upper-case variants.
        raise DatasetUrlError("unsupported url scheme")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise DatasetUrlError("malformed url") from exc

    netloc = parts.netloc
    if "@" in netloc:
        raise DatasetUrlError("credentials in url")
    if parts.fragment or "#" in url:
        raise DatasetUrlError("fragment in url")

    host = netloc.rsplit(":", 1)[0] if port is not None else netloc
    if not _HOSTNAME_RE.match(host) or _is_ip_literal(host):
        raise DatasetUrlError("invalid host")

    if scheme == "https":
        if port is not None:
            raise DatasetUrlError("explicit port not allowed")
        if host not in policy.public_hosts | policy.configured_hosts:
            raise DatasetUrlError("host not allowed")
    elif (scheme, host, port) not in policy.dev_origins:
        raise DatasetUrlError("host not allowed")

    _validate_path(parts.path)
    return url


def _validate_path(path: str) -> None:
    if not path.startswith("/") or path == "/":
        raise DatasetUrlError("missing path")
    # Decode twice so double-encoded traversal (%252e%252e) is caught too.
    decoded = unquote(unquote(path))
    if "\\" in decoded or "\x00" in decoded:
        raise DatasetUrlError("disallowed characters in path")
    # GDAL/rasterio read "!" as an archive member separator.
    if "!" in decoded:
        raise DatasetUrlError("archive path not allowed")
    if any(seg in (".", "..") for seg in decoded.split("/")):
        raise DatasetUrlError("path traversal")


# --- Redirect / destination check --------------------------------------------
#
# GDAL follows HTTP redirects itself and has no switch to stop it, so before
# the first open of a URL we ask the origin directly and refuse anything
# that is not a plain 2xx. Approved hosts serve content directly; a redirect
# means something changed and is treated as hostile. The resolved addresses
# are checked as well, so an approved public name pointed at an internal
# address is refused. Passing results are cached per URL so tiles of the
# same dataset do not repeat the check.

_ALWAYS_BLOCKED_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "168.63.129.16/32",  # Azure platform (WireServer)
        "169.254.0.0/16",  # link-local, includes IMDS
        "::/128",
        "fe80::/10",
    )
)


def check_destination_addresses(
    host: str,
    port: int,
    allow_private: bool,
    resolver: Callable = socket.getaddrinfo,
) -> None:
    """Fail closed unless every address ``host`` resolves to is acceptable."""
    try:
        infos = resolver(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DatasetUrlError("host does not resolve") from exc
    if not infos:
        raise DatasetUrlError("host does not resolve")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        if (
            addr.is_loopback
            or addr.is_multicast
            or addr.is_unspecified
            or addr.is_reserved
            or any(addr in net for net in _ALWAYS_BLOCKED_NETS)
        ):
            raise DatasetUrlError("host resolves to a blocked address")
        if addr.is_private and not allow_private:
            raise DatasetUrlError("host resolves to a private address")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


@dataclass
class DestinationChecker:
    """Preflight an approved URL once, then remember the result."""

    policy: DatasetUrlPolicy
    ttl_seconds: float = 600.0
    max_entries: int = 4096
    timeout_seconds: float = 10.0
    resolver: Callable = socket.getaddrinfo
    opener: urllib.request.OpenerDirector = _opener
    clock: Callable = time.monotonic
    _cache: OrderedDict = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, url: str) -> None:
        now = self.clock()
        with self._lock:
            expires = self._cache.get(url)
            if expires is not None and expires > now:
                self._cache.move_to_end(url)
                return

        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        check_destination_addresses(
            host,
            port,
            self.policy.allows_private_addresses(host),
            resolver=self.resolver,
        )

        # Some CDNs (Source Cooperative's among them) reject urllib's default
        # User-Agent with 403.
        request = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": USER_AGENT}
        )
        try:
            with self.opener.open(
                request, timeout=self.timeout_seconds
            ) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except (urllib.error.URLError, OSError) as exc:
            raise DatasetUrlError("dataset unreachable") from exc

        if 300 <= status < 400:
            raise DatasetUrlError("dataset url redirects")
        if not 200 <= status < 300:
            raise DatasetUrlError(f"dataset returned HTTP {status}")

        with self._lock:
            self._cache[url] = now + self.ttl_seconds
            self._cache.move_to_end(url)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)
