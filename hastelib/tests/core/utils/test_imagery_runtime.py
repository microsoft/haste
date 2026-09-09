# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Offline native-library coverage for imagery workers on supported bases."""

import tempfile
import unittest
from pathlib import Path

import cv2
import fiona
import geopandas as gpd
import numpy as np
import rasterio
from hastegeo.core.utils.gdal_security import harden_gdal
from hastegeo.core.utils.imagery import ImageryUtils
from osgeo import gdal
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import box


class ImageryRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        harden_gdal()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.pixels = np.stack(
            [
                np.full((64, 64), value, dtype=np.uint8)
                for value in (40, 80, 120)
            ]
        )
        self.source = self._write_raster("source.tif", -100.0, self.pixels)

    def _write_raster(
        self, name: str, west: float, pixels: np.ndarray
    ) -> Path:
        path = self.directory / name
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=64,
            height=64,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(west, 50.0, 0.001, 0.001),
            photometric="RGB",
            nodata=0,
        ) as dataset:
            dataset.write(pixels)
        return path

    def test_rgb_cog_preserves_pixels_crs_and_compression(self) -> None:
        output = self.directory / "rgb.tif"
        result = ImageryUtils.convert_to_rgb_cog(
            str(self.source),
            str(output),
            gdal_translate_params="COMPRESS=LZW BLOCKSIZE=256",
            source_type="rgb/no_processing",
        )

        self.assertEqual(result, str(output))
        with rasterio.open(output) as dataset:
            self.assertEqual(dataset.crs.to_epsg(), 4326)
            self.assertEqual(dataset.count, 3)
            self.assertEqual(dataset.compression.name.lower(), "lzw")
            self.assertEqual(
                dataset.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG"
            )
            self.assertTrue(dataset.is_tiled)
            np.testing.assert_array_equal(dataset.read(), self.pixels)

    def test_mosaic_combines_adjacent_rasters(self) -> None:
        right_pixels = np.full((3, 64, 64), 180, dtype=np.uint8)
        right = self._write_raster("right.tif", -99.936, right_pixels)
        output = self.directory / "mosaic.tif"
        result = ImageryUtils.mosaic_imagery(
            [str(self.source), str(right)],
            str(output),
            gdal_warp_params="-of COG -co COMPRESS=LZW -r near",
        )

        self.assertEqual(result, str(output))
        with rasterio.open(output) as dataset:
            self.assertEqual((dataset.width, dataset.height), (128, 64))
            self.assertEqual(dataset.crs.to_epsg(), 4326)
            np.testing.assert_array_equal(
                dataset.read()[:, :, :64], self.pixels
            )
            np.testing.assert_array_equal(
                dataset.read()[:, :, 64:], right_pixels
            )

    def test_mosaic_reprojects_using_native_proj_data(self) -> None:
        output = self.directory / "projected.tif"
        result = ImageryUtils.mosaic_imagery(
            [str(self.source)],
            str(output),
            gdal_warp_params="-of COG -t_srs EPSG:3857 -r near",
        )

        self.assertEqual(result, str(output))
        with rasterio.open(self.source) as source:
            expected = transform_bounds(
                source.crs, "EPSG:3857", *source.bounds
            )
        with rasterio.open(output) as dataset:
            self.assertEqual(dataset.crs.to_epsg(), 3857)
            self.assertGreater(dataset.width, 0)
            self.assertGreater(dataset.height, 0)
            self.assertTrue(dataset.read().any())
            tolerance = max(abs(dataset.transform.a), abs(dataset.transform.e))
            for actual, target in zip(dataset.bounds, expected):
                self.assertAlmostEqual(actual, target, delta=tolerance)

    def test_jpeg_preview_is_readable_by_opencv(self) -> None:
        output = self.directory / "preview.jpg"
        result = ImageryUtils.convert_tif_to_jpeg(
            str(self.source), str(output), source_type="rgb/no_processing"
        )

        self.assertEqual(result, str(output))
        image = cv2.imread(str(output))
        self.assertIsNotNone(image)
        self.assertEqual(image.shape, (64, 64, 3))
        self.assertTrue(image.any())

    def test_vector_geopackage_and_parquet_round_trip(self) -> None:
        expected = gpd.GeoDataFrame(
            {"id": [1], "geometry": [box(-100, 49.9, -99.9, 50)]},
            crs="EPSG:4326",
        )
        gpkg = self.directory / "footprints.gpkg"
        parquet = self.directory / "footprints.parquet"
        expected.to_file(gpkg, driver="GPKG", engine="fiona")
        expected.to_parquet(parquet)

        with fiona.open(gpkg) as source:
            self.assertEqual(len(source), 1)
            self.assertEqual(source.driver, "GPKG")
        for actual in (
            gpd.read_file(gpkg, engine="fiona"),
            gpd.read_parquet(parquet),
        ):
            self.assertEqual(actual.crs.to_epsg(), 4326)
            self.assertEqual(actual["id"].tolist(), [1])
            self.assertTrue(
                actual.geometry.iloc[0].equals(expected.geometry.iloc[0])
            )

    def test_blocked_gdal_drivers_remain_disabled(self) -> None:
        for name in ("HDF4", "HDF4Image", "HDF5", "HDF5Image", "netCDF"):
            with self.subTest(driver=name):
                self.assertIsNone(gdal.GetDriverByName(name))


if __name__ == "__main__":
    unittest.main()
