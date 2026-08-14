"""Minimal, hardened REST client for the Planetary Computer Pro GeoCatalog.

Adapted from the AI for Good Lab ``pcpublish`` reference client, trimmed to the
calls the publishing transport needs and hardened for server-side use:

- Entra ID auth via ``DefaultAzureCredential`` (scope
  ``https://geocatalog.spatio.azure.com/.default``), token cached with an expiry
  skew. ``azure-identity`` is imported lazily so importing this module does not
  require the ``planetary-computer`` extra.
- Redirects are never followed and every request carries explicit
  (connect, read) timeouts — the caller pins operation URLs to the GeoCatalog
  origin (see the transport adapter), so redirect-following would be an SSRF
  vector.
- ``GeoCatalogError`` never embeds server response bodies (the ``pcpublish``
  reference does); it carries only a sanitized message and the HTTP status.

This client returns raw ``requests.Response`` objects; the transport adapter
converts the async 202 + operation-location flow into resumable steps.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Optional

import requests

# Redact anything URL- or credential-like before surfacing a server error body.
_REDACT_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_REDACT_TOKEN_RE = re.compile(
    r"(?i)\b(sig|se|sv|sp|st|sr|skoid|sig|token|bearer|authorization)"
    r"[=:]\s*[^&\s\"']+"
)


def _safe_error_detail(response: requests.Response) -> str:
    """A short, URL/token-redacted snippet of a server error body."""
    try:
        text = response.text or ""
    except Exception:
        return ""
    text = _REDACT_TOKEN_RE.sub(r"\1=[redacted]", text)
    text = _REDACT_URL_RE.sub("[url]", text)
    text = " ".join(text.split())
    if not text:
        return ""
    if len(text) > 400:
        text = text[:400] + "…"
    return f": {text}"

API_VERSION = "2026-04-15"
_TOKEN_SCOPE = "https://geocatalog.spatio.azure.com/.default"
# Refresh a little before expiry so long ingestions do not fail mid-flight.
_EXPIRY_SKEW_SECONDS = 300


class GeoCatalogError(RuntimeError):
    """Raised when the GeoCatalog API returns an unexpected response.

    Carries the HTTP status code plus a short, URL/token-redacted snippet of the
    server error body (via ``_safe_error_detail``) so validation failures are
    diagnosable without leaking tokens/SAS present in error bodies.
    """

    def __init__(
        self, message: str, *, status_code: Optional[int] = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


class GeoCatalogAuth:
    """Caches an Entra ID access token for the GeoCatalog data plane."""

    def __init__(self, credential: Any = None) -> None:
        self._credential = credential
        self._token: Optional[str] = None
        self._expires_on: float = 0.0

    def token(self) -> str:
        now = time.time()
        if self._token and now < self._expires_on - _EXPIRY_SKEW_SECONDS:
            return self._token
        credential = self._credential or self._default_credential()
        self._credential = credential
        access_token = credential.get_token(_TOKEN_SCOPE)
        self._token = access_token.token
        self._expires_on = float(access_token.expires_on)
        return self._token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    @staticmethod
    def _default_credential() -> Any:
        # DefaultAzureCredential already chains managed identity, env, and the
        # az CLI, so no separate CLI-subprocess fallback is needed.
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()


class GeoCatalogClient:
    """Thin, hardened REST wrapper over the GeoCatalog STAC/ingestion APIs."""

    def __init__(
        self,
        endpoint: str,
        *,
        auth: Optional[GeoCatalogAuth] = None,
        api_version: str = API_VERSION,
        connection_timeout: int = 10,
        read_timeout: int = 30,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.auth = auth or GeoCatalogAuth()
        self.api_version = api_version
        self.timeout = (connection_timeout, read_timeout)
        self._session = requests.Session()
        # Never auto-follow redirects; operation URLs are origin-pinned by the
        # caller, and following a server-supplied redirect would defeat that.
        self._session.max_redirects = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        expected: Iterable[int] = (200, 201, 202, 204),
        absolute: bool = False,
    ) -> requests.Response:
        target = url if absolute else f"{self.endpoint}{url}"
        query = dict(params or {})
        # Absolute operation/continuation URLs already carry api-version in their
        # query string; adding it again would produce a duplicate parameter.
        if "api-version" not in query and "api-version=" not in target:
            query["api-version"] = self.api_version
        headers = self.auth.headers()
        try:
            response = self._session.request(
                method,
                target,
                params=query,
                json=json,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise GeoCatalogError(
                f"{method} request to GeoCatalog failed"
            ) from error
        if response.status_code not in tuple(expected):
            raise GeoCatalogError(
                f"{method} {url} returned HTTP {response.status_code}"
                f"{_safe_error_detail(response)}",
                status_code=response.status_code,
            )
        return response

    def close(self) -> None:
        self._session.close()
