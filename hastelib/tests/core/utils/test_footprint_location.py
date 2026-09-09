# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from hastegeo.core.utils.footprint_location import footprint_location
from shapely.geometry import box

from ..prediction_fixtures import write_gpkg


class TestFootprintLocation(unittest.TestCase):
    def test_exact_lookup_preserves_zero_based_row_id_without_sampling(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = write_gpkg(
                Path(directory, "footprints.gpkg"),
                [{"id": "first"}, {"id": "second"}],
                fields={"id": "str"},
                crs="EPSG:4326",
                geometries=[box(10, 20, 11, 21), box(12, 22, 13, 23)],
            )
            feature = footprint_location(path, "second")["features"][0]
            self.assertEqual(
                feature["properties"], {"id": "second", "rowId": 1}
            )
            self.assertEqual(
                feature["geometry"],
                {"type": "Point", "coordinates": [12.5, 22.5]},
            )
            with self.assertRaises(FileNotFoundError):
                footprint_location(path, "absent")

    def test_projected_footprints_return_wgs84_and_normalized_numeric_ids(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = write_gpkg(
                Path(directory, "footprints.gpkg"),
                [{"id": 42}],
                fields={"id": "int"},
                crs="EPSG:3857",
                geometries=[box(111000, 0, 112000, 1000)],
            )
            feature = footprint_location(path, "42")["features"][0]
            self.assertEqual(feature["properties"], {"id": "42", "rowId": 0})
            lon, lat = feature["geometry"]["coordinates"]
            self.assertTrue(0.9 < lon < 1.1)
            self.assertTrue(0 < lat < 0.02)

    def test_ambiguous_or_missing_geometry_is_not_a_valid_location(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory, "footprints.gpkg")
            write_gpkg(
                path, [{"id": "same"}, {"id": "same"}], fields={"id": "str"}
            )
            with self.assertRaises(ValueError):
                footprint_location(str(path), "same")
            write_gpkg(
                path, [{"id": "same"}], fields={"id": "str"}, geometries=[None]
            )
            with self.assertRaises(ValueError):
                footprint_location(str(path), "same")
