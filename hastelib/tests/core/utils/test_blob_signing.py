# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from hastegeo.core.utils.blob import (
    blob_url_without_query,
    clear_blob_client_caches,
    sign_internal_blob_url,
    sign_label_project_urls,
    sign_titiler_tile_url,
    unsigned_internal_blob_url,
)

ACCOUNT_URL = "https://acct.blob.core.windows.net"
BLOB_URL = f"{ACCOUNT_URL}/data/p1/layer/post.tif"


def _identity_client():
    client = MagicMock()
    client.url = f"{ACCOUNT_URL}/"
    client.account_name = "acct"
    client.credential = object()
    client.get_blob_client.side_effect = lambda container, blob: MagicMock(
        url=f"{ACCOUNT_URL}/{container}/{blob}"
    )
    return client


class TestBlobUrlWithoutQuery(unittest.TestCase):
    def test_strips_query(self):
        self.assertEqual(
            blob_url_without_query(f"{BLOB_URL}?sv=1&sig=x"), BLOB_URL
        )

    def test_no_query_and_empty(self):
        self.assertEqual(blob_url_without_query(BLOB_URL), BLOB_URL)
        self.assertIsNone(blob_url_without_query(None))
        self.assertIsNone(blob_url_without_query(""))


class TestSignInternalBlobUrl(unittest.TestCase):
    def setUp(self):
        clear_blob_client_caches()
        env = patch.dict(
            os.environ,
            {"BLOB_ACCOUNT_URL": ACCOUNT_URL, "BLOB_CONTAINER": "data"},
            clear=True,
        )
        env.start()
        self.addCleanup(env.stop)
        self.client = _identity_client()
        for target in (
            "hastegeo.core.utils.blob.get_app_blob_service_client",
            "hastegeo.core.utils.blob.get_blob_service_client",
            "hastegeo.core.utils.blob.get_cached_user_delegation_key",
        ):
            patcher = patch(target)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            if target.endswith("client"):
                mock.return_value = self.client
        self.sas = patch(
            "hastegeo.core.utils.blob_sas.generate_blob_sas",
            return_value="sv=1&sp=r&sig=fresh",
        )
        self.generate = self.sas.start()
        self.addCleanup(self.sas.stop)

    def test_unsigned_strips_only_internal_queries(self):
        external = "https://provider.example.com/a.tif?token=keep"
        self.assertEqual(
            unsigned_internal_blob_url(f"{BLOB_URL}?sig=old"), BLOB_URL
        )
        self.assertEqual(unsigned_internal_blob_url(external), external)
        self.assertIsNone(unsigned_internal_blob_url(""))
        other_container = f"{ACCOUNT_URL}/provider/a.tif?sig=keep"
        self.assertEqual(
            unsigned_internal_blob_url(other_container), other_container
        )

    def test_signs_internal_url_replacing_old_query(self):
        signed = sign_internal_blob_url(f"{BLOB_URL}?sv=old&sig=stale")
        self.assertEqual(signed, f"{BLOB_URL}?sv=1&sp=r&sig=fresh")
        kwargs = self.generate.call_args.kwargs
        self.assertEqual(kwargs["blob_name"], "p1/layer/post.tif")
        self.assertIsNone(kwargs["account_key"])
        self.assertIsNotNone(kwargs["user_delegation_key"])

    def test_external_passes_through_but_foreign_container_is_refused(self):
        external = "https://provider.example.com/a.tif?token=1"
        other = f"{ACCOUNT_URL}/other/a.tif?sv=1"
        self.assertEqual(sign_internal_blob_url(external), external)
        with self.assertRaises(ValueError):
            sign_internal_blob_url(other)
        self.generate.assert_not_called()

    def test_other_account_is_refused(self):
        url = "https://other.blob.core.windows.net/data/a.tif"
        with self.assertRaises(ValueError):
            sign_internal_blob_url(url)

    def test_azure_account_key_never_signs_read_tokens(self):
        self.client.credential = MagicMock(account_key="k")
        sign_internal_blob_url(BLOB_URL)
        self.assertIsNone(self.generate.call_args.kwargs["account_key"])

    def test_project_prefix_is_required_and_checked_before_signing(self):
        for url in (
            BLOB_URL,
            f"{ACCOUNT_URL}/data/p10/post.tif",
            f"{ACCOUNT_URL}/data/p1/%2e%2e/p2/post.tif",
            "https://provider.example.com/a.tif",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                sign_internal_blob_url(url, required_blob_prefix="p2")
        self.generate.assert_not_called()
        signed = sign_internal_blob_url(BLOB_URL, required_blob_prefix="p1")
        self.assertIn("sig=fresh", signed)

    def test_equivalent_https_port_and_encoded_blob_name(self):
        signed = sign_internal_blob_url(
            f"{ACCOUNT_URL}:443/data/p1/a%20b.tif",
            required_blob_prefix="p1",
        )
        self.assertIn("sig=fresh", signed)
        self.assertEqual(
            self.generate.call_args.kwargs["blob_name"], "p1/a b.tif"
        )

    def test_rejects_url_userinfo_and_invalid_lifetime(self):
        with self.assertRaises(ValueError):
            sign_internal_blob_url(
                "https://user@acct.blob.core.windows.net/data/p1/a.tif"
            )
        with self.assertRaises(ValueError):
            sign_internal_blob_url(BLOB_URL, minutes=61)
        self.generate.assert_not_called()

    def test_azurite_keeps_local_key_signing_and_validates_account_path(self):
        emulator = "http://azurite:10000/devstoreaccount1"
        self.client.url = emulator
        self.client.account_name = "devstoreaccount1"
        self.client.credential = MagicMock(account_key="emulator-key")
        self.client.get_blob_client.side_effect = (
            lambda container, blob: MagicMock(
                url=f"{emulator}/{container}/{blob}"
            )
        )
        with patch.dict(os.environ, {"BLOB_ACCOUNT_URL": emulator}):
            signed = sign_internal_blob_url(
                f"{emulator}/data/p1/post.tif", required_blob_prefix="p1"
            )
            self.assertIn("sig=fresh", signed)
            self.assertEqual(
                self.generate.call_args.kwargs["account_key"], "emulator-key"
            )
            with self.assertRaises(ValueError):
                sign_internal_blob_url(
                    "http://azurite:10000/another-account/data/p1/post.tif",
                    required_blob_prefix="p1",
                )
        self.assertEqual(self.generate.call_count, 1)


class TestSignTilerUrls(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "hastegeo.core.utils.blob.sign_internal_blob_url",
            side_effect=lambda url, **kwargs: (
                f"{url}?sig=fresh" if "acct" in url else url
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _tile(self, source):
        return (
            "/api/titiler/cog/tiles/WebMercatorQuad/{z}/{x}/{y}"
            f"?scale=1&url={quote(source, safe='')}&colormap=x"
        )

    def test_signs_only_nested_source(self):
        source = f"{BLOB_URL}?sig=old"
        result = sign_titiler_tile_url(self._tile(source))
        self.assertIn("{z}/{x}/{y}", result)
        self.assertTrue(result.endswith("&colormap=x"))
        self.assertIn(quote("?sig=fresh", safe=""), result)

    def test_external_source_unchanged(self):
        tile = self._tile("https://provider.example.com/a.tif")
        self.assertEqual(sign_titiler_tile_url(tile), tile)

    def test_project_details_urls_signed(self):
        from hastegeo.core.utils.blob import sign_project_details_urls

        project = {
            "imageLayer": [
                {
                    "preEventPreviewUrls": [BLOB_URL],
                    "labelsUrl": BLOB_URL,
                    "buildingFootprintsUrl": BLOB_URL,
                    "validAreaMaskUrl": BLOB_URL,
                    "models": [
                        {
                            "trainingZipUrl": BLOB_URL,
                            "inferenceZipUrl": None,
                            "artifacts": {
                                "trainingZipUrl": BLOB_URL,
                                "zipUrl": BLOB_URL,
                            },
                        }
                    ],
                },
                {},
            ]
        }
        result = sign_project_details_urls(project, "project-1")
        signed = f"{BLOB_URL}?sig=fresh"
        layer = result["imageLayer"][0]
        self.assertEqual(layer["preEventPreviewUrls"], [signed])
        self.assertEqual(layer["labelsUrl"], signed)
        self.assertEqual(layer["models"][0]["trainingZipUrl"], signed)
        self.assertIsNone(layer["models"][0]["inferenceZipUrl"])
        self.assertEqual(layer["buildingFootprintsUrl"], signed)
        self.assertEqual(layer["validAreaMaskUrl"], signed)
        artifacts = layer["models"][0]["artifacts"]
        self.assertEqual(artifacts["trainingZipUrl"], signed)
        self.assertEqual(artifacts["zipUrl"], signed)
        self.assertEqual(layer["buildingFootprintsUrl"], signed)
        self.assertEqual(layer["validAreaMaskUrl"], signed)
        artifacts = layer["models"][0]["artifacts"]
        self.assertEqual(artifacts["trainingZipUrl"], signed)
        self.assertEqual(artifacts["zipUrl"], signed)
        self.assertEqual(result["imageLayer"][1], {})

    def test_label_project_fields_signed_without_mutation(self):
        original = {
            "imagery": {
                "tileUrl": self._tile(BLOB_URL),
                "preEventTileUrl": self._tile(BLOB_URL),
                "postEventTileUrl": "",
            }
        }
        result = sign_label_project_urls(original)
        self.assertIn("fresh", result["imagery"]["tileUrl"])
        self.assertIn("fresh", result["imagery"]["preEventTileUrl"])
        self.assertEqual(result["imagery"]["postEventTileUrl"], "")
        self.assertNotIn("fresh", original["imagery"]["tileUrl"])


if __name__ == "__main__":
    unittest.main()
