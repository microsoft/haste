# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for imagery utility source-specific behavior."""

import unittest
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
            patch(
                "hastegeo.core.utils.imagery.gdal.Open",
                return_value=dataset,
            ),
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


if __name__ == "__main__":
    unittest.main()
