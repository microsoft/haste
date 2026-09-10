# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Native GeoPackage/COG coverage, identity and legacy regression fixtures."""

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

import fiona
import numpy as np
import rasterio
import shapely.geometry
from rasterio.transform import from_origin

CODE_DIR = str(Path(__file__).resolve().parents[1])
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import merge_with_building_footprints as merge  # noqa: E402
import output2visualizer as visualizer  # noqa: E402


class CatalogPostprocessingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.predictions = self.root / "predictions.tif"
        self.footprints = self.root / "footprints.gpkg"
        self.merged = self.root / "merged.gpkg"
        self.visualizer = self.root / "visualizer.tif"
        self.transform = from_origin(500000, 4200000, 10, 10)
        self.array = np.full((10, 10), 2, dtype=np.uint8)
        self.array[1:3, 1:3] = 3
        self.array[4:6, 4:6] = 0
        self.array[5:7, 1:3] = 1
        self.array[7:9, 7:9] = 4
        with rasterio.open(
            self.predictions,
            "w",
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="uint8",
            crs="EPSG:32610",
            transform=self.transform,
            nodata=0,
        ) as dst:
            dst.write(self.array, 1)
        self.rows = [
            (101, (1, 1, 3, 3)),  # damaged
            (809, (20, 1, 22, 3)),  # outside, between retained source ids
            (42, (4, 4, 6, 6)),  # no data; buffers would overlap observations
            (900, (8, 1, 12, 3)),  # half outside; zero damage, 50% unknown
            (77, (1, 5, 3, 7)),  # valid background
            (567, (7, 7, 9, 9)),  # legacy unknown/cloud class
        ]
        self.write_footprints()

    def write_footprints(self, string_ids=False):
        if self.footprints.exists():
            os.remove(self.footprints)
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:32610",
            schema={
                "geometry": "Polygon",
                "properties": {
                    "id": "str" if string_ids else "int",
                    "overture_id": "str",
                },
            },
        ) as dst:
            for identifier, (x0, y0, x1, y1) in self.rows:
                left, top = self.transform * (x0, y0)
                right, bottom = self.transform * (x1, y1)
                dst.write(
                    {
                        "geometry": shapely.geometry.mapping(
                            shapely.geometry.box(left, bottom, right, top)
                        ),
                        "properties": {
                            "id": (
                                f"source-{identifier}"
                                if string_ids
                                else identifier
                            ),
                            "overture_id": f"overture-{identifier}",
                        },
                    }
                )

    def run_merge(self, preserve=True):
        merge.main(
            argparse.Namespace(
                predictions_fn=str(self.predictions),
                footprints_fn=str(self.footprints),
                output_fn=str(self.merged),
                preserve_source_identity=preserve,
                overwrite=True,
            )
        )
        with fiona.open(self.merged) as src:
            return [dict(row["properties"]) for row in src]

    def run_visualizer(self):
        visualizer.main(
            argparse.Namespace(
                predictions_fn=str(self.predictions),
                merged_footprints_fn=str(self.merged),
                output_fn=str(self.visualizer),
                overwrite=True,
            )
        )

    def test_catalog_keeps_source_identity_and_unknowns(self):
        rows = self.run_merge()
        self.assertEqual(
            [row["id"] for row in rows], list(range(len(self.rows)))
        )
        self.assertEqual(
            [row["source_building_id"] for row in rows],
            [str(r[0]) for r in self.rows],
        )
        self.assertEqual(
            [row["overture_id"] for row in rows],
            [f"overture-{r[0]}" for r in self.rows],
        )
        self.assertEqual(rows[0]["damage_pct_0m"], 1)
        self.assertLess(rows[0]["damage_pct_20m"], rows[0]["damage_pct_10m"])
        for index in [1, 2, 5]:
            for suffix in ["0m", "10m", "20m"]:
                self.assertIsNone(rows[index][f"damage_pct_{suffix}"])
            self.assertIsNone(rows[index]["damaged"])
            self.assertEqual(rows[index]["unknown_pct"], 1)
        self.assertEqual(rows[3]["damage_pct_0m"], 0)
        self.assertEqual(rows[3]["unknown_pct"], 0.5)
        self.assertEqual(rows[4]["damage_pct_0m"], 0)
        self.assertEqual(rows[4]["unknown_pct"], 0)

    def test_string_identity_and_positional_id_are_both_preserved(self):
        self.write_footprints(string_ids=True)
        rows = self.run_merge()
        self.assertEqual(
            [r["source_building_id"] for r in rows],
            [f"source-{r[0]}" for r in self.rows],
        )
        self.assertEqual([r["id"] for r in rows], list(range(len(self.rows))))

    def test_source_identity_falls_back_to_fid_without_id_property(self):
        with fiona.open(self.footprints) as src:
            records = [
                {
                    "geometry": row["geometry"],
                    "properties": {},
                }
                for row in src
            ]
        self.footprints = self.root / "without_source_id.gpkg"
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:32610",
            schema={"geometry": "Polygon", "properties": {}},
        ) as dst:
            dst.writerecords(records)
        with fiona.open(self.footprints) as src:
            expected_ids = [row["id"] for row in src]
        rows = self.run_merge()
        self.assertEqual(
            [row["source_building_id"] for row in rows], expected_ids
        )
        self.assertEqual(
            [row["id"] for row in rows], list(range(len(self.rows)))
        )
        self.assertTrue(all(row["overture_id"] is None for row in rows))

    def test_legacy_default_keeps_previous_valid_pixel_behavior(self):
        rows = self.run_merge(preserve=False)
        self.assertEqual(len(rows), 5)  # old path drops the outside building
        self.assertEqual([r["id"] for r in rows], list(range(5)))
        self.assertNotIn("source_building_id", rows[0])
        self.assertEqual(rows[0]["damage_pct_0m"], 1)
        self.assertEqual(rows[1]["damage_pct_0m"], 0)  # old NoData semantics
        self.assertEqual(rows[1]["unknown_pct"], 0)
        self.assertEqual(rows[4]["unknown_pct"], 1)  # original cloud fraction

    def test_masks_are_unknown_even_when_pixel_values_look_damaged(self):
        with rasterio.open(self.predictions, "r+") as dst:
            mask = np.full((10, 10), 255, dtype=np.uint8)
            mask[1:3, 1:3] = 0
            dst.write_mask(mask)
        rows = self.run_merge()
        self.assertIsNone(rows[0]["damage_pct_0m"])
        self.assertEqual(rows[0]["unknown_pct"], 1)

    def test_partial_mask_unknown_fraction_does_not_dilute_damage(self):
        with rasterio.open(self.predictions, "r+") as dst:
            mask = np.full((10, 10), 255, dtype=np.uint8)
            mask[1, 1:3] = 0
            dst.write_mask(mask)
        rows = self.run_merge()
        self.assertEqual(rows[0]["damage_pct_0m"], 1)
        self.assertEqual(rows[0]["unknown_pct"], 0.5)

    def test_visualizer_has_no_false_intact_no_coverage(self):
        self.run_merge()
        self.run_visualizer()
        with rasterio.open(self.visualizer) as dst:
            colors = dst.read()
            self.assertEqual(dst.tags(ns="IMAGE_STRUCTURE")["LAYOUT"], "COG")
            self.assertEqual(dst.transform, self.transform)
            self.assertEqual(
                dst.colorinterp[-1], rasterio.enums.ColorInterp.alpha
            )
            self.assertTrue((colors[3, 1:3, 1:3] == 255).all())  # damaged
            self.assertTrue(
                (colors[:, 5:7, 1:3] == 255).all()
            )  # observed background
            self.assertFalse(colors[3, 4:6, 4:6].any())  # nodata
            self.assertFalse(colors[3, 7:9, 7:9].any())  # cloud
            self.assertIsNone(dst.nodata)  # alpha, not zero RGB components

    def test_all_outside_or_empty_footprints_still_generate_transparent_cog(
        self,
    ):
        for rows in [[self.rows[1]], []]:
            self.rows = rows
            self.write_footprints()
            self.run_merge()
            self.run_visualizer()
            with rasterio.open(self.visualizer) as dst:
                self.assertFalse(dst.read().any())
        self.run_merge(
            preserve=False
        )  # legacy empty summary must not index an empty array

    def test_visualizer_null_nan_and_all_unknown_are_not_class_zero(self):
        self.assertIsNone(visualizer.classify(None))
        self.assertIsNone(visualizer.classify(float("nan")))
        self.assertEqual(visualizer.classify(0), 0)
        self.assertEqual(visualizer.classify(0.2), 0)
        self.assertEqual(visualizer.classify(1), 4)

    def test_projected_feet_buffer_is_metres(self):
        crs = "EPSG:2263"
        geometry = shapely.geometry.box(980000, 190000, 980030, 190030)
        metric = merge.metric_crs_for(crs, geometry.bounds)
        self.assertEqual(metric, "EPSG:32618")
        result = merge.buffered_shape(
            shapely.geometry.mapping(geometry), crs, metric, 10
        )
        self.assertAlmostEqual(
            geometry.bounds[0] - result.bounds[0], 32.8, delta=1
        )


if __name__ == "__main__":
    unittest.main()
