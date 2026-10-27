# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from hastegeo.core.utils.blob import (
    blob_url_without_query,
    clear_blob_client_caches,
    sign_label_project_urls,
    sign_internal_blob_url,
    sign_titiler_tile_url,
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

    def test_signs_internal_url_replacing_old_query(self):
        signed = sign_internal_blob_url(f"{BLOB_URL}?sv=old&sig=stale")
        self.assertEqual(signed, f"{BLOB_URL}?sv=1&sp=r&sig=fresh")
        kwargs = self.generate.call_args.kwargs
        self.assertEqual(kwargs["blob_name"], "p1/layer/post.tif")
        self.assertIsNone(kwargs["account_key"])
        self.assertIsNotNone(kwargs["user_delegation_key"])

    def test_external_and_other_container_pass_through(self):
        external = "https://provider.example.com/a.tif?token=1"
        other = f"{ACCOUNT_URL}/other/a.tif?sv=1"
        self.assertEqual(sign_internal_blob_url(external), external)
        self.assertEqual(sign_internal_blob_url(other), other)
        self.generate.assert_not_called()

    def test_other_account_passes_through(self):
        url = "https://other.blob.core.windows.net/data/a.tif"
        self.assertEqual(sign_internal_blob_url(url), url)

    def test_account_key_credential_signs_with_key(self):
        self.client.credential = MagicMock(account_key="k")
        sign_internal_blob_url(BLOB_URL)
        self.assertEqual(self.generate.call_args.kwargs["account_key"], "k")


class TestSignTilerUrls(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "hastegeo.core.utils.blob.sign_internal_blob_url",
            side_effect=lambda url: (
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
