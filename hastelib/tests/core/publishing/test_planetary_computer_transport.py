import unittest
from typing import Any, Optional

from hastegeo.core.publishing.geocatalog_client import (
    GeoCatalogAuth,
    GeoCatalogClient,
    GeoCatalogError,
)
from hastegeo.core.publishing.planetary_computer_transport import (
    PlanetaryComputerOperationError,
    PlanetaryComputerOperationKind,
    PlanetaryComputerRestAdapter,
)

ENDPOINT = "https://cat.example.geocatalog.spatio.azure.com"
OP_URL = f"{ENDPOINT}/inma/operations/op-1?api-version=2026-04-15"


class FakeResponse:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for GeoCatalogClient; replays queued responses and mirrors its
    raise-on-unexpected-status contract so 4xx branches are exercised."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(
        self,
        method,
        url,
        *,
        json=None,
        params=None,
        expected=(200, 201, 202, 204),
        absolute=False,
    ):
        self.calls.append(
            {"method": method, "url": url, "json": json, "absolute": absolute}
        )
        response = self.handler(method, url)
        if response.status_code not in tuple(expected):
            raise GeoCatalogError(
                f"{method} {url} -> {response.status_code}",
                status_code=response.status_code,
            )
        return response


def adapter(handler):
    return PlanetaryComputerRestAdapter(ENDPOINT, client=FakeClient(handler))


class TestGeoCatalogClient(unittest.TestCase):
    def _client(self, response):
        auth = GeoCatalogAuth(credential=_FakeCredential())
        client = GeoCatalogClient(ENDPOINT, auth=auth)
        client._session = _FakeSession(response)
        return client

    def test_builds_url_adds_api_version_and_auth(self):
        client = self._client(FakeResponse(200, payload={"ok": True}))
        client.request("GET", "/stac/collections/x")
        call = client._session.last
        self.assertEqual(
            call["url"], f"{ENDPOINT}/stac/collections/x"
        )
        self.assertEqual(call["params"]["api-version"], "2026-04-15")
        self.assertEqual(
            call["headers"]["Authorization"], "Bearer test-token"
        )
        self.assertFalse(call["allow_redirects"])

    def test_absolute_url_not_prefixed(self):
        client = self._client(FakeResponse(200, payload={}))
        client.request("GET", OP_URL, absolute=True)
        self.assertEqual(client._session.last["url"], OP_URL)

    def test_unexpected_status_raises_without_body(self):
        client = self._client(FakeResponse(409, payload={"secret": "x"}))
        with self.assertRaises(GeoCatalogError) as ctx:
            client.request("POST", "/stac/collections", expected=(201,))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertNotIn("secret", str(ctx.exception))


class TestRestAdapter(unittest.TestCase):
    def test_start_collection_async_202_pins_operation_url(self):
        step = adapter(
            lambda m, u: FakeResponse(202, {"operation-location": OP_URL})
        ).start_create_collection("c", {"id": "c"})
        self.assertFalse(step.is_complete)
        self.assertEqual(step.continuation_token, OP_URL)
        self.assertEqual(
            step.kind, PlanetaryComputerOperationKind.CREATE_COLLECTION
        )

    def test_start_collection_sync_201_is_complete(self):
        step = adapter(
            lambda m, u: FakeResponse(201, payload={"id": "c"})
        ).start_create_collection("c", {"id": "c"})
        self.assertTrue(step.is_complete)
        self.assertIsNone(step.continuation_token)

    def test_start_rejects_offorigin_operation_url(self):
        evil = "https://evil.example.com/inma/operations/op-1"
        with self.assertRaises(ValueError):
            adapter(
                lambda m, u: FakeResponse(202, {"operation-location": evil})
            ).start_create_item("c", "i", {"id": "i"})

    def test_continue_in_progress_stays_pending(self):
        step = adapter(
            lambda m, u: FakeResponse(200, payload={"status": "Running"})
        ).continue_create_item("c", "i", OP_URL)
        self.assertFalse(step.is_complete)
        self.assertEqual(step.continuation_token, OP_URL)

    def test_continue_finished_is_success(self):
        # Regression: "Finished" must be treated as terminal success.
        step = adapter(
            lambda m, u: FakeResponse(200, payload={"status": "Finished"})
        ).continue_create_item("c", "i", OP_URL)
        self.assertTrue(step.is_complete)
        self.assertIsNone(step.continuation_token)

    def test_continue_succeeded_with_failed_items_raises(self):
        payload = {
            "status": "Succeeded",
            "additionalInformation": {"totalFailedItems": 2},
        }
        with self.assertRaises(PlanetaryComputerOperationError):
            adapter(lambda m, u: FakeResponse(200, payload=payload)).\
                continue_create_item("c", "i", OP_URL)

    def test_continue_failed_sanitizes_error_code(self):
        payload = {
            "status": "Failed",
            "error": {"code": "Bad Code<script>", "message": "leak"},
        }
        with self.assertRaises(PlanetaryComputerOperationError) as ctx:
            adapter(lambda m, u: FakeResponse(200, payload=payload)).\
                continue_create_item("c", "i", OP_URL)
        message = str(ctx.exception)
        self.assertNotIn("<script>", message)
        self.assertNotIn("leak", message)

    def test_get_collection_404_returns_none(self):
        self.assertIsNone(
            adapter(lambda m, u: FakeResponse(404)).get_collection("missing")
        )

    def test_get_collection_returns_mapping(self):
        got = adapter(
            lambda m, u: FakeResponse(200, payload={"id": "c"})
        ).get_collection("c")
        self.assertEqual(got["id"], "c")

    def test_start_conflict_propagates_status(self):
        with self.assertRaises(GeoCatalogError) as ctx:
            adapter(lambda m, u: FakeResponse(409)).start_create_collection(
                "c", {"id": "c"}
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_get_ingestion_source_filters_by_id(self):
        payload = {"value": [{"id": "other"}, {"id": "src", "kind": "SasToken"}]}
        got = adapter(
            lambda m, u: FakeResponse(200, payload=payload)
        ).get_ingestion_source("src")
        self.assertEqual(got["kind"], "SasToken")
        self.assertIsNone(
            adapter(
                lambda m, u: FakeResponse(200, payload={"value": []})
            ).get_ingestion_source("src")
        )

    def test_get_signed_asset_url(self):
        signed = "https://acct.blob.core.windows.net/c/a.gpkg?sv=x&sig=y"
        got = adapter(
            lambda m, u: FakeResponse(200, payload={"href": signed})
        ).get_signed_asset_url(
            "https://acct.blob.core.windows.net/c/a.gpkg"
        )
        self.assertEqual(got, signed)

    def test_endpoint_must_be_https_origin(self):
        with self.assertRaises(ValueError):
            PlanetaryComputerRestAdapter("http://cat.example.com")


class _FakeToken:
    token = "test-token"
    expires_on = 9_999_999_999


class _FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return _FakeToken()


class _FakeSession:
    def __init__(self, response):
        self._response = response
        self.last: Optional[dict] = None

    def request(self, method, url, **kwargs: Any):
        self.last = {"method": method, "url": url, **kwargs}
        return self._response


if __name__ == "__main__":
    unittest.main()
