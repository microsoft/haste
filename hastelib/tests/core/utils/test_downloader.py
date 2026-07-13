# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for ImageryDownloader.download_imagery_from_urls hardening.

Covers the SSRF/redirect refusal and the streaming size cap. The module
imports the Azure/AWS SDKs, so the whole module is skipped where those are
unavailable (the suite runs them in the conda/hatch env or Docker image).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from hastegeo.core.utils.downloader import ImageryDownloader

    _HAS_DEPS = True
except Exception:  # pragma: no cover - deps missing on a bare host
    _HAS_DEPS = False


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [b"ok-data"]
        self.closed = False

    def iter_content(self, chunk_size=1):
        for c in self._chunks:
            yield c

    def close(self):
        self.closed = True


@unittest.skipUnless(_HAS_DEPS, "requires azure/boto3 SDKs")
class TestDownloadImageryFromUrls(unittest.TestCase):
    AZ = "https://acct.blob.core.windows.net/c/img.tif"

    def setUp(self):
        self.dst = tempfile.mkdtemp()
        self.dl = ImageryDownloader(sourceType="other")

    def _files(self):
        return sorted(os.listdir(self.dst))

    @patch("hastegeo.core.utils.downloader.requests.get")
    def test_refuses_cross_host_redirect(self, mock_get):
        mock_get.return_value = _FakeResponse(
            status_code=302, headers={"Location": "http://169.254.169.254/"}
        )
        out = self.dl.download_imagery_from_urls([self.AZ], self.dst)
        self.assertEqual(out, [])
        self.assertEqual(self._files(), [])

    @patch("hastegeo.core.utils.downloader.requests.get")
    def test_size_cap_via_content_length(self, mock_get):
        mock_get.return_value = _FakeResponse(
            status_code=200, headers={"Content-Length": str(10**12)}
        )
        with patch(
            "hastegeo.core.utils.downloader.max_download_bytes",
            return_value=1024,
        ):
            out = self.dl.download_imagery_from_urls([self.AZ], self.dst)
        self.assertEqual(out, [])
        self.assertEqual(self._files(), [])

    @patch("hastegeo.core.utils.downloader.requests.get")
    def test_size_cap_mid_stream_removes_partial(self, mock_get):
        big = [b"x" * 1024] * 8  # 8 KiB, no Content-Length header
        mock_get.return_value = _FakeResponse(status_code=200, chunks=big)
        with patch(
            "hastegeo.core.utils.downloader.max_download_bytes",
            return_value=2048,
        ):
            out = self.dl.download_imagery_from_urls([self.AZ], self.dst)
        self.assertEqual(out, [])
        self.assertEqual(self._files(), [])  # partial cleaned up

    @patch("hastegeo.core.utils.downloader.requests.get")
    def test_happy_path_writes_file(self, mock_get):
        mock_get.return_value = _FakeResponse(
            status_code=200, chunks=[b"II*\x00", b"payload"]
        )
        out = self.dl.download_imagery_from_urls([self.AZ], self.dst)
        self.assertEqual(len(out), 1)
        self.assertEqual(self._files(), ["img.tif"])

    @patch("hastegeo.core.utils.downloader.requests.get")
    def test_non_allowlisted_host_skipped(self, mock_get):
        out = self.dl.download_imagery_from_urls(
            ["https://evil.example.com/x.tif"], self.dst
        )
        self.assertEqual(out, [])
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
