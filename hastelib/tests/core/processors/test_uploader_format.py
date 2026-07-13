# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for FileUploader._resolve_data_format.

The chunked-upload endpoint accepts an optional ``data_format`` form
field; the resolver normalizes the value and rejects anything outside
the strict allowlist so a hostile client cannot smuggle arbitrary file
extensions through the blob-path construction.
"""

import unittest
from unittest.mock import patch


def _make_uploader():
    """Construct a FileUploader with all I/O dependencies stubbed."""
    from hastegeo.core.config import Config

    # Patch the heavy collaborators so we never actually init storage.
    with patch(
        "hastegeo.core.processors.uploader.UnifiedDataLayer",
        autospec=True,
    ):
        from hastegeo.core.processors.uploader import FileUploader

        cfg = Config()
        # Ensure DATA_DIR is set so FileUploader.__init__ accepts it.
        cfg.DATA_DIR = "/tmp/uploader-test"
        return FileUploader(project_id="proj-1", config=cfg)


class TestResolveDataFormat(unittest.TestCase):
    def test_default_none_returns_tif(self):
        u = _make_uploader()
        self.assertEqual(u._resolve_data_format(None), "tif")

    def test_tif_tiff_geotiff_normalize_to_tif(self):
        u = _make_uploader()
        for v in ("tif", "TIF", "tiff", "TIFF", "geotiff", "GeoTIFF"):
            with self.subTest(v=v):
                self.assertEqual(u._resolve_data_format(v), "tif")

    def test_gpkg_accepted(self):
        u = _make_uploader()
        for v in ("gpkg", "GPKG", "  gpkg  "):
            with self.subTest(v=v):
                self.assertEqual(u._resolve_data_format(v), "gpkg")

    def test_rejects_unknown_format(self):
        u = _make_uploader()
        for v in ("zip", "shp", "json", "tif/../etc/passwd"):
            with self.subTest(v=v):
                with self.assertRaises(ValueError):
                    u._resolve_data_format(v)


class TestUploadSizeAndContentChecks(unittest.TestCase):
    """Size cap + magic-byte type checks at the upload boundary."""

    def _uploader_with_tmpdir(self):
        import tempfile

        u = _make_uploader()
        u.temp_dir = tempfile.mkdtemp()
        return u

    def _write_chunk(self, u, file_id, n, data):
        import os

        path = os.path.join(u.temp_dir, f"{file_id}_chunk_{n}")
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_cumulative_size_limit_rejects_and_cleans_up(self):
        import os

        u = self._uploader_with_tmpdir()
        self._write_chunk(u, "f1", 0, b"a" * 60)
        self._write_chunk(u, "f1", 1, b"b" * 60)
        with self.assertRaises(ValueError):
            u._enforce_cumulative_size_limit("f1", max_bytes=100)
        # Offending chunks are removed.
        self.assertEqual(
            [p for p in os.listdir(u.temp_dir) if p.startswith("f1_")], []
        )

    def test_cumulative_size_limit_allows_within_cap(self):
        u = self._uploader_with_tmpdir()
        self._write_chunk(u, "f2", 0, b"a" * 40)
        # Under the cap → no raise.
        u._enforce_cumulative_size_limit("f2", max_bytes=100)

    def test_content_matches_declared_accepts_tiff(self):
        u = self._uploader_with_tmpdir()
        self._write_chunk(u, "f3", 0, b"II*\x00" + b"\x00" * 80)
        u._assert_content_matches_declared("f3", "tif")  # no raise

    def test_content_mismatch_rejected(self):
        u = self._uploader_with_tmpdir()
        # GPKG bytes declared as tif must be rejected before GDAL parses.
        gpkg = b"SQLite format 3\x00" + b"\x00" * (68 - 16) + b"GPKG"
        self._write_chunk(u, "f4", 0, gpkg)
        with self.assertRaises(ValueError):
            u._assert_content_matches_declared("f4", "tif")

    def test_content_check_skipped_when_no_local_chunk(self):
        u = self._uploader_with_tmpdir()
        # No chunk_0 staged → skip rather than block a legitimate finalize.
        u._assert_content_matches_declared("absent", "tif")  # no raise


if __name__ == "__main__":
    unittest.main()
