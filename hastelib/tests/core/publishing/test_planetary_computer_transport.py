import json
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
    def __init__(self, status_code, headers=None, payload=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = text

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
        data=None,
        files=None,
        params=None,
        expected=(200, 201, 202, 204),
        absolute=False,
    ):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "data": data,
                "files": files,
                "absolute": absolute,
            }
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

    def test_multipart_data_and_files_pass_through(self):
        client = self._client(FakeResponse(201, payload={}))
        client.request(
            "POST",
            "/stac/collections/c/assets",
            data={"data": "{}"},
            files={"file": ("t.png", b"x", "image/png")},
            expected=(201,),
        )
        self.assertEqual(client._session.last["data"], {"data": "{}"})
        self.assertEqual(
            client._session.last["files"]["file"],
            ("t.png", b"x", "image/png"),
        )

    def test_unexpected_status_surfaces_redacted_body(self):
        body = (
            "Invalid collection: asset href "
            "https://acct.blob.core.windows.net/c/x?sig=SECRETTOKEN not allowed"
        )
        client = self._client(FakeResponse(400, text=body))
        with self.assertRaises(GeoCatalogError) as ctx:
            client.request("POST", "/stac/collections", expected=(201,))
        message = str(ctx.exception)
        self.assertEqual(ctx.exception.status_code, 400)
        # The validation detail is surfaced for diagnosis...
        self.assertIn("Invalid collection", message)
        # ...but URLs and tokens in the body are redacted.
        self.assertNotIn("SECRETTOKEN", message)
        self.assertNotIn("blob.core.windows.net", message)


class TestRestAdapter(unittest.TestCase):
    def test_upload_collection_asset_posts_multipart(self):
        client = FakeClient(lambda m, u: FakeResponse(201, payload={}))
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.upload_collection_asset(
            "haste-c",
            key="thumbnail",
            data=b"\x89PNG",
            filename="thumbnail.png",
            media_type="image/png",
            roles=["thumbnail"],
            title="Collection thumbnail",
        )
        call = client.calls[-1]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "/stac/collections/haste-c/assets")
        metadata = json.loads(call["data"]["data"])
        self.assertEqual(metadata["key"], "thumbnail")
        self.assertEqual(metadata["roles"], ["thumbnail"])
        self.assertEqual(metadata["type"], "image/png")
        self.assertEqual(metadata["title"], "Collection thumbnail")
        self.assertEqual(
            call["files"]["file"],
            ("thumbnail.png", b"\x89PNG", "image/png"),
        )

    def test_replace_collection_preserves_live_managed_assets(self):
        # MPC Pro's collection PUT is a full-document replace: omitting the
        # live managed thumbnail reads as REMOVING it and is rejected. The
        # rebuilt body carries no assets, so the PUT must carry the live
        # thumbnail (fetched via GET) forward verbatim.
        live_thumbnail = {
            "thumbnail": {"href": "https://x/live.png", "roles": ["thumbnail"]}
        }

        def handler(method, url):
            if method == "GET":
                return FakeResponse(
                    200, payload={"id": "haste-x", "assets": live_thumbnail}
                )
            return FakeResponse(200, payload={})

        client = FakeClient(handler)
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.replace_collection(
            "haste-x",
            {"id": "haste-x", "description": "d"},
        )
        put = client.calls[-1]
        self.assertEqual(put["method"], "PUT")
        self.assertEqual(put["url"], "/stac/collections/haste-x")
        self.assertEqual(put["json"]["description"], "d")
        # The live thumbnail is carried forward so MPC does not read the PUT
        # as an asset removal.
        self.assertEqual(put["json"]["assets"], live_thumbnail)

    def test_replace_collection_omits_assets_when_none_live(self):
        # A freshly POST-created collection has no managed assets yet; the PUT
        # must not send an `assets` map (MPC rejects it on such collections).
        def handler(method, url):
            return FakeResponse(200, payload={"id": "haste-x"})

        client = FakeClient(handler)
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.replace_collection(
            "haste-x",
            {
                "id": "haste-x",
                "description": "d",
                "assets": {"thumbnail": {"href": "https://x/stale.png"}},
            },
        )
        put = client.calls[-1]
        self.assertEqual(put["method"], "PUT")
        self.assertNotIn("assets", put["json"])
        self.assertEqual(put["json"]["description"], "d")

    def test_create_render_option_posts_to_configurations(self):
        client = FakeClient(lambda m, u: FakeResponse(201, payload={}))
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.create_render_option("haste-c", {"id": "damage", "type": "raster-tile"})
        call = client.calls[-1]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(
            call["url"],
            "/stac/collections/haste-c/configurations/render-options",
        )
        self.assertEqual(call["json"]["id"], "damage")

    def test_get_render_options_unwraps_and_handles_404(self):
        # Bare list.
        got = adapter(
            lambda m, u: FakeResponse(200, payload=[{"id": "damage"}])
        ).get_render_options("c")
        self.assertEqual(got, [{"id": "damage"}])
        # Dict-wrapped.
        got = adapter(
            lambda m, u: FakeResponse(
                200, payload={"renderOptions": [{"id": "x"}]}
            )
        ).get_render_options("c")
        self.assertEqual(got, [{"id": "x"}])
        # 404 -> empty.
        self.assertEqual(
            adapter(lambda m, u: FakeResponse(404)).get_render_options("c"), []
        )

    def test_create_mosaic_posts_to_configurations(self):
        client = FakeClient(lambda m, u: FakeResponse(201, payload={}))
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.create_mosaic("haste-c", {"id": "most-recent", "cql": []})
        call = client.calls[-1]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(
            call["url"], "/stac/collections/haste-c/configurations/mosaics"
        )
        self.assertEqual(call["json"]["id"], "most-recent")

    def test_replace_tile_settings_puts(self):
        client = FakeClient(lambda m, u: FakeResponse(200, payload={}))
        rest = PlanetaryComputerRestAdapter(ENDPOINT, client=client)
        rest.replace_tile_settings("haste-c", {"minZoom": 13})
        call = client.calls[-1]
        self.assertEqual(call["method"], "PUT")
        self.assertEqual(
            call["url"],
            "/stac/collections/haste-c/configurations/tile-settings",
        )
        self.assertEqual(call["json"]["minZoom"], 13)

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
