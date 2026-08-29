import os
import tempfile
import unittest

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import box

from hastegeo.core.publishing.raster import (
    DAMAGED_VALUE,
    DAMAGE_CLASS_NODATA,
    UNDAMAGED_VALUE,
    rasterize_damage_cog,
)

# A ~small AOI near the equator (degrees); two buildings inside it.
AOI = box(-67.10, 10.40, -67.099, 10.401)
DAMAGED_BLDG = box(-67.0999, 10.4001, -67.0997, 10.4003)
INTACT_BLDG = box(-67.0995, 10.4005, -67.0993, 10.4007)


def _aoi_gdf():
    return gpd.GeoDataFrame(geometry=[AOI], crs="EPSG:4326")


def _buildings_gdf():
    return gpd.GeoDataFrame(
        {"predicted_damage": [1, 0]},
        geometry=[DAMAGED_BLDG, INTACT_BLDG],
        crs="EPSG:4326",
    )


class TestRasterizeDamageCog(unittest.TestCase):
    def test_writes_readable_cog_with_expected_classes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "damage_class.tif")
            result = rasterize_damage_cog(
                _buildings_gdf(), _aoi_gdf(), out, target_meters=1.0
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.total_buildings, 2)
            self.assertEqual(result.damaged_buildings, 1)
            self.assertFalse(result.coarsened)
            self.assertTrue(os.path.exists(out))

            with rasterio.open(out) as ds:
                self.assertEqual(ds.count, 1)
                self.assertEqual(ds.dtypes[0], "uint8")
                self.assertEqual(ds.nodata, DAMAGE_CLASS_NODATA)
                # COG-style: internally tiled (overviews only appear once the
                # raster is larger than the overview threshold, so not asserted
                # for this tiny fixture).
                self.assertTrue(ds.profile.get("tiled", False))
                band = ds.read(1)

            values = set(np.unique(band).tolist())
            self.assertIn(DAMAGED_VALUE, values)
            self.assertIn(UNDAMAGED_VALUE, values)
            self.assertIn(DAMAGE_CLASS_NODATA, values)
            # Most of the AOI is empty -> nodata dominates.
            self.assertGreater((band == DAMAGE_CLASS_NODATA).sum(), (band != DAMAGE_CLASS_NODATA).sum())

    def test_larger_raster_builds_cog_overviews(self) -> None:
        # A ~1 km AOI at 1 m exceeds the overview threshold, so the COG driver
        # builds internal overviews (what makes it efficient for TiTiler).
        big_aoi = gpd.GeoDataFrame(
            geometry=[box(-67.10, 10.40, -67.090, 10.410)], crs="EPSG:4326"
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "damage_class.tif")
            result = rasterize_damage_cog(
                _buildings_gdf(), big_aoi, out, target_meters=1.0
            )
            self.assertIsNotNone(result)
            self.assertGreater(min(result.width, result.height), 512)
            with rasterio.open(out) as ds:
                self.assertTrue(ds.overviews(1))

    def test_coarsens_past_pixel_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "damage_class.tif")
            result = rasterize_damage_cog(
                _buildings_gdf(),
                _aoi_gdf(),
                out,
                target_meters=0.01,  # would be huge; force coarsening
                max_pixels_per_side=64,
            )
            self.assertIsNotNone(result)
            self.assertTrue(result.coarsened)
            self.assertLessEqual(max(result.width, result.height), 64)

    def test_returns_none_without_buildings(self) -> None:
        empty = _buildings_gdf().iloc[0:0]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "damage_class.tif")
            self.assertIsNone(
                rasterize_damage_cog(empty, _aoi_gdf(), out)
            )
            self.assertFalse(os.path.exists(out))

    def test_returns_none_without_aoi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "damage_class.tif")
            self.assertIsNone(
                rasterize_damage_cog(
                    _buildings_gdf(), _aoi_gdf().iloc[0:0], out
                )
            )


if __name__ == "__main__":
    unittest.main()
