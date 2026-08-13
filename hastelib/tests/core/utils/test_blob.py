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

import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.utils.blob import (
    fetch_url_text,
    parse_byte_range,
    split_blob_url,
)


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
