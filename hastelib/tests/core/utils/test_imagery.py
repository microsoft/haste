# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for imagery utility source-specific behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from hastegeo.core.utils.imagery import ImageryUtils


class TestGetScaleImageryParams(unittest.TestCase):
    def test_rgb_no_processing_uses_default_percentiles(self):
        dataset = MagicMock()
        dataset.__enter__.return_value = dataset
        dataset.RasterCount = 3
        dataset.GetRasterBand.return_value.ReadAsArray.return_value = np.array(
            [0, 1, 2]
        )

        with (
            patch.object(ImageryUtils, "open_gtiff", return_value=dataset),
            patch(
                "hastegeo.core.utils.imagery.np.percentile",
                side_effect=lambda _, percentile: percentile,
            ) as mock_percentile,
        ):
            result = ImageryUtils.get_scale_imagery_params(
                "image.tif", "rgb/no_processing"
            )

        self.assertEqual(
            result,
            [
                [2, 98, 0, 255],
                [2, 98, 0, 255],
                [2, 98, 0, 255],
            ],
        )
        self.assertEqual(
            [call.args[1] for call in mock_percentile.call_args_list],
            [2, 98, 2, 98, 2, 98],
        )


class TestGetRgbBandIndexes(unittest.TestCase):
    """The Vantor band mapping must be reachable from both source-type keys.

    ``sourceTypePostEvent`` is persisted per image layer, so layers created
    before the Maxar -> Vantor rename still pass ``"maxar"`` here. If the
    alias regressed, those layers would fall through to the GDAL
    colour-interpretation fallback instead of the explicit mapping --
    silently, with no error.
    """

    @staticmethod
    def _band_indexes(source_type, num_bands):
        dataset = MagicMock()
        dataset.__enter__.return_value = dataset
        dataset.RasterCount = num_bands

        with patch.object(ImageryUtils, "open_gtiff", return_value=dataset):
            return ImageryUtils.get_rgb_band_indexes("image.tif", source_type)

    def test_vantor_matches_legacy_maxar_for_supported_band_counts(self):
        for num_bands in (3, 4, 8):
            with self.subTest(num_bands=num_bands):
                self.assertEqual(
                    self._band_indexes("vantor", num_bands),
                    self._band_indexes("maxar", num_bands),
                )

    def test_vantor_band_mappings(self):
        # Visual RGB, 4-band (BGR + NIR1) and 8-band orderings per the
        # provider band spec referenced in get_rgb_band_indexes.
        self.assertEqual(self._band_indexes("vantor", 3), [1, 2, 3])
        self.assertEqual(self._band_indexes("vantor", 4), [3, 2, 1])
        self.assertEqual(self._band_indexes("vantor", 8), [4, 3, 1])

    def test_legacy_maxar_still_resolves_to_the_vantor_mapping(self):
        self.assertEqual(self._band_indexes("maxar", 3), [1, 2, 3])
        self.assertEqual(self._band_indexes("maxar", 4), [3, 2, 1])
        self.assertEqual(self._band_indexes("maxar", 8), [4, 3, 1])


class TestOpenGtiff(unittest.TestCase):
    def test_vrt_bytes_disguised_as_tiff_are_rejected_before_gdal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disguised.tif"
            path.write_text("<VRTDataset/>", encoding="utf-8")
            with patch("hastegeo.core.utils.imagery.gdal.OpenEx") as open_ex:
                with self.assertRaisesRegex(
                    ValueError, "does not match the declared format"
                ):
                    ImageryUtils.open_gtiff(str(path))

        open_ex.assert_not_called()

    def test_tiff_open_is_limited_to_gtiff_driver(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.tif"
            path.write_bytes(b"II*\x00" + b"\x00" * 68)
            dataset = MagicMock()
            dataset.__enter__.return_value = dataset
            with patch(
                "hastegeo.core.utils.imagery.gdal.OpenEx",
                return_value=dataset,
            ) as open_ex:
                with ImageryUtils.open_gtiff(str(path)) as actual:
                    self.assertIs(actual, dataset)

        self.assertEqual(
            open_ex.call_args.kwargs["allowed_drivers"], ["GTiff"]
        )


if __name__ == "__main__":
    unittest.main()
