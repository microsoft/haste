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


if __name__ == "__main__":
    unittest.main()
