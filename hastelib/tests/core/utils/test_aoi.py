# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.aoi helpers.

``extract_aoi_polygon`` itself reads GeoTIFFs and is exercised by the
imageryprep workflow tests that mock it out; here we cover the simpler
``save_polygon_as_geojson`` helper directly so the file shape stays
stable for the UI's "Download Valid Area Mask" feature.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import shapely.geometry
from hastegeo.core.utils.aoi import (
    raster_extent_feature,
    save_polygon_as_geojson,
)


class TestSavePolygonAsGeojson(unittest.TestCase):
    """Unit tests for ``save_polygon_as_geojson``."""

    def _polygon(self):
        return shapely.geometry.Polygon(
            [(-1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (-1.0, 1.0)]
        )

    def test_writes_featurecollection_with_polygon_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "mask.geojson")
            returned = save_polygon_as_geojson(self._polygon(), out)
            self.assertEqual(returned, out)
            self.assertTrue(os.path.exists(out))

            with open(out) as f:
                fc = json.load(f)

            self.assertEqual(fc["type"], "FeatureCollection")
            self.assertEqual(len(fc["features"]), 1)
            feat = fc["features"][0]
            self.assertEqual(feat["type"], "Feature")
            self.assertEqual(feat["geometry"]["type"], "Polygon")
            # First coordinate matches what we passed in.
            ring = feat["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], [-1.0, 0.0])
            self.assertEqual(feat["properties"], {})

    def test_properties_are_written_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "mask.geojson")
            save_polygon_as_geojson(
                self._polygon(),
                out,
                properties={"source": "post_event_mosaic"},
            )
            with open(out) as f:
                fc = json.load(f)
            self.assertEqual(
                fc["features"][0]["properties"]["source"],
                "post_event_mosaic",
            )


class TestRasterDisplayExtent(unittest.TestCase):
    def test_extent_reads_only_raster_headers_without_scanning_a_mask(
        self,
    ) -> None:
        source = Mock(crs="EPSG:4326", bounds=(-1.0, 0.0, 1.0, 2.0))
        with patch("hastegeo.core.utils.aoi.rasterio.open") as open_raster:
            open_raster.return_value.__enter__.return_value = source
            feature = raster_extent_feature("fixture.tif")
        self.assertEqual(feature["bbox"], [-1.0, 0.0, 1.0, 2.0])
        self.assertEqual(feature["geometry"]["type"], "Polygon")
        source.read.assert_not_called()

    def test_missing_crs_is_not_a_success_shaped_empty_extent(self) -> None:
        with patch("hastegeo.core.utils.aoi.rasterio.open") as open_raster:
            open_raster.return_value.__enter__.return_value = Mock(crs=None)
            with self.assertRaisesRegex(ValueError, "coordinate reference"):
                raster_extent_feature("fixture.tif")


if __name__ == "__main__":
    unittest.main()
