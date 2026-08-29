"""REST transport adapter for the Planetary Computer Pro GeoCatalog.

Presents the resumable, one-request-per-step interface the publishing provider
depends on (start/continue create-collection, create-item, delete-item; plus
get-collection/item/ingestion-source and asset signing), backed by the vendored
``GeoCatalogClient`` REST client instead of the ``azure-planetarycomputer`` SDK.

The GeoCatalog ingests items asynchronously: ``POST .../items`` returns 202 with
an ``operation-location`` header that is polled to a terminal state. Collection
creation is synchronous (201). ``_start_from_response`` handles both: a 202
yields an incomplete step carrying the (origin-pinned) operation URL; a 2xx
without a 202 yields a completed step.

Security controls carried over from the SDK adapter (and absent from the
reference REST client): operation-URL SSRF pinning to the GeoCatalog origin,
endpoint validation, sanitized error/status text (no server bodies), and
strict failed-item accounting. Redirect suppression and per-request timeouts
live in ``GeoCatalogClient``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional
from urllib.parse import parse_qsl, urlparse

from .geocatalog_client import GeoCatalogAuth, GeoCatalogClient


class PlanetaryComputerOperationKind(str, Enum):
    CREATE_COLLECTION = "create_collection"
    CREATE_ITEM = "create_item"
    DELETE_ITEM = "delete_item"
    DELETE_COLLECTION = "delete_collection"


class PlanetaryComputerOperationError(RuntimeError):
    """Raised when a GeoCatalog long-running operation fails."""


@dataclass(frozen=True)
class PlanetaryComputerOperationStep:
    kind: PlanetaryComputerOperationKind
    collection_id: str
    item_id: Optional[str]
    continuation_token: Optional[str] = field(repr=False)
    is_complete: bool


class PlanetaryComputerRestAdapter:
    """Run one authenticated GeoCatalog REST request per adapter step."""

    _IN_PROGRESS_STATUSES = {
        "inprogress",
        "notstarted",
        "pending",
        "running",
        "accepted",
    }
    # Includes "finished": the GeoCatalog reports terminal success as either
    # Succeeded or Finished; omitting the latter would fail a good ingest.
    _SUCCESS_STATUSES = {"completed", "succeeded", "success", "finished"}
    _FAILURE_STATUSES = {"cancelled", "canceled", "failed"}

    def __init__(
        self,
        endpoint: str,
        *,
        client: Any = None,
        credential: Any = None,
        connection_timeout: int = 10,
        read_timeout: int = 30,
    ) -> None:
        self.endpoint = self._validate_endpoint(endpoint)
        if connection_timeout < 1 or read_timeout < 1:
            raise ValueError("Planetary Computer timeouts must be positive")
        self.connection_timeout = connection_timeout
        self.read_timeout = read_timeout
        self._credential = credential
        self._client = client

    @property
    def client(self) -> GeoCatalogClient:
        if self._client is None:
            self._client = GeoCatalogClient(
                self.endpoint,
                auth=GeoCatalogAuth(self._credential),
                connection_timeout=self.connection_timeout,
                read_timeout=self.read_timeout,
            )
        return self._client

    # ------------------------------------------------------------ collections

    def get_collection(
        self, collection_id: str
    ) -> Optional[Mapping[str, Any]]:
        response = self.client.request(
            "GET",
            f"/stac/collections/{collection_id}",
            expected=(200, 404),
        )
        if response.status_code == 404:
            return None
        return self._as_mapping(response.json())

    def start_create_collection(
        self,
        collection_id: str,
        body: Mapping[str, Any],
    ) -> PlanetaryComputerOperationStep:
        response = self.client.request(
            "POST",
            "/stac/collections",
            json=dict(body),
            expected=(200, 201, 202),
        )
        return self._start_from_response(
            response,
            PlanetaryComputerOperationKind.CREATE_COLLECTION,
            collection_id,
        )

    def replace_collection(
        self,
        collection_id: str,
        body: Mapping[str, Any],
    ) -> None:
        # MPC Pro manages collection-level assets (the thumbnail) through the
        # Collection Asset API. A collection PUT is a full-document replace, so
        # a body that OMITS an existing managed asset is read as an attempt to
        # REMOVE it and rejected ("'thumbnail' must be removed using the
        # GeoCatalog Collection Asset API"). Our rebuilt collection body carries
        # no assets, so on re-publish/edit/unpublish we must carry the live
        # managed assets forward verbatim. Fetch the current collection and echo
        # its assets back; only send `assets` when the collection actually has
        # them (a freshly POST-created collection has none, and MPC rejects an
        # asset map on create).
        payload = {
            key: value for key, value in body.items() if key != "assets"
        }
        current = self.get_collection(collection_id)
        current_assets = (current or {}).get("assets")
        if current_assets:
            payload["assets"] = current_assets
        self.client.request(
            "PUT",
            f"/stac/collections/{collection_id}",
            json=payload,
            expected=(200, 201, 202, 204),
        )

    def continue_create_collection(
        self,
        collection_id: str,
        continuation_token: str,
    ) -> PlanetaryComputerOperationStep:
        return self._continue(
            PlanetaryComputerOperationKind.CREATE_COLLECTION,
            collection_id,
            None,
            continuation_token,
        )

    def start_delete_collection(
        self,
        collection_id: str,
    ) -> PlanetaryComputerOperationStep:
        response = self.client.request(
            "DELETE",
            f"/stac/collections/{collection_id}",
            expected=(200, 202, 204),
        )
        return self._start_from_response(
            response,
            PlanetaryComputerOperationKind.DELETE_COLLECTION,
            collection_id,
        )

    def continue_delete_collection(
        self,
        collection_id: str,
        continuation_token: str,
    ) -> PlanetaryComputerOperationStep:
        return self._continue(
            PlanetaryComputerOperationKind.DELETE_COLLECTION,
            collection_id,
            None,
            continuation_token,
        )

    def list_item_ids(
        self, collection_id: str, limit: int = 100
    ) -> list:
        """Return the ids of items currently in the collection (bounded)."""
        response = self.client.request(
            "GET",
            f"/stac/collections/{collection_id}/items",
            params={"limit": limit},
            expected=(200, 404),
        )
        if response.status_code == 404:
            return []
        payload = response.json()
        features = []
        if isinstance(payload, Mapping):
            features = payload.get("features") or []
        return [
            str(feature["id"])
            for feature in features
            if isinstance(feature, Mapping) and feature.get("id")
        ]

    def upload_collection_asset(
        self,
        collection_id: str,
        key: str,
        data: bytes,
        filename: str,
        media_type: str,
        roles: Optional[list] = None,
        title: Optional[str] = None,
    ) -> None:
        """Attach a collection-level asset via the Collection Asset API.

        MPC Pro rejects assets in the collection POST; they must be uploaded
        here as multipart/form-data (a JSON `data` part + the file part).
        """
        metadata: dict[str, Any] = {
            "key": key,
            "href": "",
            "type": media_type,
            "roles": roles or [key],
        }
        if title:
            metadata["title"] = title
        self.client.request(
            "POST",
            f"/stac/collections/{collection_id}/assets",
            data={"data": json.dumps(metadata)},
            files={"file": (filename, data, media_type)},
            expected=(200, 201),
        )

    # ------------------------------------------------ visualization config

    @staticmethod
    def _config_list(payload: Any) -> list:
        """Normalize a configurations GET body to a list of dicts."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, Mapping):
            for key in ("renderOptions", "render_options", "mosaics", "value"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def get_render_options(self, collection_id: str) -> list:
        response = self.client.request(
            "GET",
            f"/stac/collections/{collection_id}/configurations/render-options",
            expected=(200, 404),
        )
        if response.status_code == 404:
            return []
        return self._config_list(response.json())

    def create_render_option(
        self, collection_id: str, body: Mapping[str, Any]
    ) -> None:
        self.client.request(
            "POST",
            f"/stac/collections/{collection_id}/configurations/render-options",
            json=dict(body),
            expected=(200, 201),
        )

    def get_mosaics(self, collection_id: str) -> list:
        response = self.client.request(
            "GET",
            f"/stac/collections/{collection_id}/configurations/mosaics",
            expected=(200, 404),
        )
        if response.status_code == 404:
            return []
        return self._config_list(response.json())

    def create_mosaic(
        self, collection_id: str, body: Mapping[str, Any]
    ) -> None:
        self.client.request(
            "POST",
            f"/stac/collections/{collection_id}/configurations/mosaics",
            json=dict(body),
            expected=(200, 201),
        )

    def replace_tile_settings(
        self, collection_id: str, body: Mapping[str, Any]
    ) -> None:
        # PUT is replace-semantics, so this is naturally idempotent.
        self.client.request(
            "PUT",
            f"/stac/collections/{collection_id}/configurations/tile-settings",
            json=dict(body),
            expected=(200, 201, 202, 204),
        )

    # ------------------------------------------------------------------ items

    def get_item(
        self,
        collection_id: str,
        item_id: str,
    ) -> Optional[Mapping[str, Any]]:
        response = self.client.request(
            "GET",
            f"/stac/collections/{collection_id}/items/{item_id}",
            expected=(200, 404),
        )
        if response.status_code == 404:
            return None
        return self._as_mapping(response.json())

    def update_item(
        self,
        collection_id: str,
        item_id: str,
        body: Mapping[str, Any],
    ) -> None:
        """Replace an existing item document (STAC transactions PUT)."""
        self.client.request(
            "PUT",
            f"/stac/collections/{collection_id}/items/{item_id}",
            json=dict(body),
            expected=(200, 201, 202, 204),
        )

    def start_create_item(
        self,
        collection_id: str,
        item_id: str,
        body: Mapping[str, Any],
    ) -> PlanetaryComputerOperationStep:
        response = self.client.request(
            "POST",
            f"/stac/collections/{collection_id}/items",
            json=dict(body),
            expected=(200, 201, 202),
        )
        return self._start_from_response(
            response,
            PlanetaryComputerOperationKind.CREATE_ITEM,
            collection_id,
            item_id,
        )

    def continue_create_item(
        self,
        collection_id: str,
        item_id: str,
        continuation_token: str,
    ) -> PlanetaryComputerOperationStep:
        return self._continue(
            PlanetaryComputerOperationKind.CREATE_ITEM,
            collection_id,
            item_id,
            continuation_token,
        )

    def start_delete_item(
        self,
        collection_id: str,
        item_id: str,
    ) -> PlanetaryComputerOperationStep:
        response = self.client.request(
            "DELETE",
            f"/stac/collections/{collection_id}/items/{item_id}",
            expected=(200, 202, 204),
        )
        return self._start_from_response(
            response,
            PlanetaryComputerOperationKind.DELETE_ITEM,
            collection_id,
            item_id,
        )

    def continue_delete_item(
        self,
        collection_id: str,
        item_id: str,
        continuation_token: str,
    ) -> PlanetaryComputerOperationStep:
        return self._continue(
            PlanetaryComputerOperationKind.DELETE_ITEM,
            collection_id,
            item_id,
            continuation_token,
        )

    # ------------------------------------------------------- ingestion / SAS

    def get_ingestion_source(
        self, source_id: str
    ) -> Optional[Mapping[str, Any]]:
        # The REST API exposes only a list endpoint; find the source by id.
        response = self.client.request(
            "GET", "/inma/ingestion-sources", expected=(200,)
        )
        payload = response.json()
        if isinstance(payload, Mapping):
            sources = payload.get("value", [])
        elif isinstance(payload, list):
            sources = payload
        else:
            sources = []
        for source in sources:
            if isinstance(source, Mapping) and str(source.get("id")) == str(
                source_id
            ):
                return self._as_mapping(source)
        return None

    def get_signed_asset_url(self, href: str) -> str:
        response = self.client.request(
            "GET", "/sas/sign", params={"href": href}, expected=(200,)
        )
        signed_link = self._as_mapping(response.json())
        signed_href = signed_link.get("href")
        if not isinstance(signed_href, str) or not signed_href:
            raise PlanetaryComputerOperationError(
                "Planetary Computer returned an invalid signed asset URL"
            )
        return signed_href

    def close(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close is not None:
                close()

    # ------------------------------------------------------------- internals

    def _start_from_response(
        self,
        response: Any,
        kind: PlanetaryComputerOperationKind,
        collection_id: str,
        item_id: Optional[str] = None,
    ) -> PlanetaryComputerOperationStep:
        if response.status_code == 202:
            headers = {
                str(key).lower(): value
                for key, value in response.headers.items()
            }
            operation_url = headers.get("operation-location") or headers.get(
                "location"
            )
            operation_url = self._validate_operation_url(operation_url)
            return PlanetaryComputerOperationStep(
                kind=kind,
                collection_id=collection_id,
                item_id=item_id,
                continuation_token=operation_url,
                is_complete=False,
            )
        # Synchronous completion (e.g. 201 Created for a collection).
        return PlanetaryComputerOperationStep(
            kind=kind,
            collection_id=collection_id,
            item_id=item_id,
            continuation_token=None,
            is_complete=True,
        )

    def _continue(
        self,
        kind: PlanetaryComputerOperationKind,
        collection_id: str,
        item_id: Optional[str],
        continuation_token: str,
    ) -> PlanetaryComputerOperationStep:
        operation_url = self._validate_operation_url(continuation_token)
        response = self.client.request(
            "GET", operation_url, expected=(200,), absolute=True
        )
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise PlanetaryComputerOperationError(
                "Planetary Computer returned an invalid operation response"
            )
        status = str(payload.get("status") or "").replace("_", "").lower()
        if status in self._IN_PROGRESS_STATUSES:
            return PlanetaryComputerOperationStep(
                kind=kind,
                collection_id=collection_id,
                item_id=item_id,
                continuation_token=operation_url,
                is_complete=False,
            )
        if status in self._SUCCESS_STATUSES:
            failed_items = self._failed_item_count(payload)
            if failed_items:
                raise PlanetaryComputerOperationError(
                    "Planetary Computer operation failed "
                    f"({failed_items} items)"
                )
            return PlanetaryComputerOperationStep(
                kind=kind,
                collection_id=collection_id,
                item_id=item_id,
                continuation_token=None,
                is_complete=True,
            )
        if status in self._FAILURE_STATUSES:
            error = payload.get("error") or {}
            if not isinstance(error, Mapping):
                error = {}
            code = re.sub(
                r"[^A-Za-z0-9_.-]", "", str(error.get("code") or "")
            )
            detail = f" ({code})" if code else ""
            raise PlanetaryComputerOperationError(
                f"Planetary Computer operation {status}{detail}"
            )
        raise PlanetaryComputerOperationError(
            "Planetary Computer returned an unknown operation status"
        )

    @staticmethod
    def _failed_item_count(payload: Mapping[str, Any]) -> int:
        value = None
        candidates = [payload]
        for key in ("additionalInformation", "additional_information"):
            additional = payload.get(key)
            if isinstance(additional, Mapping):
                candidates.append(additional)
        for candidate in candidates:
            for key, candidate_value in candidate.items():
                normalized_key = str(key).replace("_", "").lower()
                if normalized_key == "totalfaileditems":
                    value = candidate_value
                    break
            if value is not None:
                break
        if value is None:
            return 0
        if isinstance(value, bool):
            raise PlanetaryComputerOperationError(
                "Planetary Computer returned an invalid failed-item count"
            )
        try:
            count = int(value)
        except (TypeError, ValueError) as error:
            raise PlanetaryComputerOperationError(
                "Planetary Computer returned an invalid failed-item count"
            ) from error
        if count < 0:
            raise PlanetaryComputerOperationError(
                "Planetary Computer returned an invalid failed-item count"
            )
        return count

    @staticmethod
    def _validate_endpoint(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError(
                "Planetary Computer endpoint is invalid"
            ) from error
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Planetary Computer endpoint is invalid")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "Planetary Computer endpoint must be an HTTPS origin"
            )
        return endpoint.rstrip("/")

    @classmethod
    def _as_mapping(cls, value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        raise TypeError("Planetary Computer response is not a mapping")

    def _validate_operation_url(self, value: Optional[str]) -> str:
        if not value or len(value) > 4096:
            raise ValueError("Planetary Computer operation URL is invalid")
        endpoint = urlparse(self.endpoint)
        operation = urlparse(value)
        try:
            operation_port = operation.port
        except ValueError as error:
            raise ValueError(
                "Planetary Computer operation URL is invalid"
            ) from error
        endpoint_port = endpoint.port
        if operation_port is not None and not 1 <= operation_port <= 65535:
            raise ValueError("Planetary Computer operation URL is invalid")
        if (
            operation.scheme != "https"
            or operation.hostname != endpoint.hostname
            or (operation_port if operation_port is not None else 443)
            != (endpoint_port if endpoint_port is not None else 443)
            or operation.username is not None
            or operation.password is not None
            or operation.fragment
            or not operation.path
        ):
            raise ValueError(
                "Planetary Computer operation URL must use the "
                "GeoCatalog origin"
            )
        query_names = {
            name.lower()
            for name, _ in parse_qsl(
                operation.query,
                keep_blank_values=True,
            )
        }
        if not query_names.issubset({"api-version"}):
            raise ValueError(
                "Planetary Computer operation URL has unsupported query fields"
            )
        return value
