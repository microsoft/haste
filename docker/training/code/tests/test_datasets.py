# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the channel handling in ``bda.datasets.TileDataset``.

``num_channels`` exists to drop an extra band (typically alpha) that the
checkpoint wasn't trained on. Slicing cannot go the other way, so a raster
with *fewer* bands than the config claims has to be rejected up front —
otherwise the short stack flows through and fails much later as a generic
convolution channel mismatch inside the model.
"""

import os
import sys
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

# The `bda` package lives in the parent directory and is not installed.
CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from bda.datasets import TileDataset  # noqa: E402


def _write_raster(path, band_count, size=16):
    """Write a small uint8 raster with `band_count` bands."""
    data = np.arange(band_count * size * size, dtype=np.uint8).reshape(
        band_count, size, size
    )
    profile = {
        "driver": "GTiff",
        "height": size,
        "width": size,
        "count": band_count,
        "dtype": "uint8",
        "crs": "EPSG:32610",
        "transform": from_origin(0, size, 1, 1),
    }
    with rasterio.open(path, "w", **profile) as f:
        f.write(data)
    return path


class TestTileDatasetChannels(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _raster(self, name, band_count):
        return _write_raster(
            os.path.join(self.tmp.name, name), band_count=band_count
        )

    def test_extra_band_is_dropped(self):
        """4-band raster, 3-channel model: the alpha band is clipped off."""
        fn = self._raster("rgba.tif", 4)
        ds = TileDataset([[fn]], mask_fns=None, num_channels=3)
        sample = ds[(0, 0, 0, 8)]
        self.assertEqual(sample["image"].shape[0], 3)

    def test_exact_match_is_unchanged(self):
        fn = self._raster("rgb.tif", 3)
        ds = TileDataset([[fn]], mask_fns=None, num_channels=3)
        sample = ds[(0, 0, 0, 8)]
        self.assertEqual(sample["image"].shape[0], 3)

    def test_none_keeps_every_band(self):
        fn = self._raster("rgba2.tif", 4)
        ds = TileDataset([[fn]], mask_fns=None, num_channels=None)
        sample = ds[(0, 0, 0, 8)]
        self.assertEqual(sample["image"].shape[0], 4)

    def test_too_few_bands_is_rejected_at_construction(self):
        """The failure must surface here, not as a model shape error later."""
        fn = self._raster("rgb2.tif", 3)
        with self.assertRaises(ValueError) as ctx:
            TileDataset([[fn]], mask_fns=None, num_channels=4)
        message = str(ctx.exception)
        self.assertIn("4", message)
        self.assertIn("3", message)

    def test_bands_are_summed_across_a_stacked_group(self):
        """Channels come from concatenating every file in the inner list."""
        a = self._raster("a.tif", 2)
        b = self._raster("b.tif", 2)
        ds = TileDataset([[a, b]], mask_fns=None, num_channels=4)
        sample = ds[(0, 0, 0, 8)]
        self.assertEqual(sample["image"].shape[0], 4)

    def test_too_few_bands_across_a_stacked_group_is_rejected(self):
        a = self._raster("a2.tif", 2)
        b = self._raster("b2.tif", 1)
        with self.assertRaises(ValueError):
            TileDataset([[a, b]], mask_fns=None, num_channels=4)


if __name__ == "__main__":
    unittest.main()
