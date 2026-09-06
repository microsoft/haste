# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.blob.

``split_blob_url`` and ``parse_byte_range`` are pure helpers. ``fetch_url_text``
uses mocked HTTP: its default best-effort behavior is preserved, while strict
required-output reads distinguish missing files from retrieval failures.

The async download_blob_to_tempfile helper isn't covered here because it
needs a live blob backend (Azurite); the integration is exercised by the
existing test_artifacts.py.
"""

import unittest
from unittest.mock import MagicMock, patch

import requests
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
    """Default reads remain best effort; strict reads enable worker retries."""

    def test_returns_the_response_body(self) -> None:
        response = MagicMock(text="manifest-contents")
        with patch("requests.get", return_value=response):
            self.assertEqual(
                fetch_url_text("https://acct.blob.core.windows.net/c/b?sas"),
                "manifest-contents",
            )
        response.raise_for_status.assert_called_once()

    def test_passes_the_timeout_through(self) -> None:
        with patch("requests.get", return_value=MagicMock(text="x")) as get:
            fetch_url_text("https://host/blob", timeout=5)
        self.assertEqual(get.call_args.kwargs["timeout"], 5)

    def test_http_error_returns_none_by_default(self) -> None:
        for status in (404, 403, 429, 503):
            response = requests.Response()
            response.status_code = status
            with self.subTest(status=status):
                with patch("requests.get", return_value=response):
                    self.assertIsNone(fetch_url_text("https://host/blob"))

    def test_transport_error_returns_none_by_default(self) -> None:
        for error in (requests.Timeout(), OSError("connection reset")):
            with patch("requests.get", side_effect=error):
                self.assertIsNone(fetch_url_text("https://host/blob"))

    def test_strict_returns_the_response_body(self) -> None:
        response = requests.Response()
        response.status_code = 200
        response._content = b"manifest-contents"
        with patch("requests.get", return_value=response):
            self.assertEqual(
                fetch_url_text("https://host/blob", strict=True),
                "manifest-contents",
            )

    def test_strict_missing_blob_returns_none(self) -> None:
        response = requests.Response()
        response.status_code = 404
        with patch("requests.get", return_value=response):
            self.assertIsNone(
                fetch_url_text("https://host/missing", strict=True)
            )

    def test_strict_other_http_errors_propagate(self) -> None:
        for status in (403, 429, 500, 503):
            response = requests.Response()
            response.status_code = status
            with self.subTest(status=status):
                with patch("requests.get", return_value=response):
                    with self.assertRaises(requests.HTTPError):
                        fetch_url_text("https://host/blob", strict=True)

    def test_strict_transport_and_unexpected_errors_propagate(self) -> None:
        for error in (
            requests.Timeout(),
            requests.ConnectionError(),
            ValueError("unexpected"),
        ):
            with patch("requests.get", side_effect=error):
                with self.assertRaises(type(error)) as raised:
                    fetch_url_text("https://host/blob", strict=True)
                self.assertIs(raised.exception, error)

    def test_absent_or_non_http_url_is_not_fetched(self) -> None:
        # Local filesystem paths are not handed to requests in either mode.
        with patch("requests.get") as get:
            for strict in (False, True):
                for url in (None, "", "/mnt/data/outputs/file.json"):
                    self.assertIsNone(fetch_url_text(url, strict=strict))
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
