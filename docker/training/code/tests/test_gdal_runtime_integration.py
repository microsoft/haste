import importlib.util
import tempfile
import unittest
from pathlib import Path


class TestGdalRuntimeIntegration(unittest.TestCase):
    def test_labels_rasterize_in_process_to_tiled_big_tiff_mask(self):
        from hastegeo.core.utils.gdal_security import harden_gdal

        harden_gdal()
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import box

        import create_masks

        labels = gpd.GeoDataFrame(
            {"class": ["Damaged", "Destroyed"]},
            geometry=[
                box(0, 0, 2, 2),
                box(2, 0, 4, 2),
            ],
            crs="EPSG:3857",
        )
        profile = {
            "driver": "GTiff",
            "height": 4,
            "width": 4,
            "count": 1,
            "dtype": "uint8",
            "crs": "EPSG:3857",
            "transform": from_origin(0, 4, 1, 1),
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "mask.tif"
            create_masks.rasterize_class_mask(
                labels,
                ["Damaged", "Destroyed"],
                {"Damaged": 1, "Destroyed": 2},
                profile,
                str(output),
            )
            with rasterio.open(output) as mask:
                data = mask.read(1)
                self.assertEqual(mask.count, 1)
                self.assertEqual(mask.nodata, 0)
                self.assertEqual(mask.crs.to_epsg(), 3857)
                self.assertEqual(mask.transform, from_origin(0, 4, 1, 1))
                self.assertTrue(mask.is_tiled)
                self.assertEqual(mask.compression.name.casefold(), "lzw")

        expected = np.zeros((4, 4), dtype=np.uint8)
        expected[2:, :2] = 1
        expected[2:, 2:] = 2
        np.testing.assert_array_equal(data, expected)

    @unittest.skipUnless(
        importlib.util.find_spec("osgeo"),
        "requires GDAL's Python bindings",
    )
    def test_visualizer_conversion_uses_in_process_cog_translate(self):
        from hastegeo.core.utils.gdal_security import harden_gdal

        harden_gdal()
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        import run_workflow

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.tif"
            destination = Path(temporary) / "output.tif"
            with rasterio.open(
                source,
                "w",
                driver="GTiff",
                height=4,
                width=4,
                count=1,
                dtype="uint8",
                crs="EPSG:3857",
                transform=from_origin(0, 4, 1, 1),
            ) as dataset:
                dataset.write(np.ones((4, 4), dtype=np.uint8), 1)

            run_workflow.translate_to_cog(
                str(source),
                str(destination),
                "-co COMPRESS=DEFLATE -of COG",
            )

            with rasterio.open(destination) as translated:
                self.assertEqual(
                    translated.tags(ns="IMAGE_STRUCTURE").get("LAYOUT"),
                    "COG",
                )
                self.assertEqual(
                    translated.tags(ns="IMAGE_STRUCTURE").get("COMPRESSION"),
                    "DEFLATE",
                )


if __name__ == "__main__":
    unittest.main()
