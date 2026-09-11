# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.blob.

``split_blob_url`` and ``parse_byte_range`` are pure helpers. ``fetch_url_text``
is covered with a mocked ``requests`` because its whole contract is that it
never raises — it backs the task-output fallback, where an exception would mask
the original reason a file could not be read from the compute node.

The async download_blob_to_tempfile helper isn't covered here because it
needs a live blob backend (Azurite); the integration is exercised by the
existing test_artifacts.py.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.utils.blob import (
    clear_blob_client_caches,
    download_blob_to_tempfile,
    fetch_url_text,
    get_blob_service_client,
    get_cached_user_delegation_key,
    parse_byte_range,
    read_blob_range,
    split_blob_url,
)


class TestBlobServiceClientCache(unittest.TestCase):
    def setUp(self):
        clear_blob_client_caches()

    def tearDown(self):
        clear_blob_client_caches()

    @patch("azure.storage.blob.BlobServiceClient.from_connection_string")
    def test_reuses_client_for_connection_string(self, from_connection_string):
        first = get_blob_service_client(connection_string="connection")
        second = get_blob_service_client(connection_string="connection")

        self.assertIs(first, second)
        from_connection_string.assert_called_once_with("connection")

    @patch("azure.storage.blob.BlobServiceClient")
    @patch("azure.identity.DefaultAzureCredential")
    def test_reuses_client_for_account_url(self, credential, client_class):
        first = get_blob_service_client(account_url="https://account.test")
        second = get_blob_service_client(account_url="https://account.test")

        self.assertIs(first, second)
        credential.assert_called_once_with()
        client_class.assert_called_once_with(
            account_url="https://account.test",
            credential=credential.return_value,
        )

    def test_requires_connection_target(self):
        with self.assertRaises(ValueError):
            get_blob_service_client()

    def test_reuses_unexpired_user_delegation_key(self):
        from datetime import datetime, timedelta, timezone

        client = MagicMock(url="https://account.test")
        client.get_user_delegation_key.return_value = "delegation-key"
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)

        first = get_cached_user_delegation_key(client, now=now)
        second = get_cached_user_delegation_key(
            client, now=now + timedelta(hours=1)
        )

        self.assertEqual(first, "delegation-key")
        self.assertEqual(second, "delegation-key")
        client.get_user_delegation_key.assert_called_once()

    def test_refreshes_expiring_user_delegation_key(self):
        from datetime import datetime, timedelta, timezone

        client = MagicMock(url="https://account.test")
        client.get_user_delegation_key.side_effect = ["first", "second"]
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        get_cached_user_delegation_key(client, now=now)

        result = get_cached_user_delegation_key(
            client, now=now + timedelta(hours=1, minutes=46)
        )

        self.assertEqual(result, "second")
        self.assertEqual(client.get_user_delegation_key.call_count, 2)

    def test_user_delegation_cache_evicts_oldest_client(self):
        from datetime import datetime, timezone

        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        clients = []
        for index in range(9):
            client = MagicMock(url=f"https://account-{index}.test")
            client.get_user_delegation_key.return_value = f"key-{index}"
            clients.append(client)
            get_cached_user_delegation_key(client, now=now)

        get_cached_user_delegation_key(clients[0], now=now)

        self.assertEqual(clients[0].get_user_delegation_key.call_count, 2)
        self.assertEqual(clients[-1].get_user_delegation_key.call_count, 1)


class TestAsyncBlobHelpers(unittest.IsolatedAsyncioTestCase):
    @patch("hastegeo.core.utils.blob.get_blob_service_client")
    async def test_download_blob_to_tempfile_uses_shared_client(self, factory):
        blob_client = (
            factory.return_value.get_container_client.return_value.get_blob_client.return_value
        )
        blob_client.download_blob.return_value.chunks.return_value = [
            b"hello",
            b" world",
        ]

        path = await download_blob_to_tempfile(
            "https://account.blob.core.windows.net/container/file.txt"
        )
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))

        with open(path, "rb") as downloaded:
            self.assertEqual(downloaded.read(), b"hello world")
        factory.assert_called_once()

    @patch("hastegeo.core.utils.blob.get_blob_service_client")
    async def test_read_blob_range_uses_shared_client(self, factory):
        blob_client = (
            factory.return_value.get_container_client.return_value.get_blob_client.return_value
        )
        properties = blob_client.get_blob_properties.return_value
        properties.size = 5
        properties.content_settings.content_type = "text/plain"
        properties.etag = '"etag"'
        blob_client.download_blob.return_value.readall.return_value = b"ell"

        result = await read_blob_range(
            "https://account.blob.core.windows.net/container/file.txt",
            offset=1,
            length=3,
        )

        self.assertEqual(result.data, b"ell")
        self.assertEqual(result.total_size, 5)
        blob_client.download_blob.assert_called_once_with(offset=1, length=3)


class TestSplitBlobUrl(unittest.TestCase):
    def test_azurite_docker_internal_host(self):
        # The case that motivated the helper in the first place: the
        # azure-storage-blob SDK's BlobClient.from_blob_url misparses
        # hosts other than localhost/127.0.0.1/*.blob.core.windows.net.
        container, blob = split_blob_url(
            "http://azurite:10000/devstoreaccount1/data/some/path/file.gpkg?sv=x"
        )
        self.assertEqual(container, "data")
        self.assertEqual(blob, "some/path/file.gpkg")

    def test_azurite_localhost(self):
        container, blob = split_blob_url(
            "http://localhost:10000/devstoreaccount1/data/file.gpkg?sv=x"
        )
        self.assertEqual(container, "data")
        self.assertEqual(blob, "file.gpkg")

    def test_azurite_ipv4(self):
        container, blob = split_blob_url(
            "http://127.0.0.1:10000/devstoreaccount1/data/nested/dir/file.gpkg"
        )
        self.assertEqual(container, "data")
        self.assertEqual(blob, "nested/dir/file.gpkg")

    def test_real_azure_https(self):
        container, blob = split_blob_url(
            "https://account.blob.core.windows.net/data/some/path/file.gpkg?sv=x"
        )
        self.assertEqual(container, "data")
        self.assertEqual(blob, "some/path/file.gpkg")

    def test_real_azure_single_blob(self):
        container, blob = split_blob_url(
            "https://account.blob.core.windows.net/data/file.gpkg"
        )
        self.assertEqual(container, "data")
        self.assertEqual(blob, "file.gpkg")

    def test_real_azure_short_url_raises(self):
        with self.assertRaises(ValueError):
            split_blob_url("https://account.blob.core.windows.net/data")

    def test_azurite_short_url_raises(self):
        with self.assertRaises(ValueError):
            split_blob_url("http://azurite:10000/devstoreaccount1/data")


class TestParseByteRange(unittest.TestCase):
    def test_no_header(self):
        self.assertEqual(parse_byte_range(None), (0, None, False))
        self.assertEqual(parse_byte_range(""), (0, None, False))

    def test_closed_range(self):
        # pmtiles.js' typical header read.
        self.assertEqual(parse_byte_range("bytes=0-16383"), (0, 16384, True))
        self.assertEqual(parse_byte_range("bytes=100-199"), (100, 100, True))

    def test_open_ended_range(self):
        self.assertEqual(parse_byte_range("bytes=200-"), (200, None, True))

    def test_whitespace_tolerated(self):
        self.assertEqual(parse_byte_range(" bytes=0-9 "), (0, 10, True))

    def test_suffix_range_unsupported(self):
        with self.assertRaises(ValueError):
            parse_byte_range("bytes=-500")

    def test_multi_range_unsupported(self):
        with self.assertRaises(ValueError):
            parse_byte_range("bytes=0-9,20-29")

    def test_malformed_raises(self):
        with self.assertRaises(ValueError):
            parse_byte_range("kilobytes=0-9")
        with self.assertRaises(ValueError):
            parse_byte_range("bytes=abc-def")

    def test_inverted_bounds_raise(self):
        with self.assertRaises(ValueError):
            parse_byte_range("bytes=200-100")


class TestFetchUrlText(unittest.TestCase):
    """The fallback used to recover task outputs from blob storage.

    Its contract is that it never raises: a failure here must not replace the
    original reason the compute node could not serve the file.
    """

    def _patched_requests(self, **kwargs):
        return patch.dict(
            "sys.modules", {"requests": MagicMock(**kwargs)}, clear=False
        )

    def test_returns_the_response_body(self):
        response = MagicMock(text="manifest-contents")
        requests = MagicMock()
        requests.get.return_value = response
        with self._patched_requests(get=requests.get):
            self.assertEqual(
                fetch_url_text("https://acct.blob.core.windows.net/c/b?sas"),
                "manifest-contents",
            )
        response.raise_for_status.assert_called_once()

    def test_passes_the_timeout_through(self):
        requests = MagicMock()
        requests.get.return_value = MagicMock(text="x")
        with self._patched_requests(get=requests.get):
            fetch_url_text("https://host/blob", timeout=5)
        self.assertEqual(requests.get.call_args.kwargs["timeout"], 5)

    def test_http_error_returns_none(self):
        response = MagicMock()
        response.raise_for_status.side_effect = RuntimeError("404")
        requests = MagicMock()
        requests.get.return_value = response
        with self._patched_requests(get=requests.get):
            self.assertIsNone(fetch_url_text("https://host/missing"))

    def test_transport_error_returns_none(self):
        requests = MagicMock()
        requests.get.side_effect = OSError("connection reset")
        with self._patched_requests(get=requests.get):
            self.assertIsNone(fetch_url_text("https://host/blob"))

    def test_non_http_url_is_not_fetched(self):
        requests = MagicMock()
        with self._patched_requests(get=requests.get):
            # A data layer resolving to a local filesystem path (docker dev
            # stack) must not be handed to requests.
            self.assertIsNone(fetch_url_text("/mnt/data/outputs/file.json"))
        requests.get.assert_not_called()

    def test_empty_url_returns_none(self):
        self.assertIsNone(fetch_url_text(None))
        self.assertIsNone(fetch_url_text(""))


if __name__ == "__main__":
    unittest.main()
