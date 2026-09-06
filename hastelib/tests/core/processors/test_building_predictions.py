# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Exercise the local interactive producer with real GDAL vector files."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import fiona
from hastegeo.core.processors.building_predictions import (
    BuildingPredictionArtifacts,
    write_building_predictions,
)
from hastegeo.core.utils.predictions import FootprintPredictionMismatchError
from shapely.geometry import box, mapping, shape


class BuildingPredictionsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.footprints = os.path.join(self.directory, "footprints.gpkg")
        self.gpkg = os.path.join(self.directory, "predictions.gpkg")
        self.attrs = os.path.join(self.directory, "attributes.json")
        self.geometries = [box(0, 0, 10, 10), box(20, 0, 30, 10)]
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:6933",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
        ) as dst:
            for index, geometry in enumerate(self.geometries):
                dst.write(
                    {
                        "geometry": mapping(geometry),
                        "properties": {"id": f"source-{index}"},
                    }
                )

    def write(
        self, predictions: list, revision: str = "first"
    ) -> BuildingPredictionArtifacts:
        return write_building_predictions(
            self.footprints,
            predictions,
            self.gpkg,
            self.attrs,
            prediction_revision=revision,
        )

    def test_out_of_order_input_preserves_source_ids_geometry_and_crs(
        self,
    ) -> None:
        result = self.write(
            [
                {"id": 1, "damaged": 1, "overtureId": "source-1"},
                {"id": 0, "damaged": 0},
            ]
        )
        self.assertEqual(result.count, 2)
        self.assertEqual(result.gpkg_path, self.gpkg)
        self.assertEqual(result.attrs_path, self.attrs)
        self.assertEqual(result.payload["flavor"], "embedding")
        with fiona.open(self.gpkg, layer="predictions") as src:
            self.assertEqual(src.crs.to_epsg(), 6933)
            rows = list(src)
        self.assertEqual([row["properties"]["id"] for row in rows], [0, 1])
        self.assertEqual(
            [row["properties"]["overture_id"] for row in rows],
            ["source-0", "source-1"],
        )
        self.assertEqual(
            [row["properties"]["damaged"] for row in rows], [0, 1]
        )
        for index, row in enumerate(rows):
            self.assertTrue(
                shape(row["geometry"]).equals(self.geometries[index])
            )
            self.assertAlmostEqual(row["properties"]["area"], 100.0)
        with open(self.attrs, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), result.payload)

    def test_all_undamaged_is_a_full_prediction_not_clear(self) -> None:
        result = self.write([{"id": i, "damaged": 0} for i in range(2)])
        self.assertEqual(result.count, 2)
        self.assertEqual(result.payload["classes"], ["NotDamaged"] * 2)

    def test_cloud_class_takes_precedence_over_damage(self) -> None:
        result = self.write(
            [{"id": 0, "damaged": 1, "unknown": 0.2}, {"id": 1, "damaged": 0}]
        )
        self.assertEqual(result.payload["classes"], ["Unknown", "NotDamaged"])

    def test_clear_partial_duplicate_and_bad_ids_are_rejected(self) -> None:
        for rows in (
            [],
            [{"id": 0, "damaged": 1}],
            [{"id": 0, "damaged": 1}, {"id": 0, "damaged": 0}],
            [{"id": -1, "damaged": 0}, {"id": 1, "damaged": 0}],
            [{"id": 2, "damaged": 0}, {"id": 1, "damaged": 0}],
            [{"id": "0", "damaged": 0}, {"id": 1, "damaged": 0}],
            [{"id": 0.0, "damaged": 0}, {"id": 1, "damaged": 0}],
            [{"id": False, "damaged": 0}, {"id": 1, "damaged": 0}],
            [None, {"id": 1, "damaged": 0}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.write(rows)
            self.assertFalse(os.path.exists(self.gpkg))
            self.assertFalse(os.path.exists(self.attrs))

    def test_bad_score_values_are_not_coerced(self) -> None:
        for field, value in (
            ("damaged", None),
            ("damaged", 2),
            ("damaged", True),
            ("damaged", 1.5),
            ("damaged", "1"),
            ("unknown", None),
            ("unknown", True),
            ("unknown", "0.5"),
            ("unknown", -0.1),
            ("unknown", 1.1),
            ("unknown", float("nan")),
            ("unknown", float("inf")),
        ):
            rows = [{"id": 0, "damaged": 0}, {"id": 1, "damaged": 0}]
            rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                ValueError
            ):
                self.write(rows)
            self.assertFalse(os.path.exists(self.gpkg))

    def test_mismatched_explicit_overture_id_fails(self) -> None:
        with self.assertRaises(FootprintPredictionMismatchError):
            self.write(
                [
                    {"id": 0, "damaged": 0, "overtureId": "source-1"},
                    {"id": 1, "damaged": 0},
                ]
            )

    def test_input_output_alias_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            write_building_predictions(
                self.footprints,
                [],
                self.footprints,
                self.attrs,
                prediction_revision="revision",
            )
        with fiona.open(self.footprints) as src:
            self.assertEqual(len(src), 2)

    def test_new_generation_has_new_attributes(self) -> None:
        first = self.write([{"id": i, "damaged": 0} for i in range(2)])
        self.gpkg = os.path.join(self.directory, "second.gpkg")
        self.attrs = os.path.join(self.directory, "second.json")
        second = self.write(
            [{"id": i, "damaged": 1} for i in range(2)], revision="second"
        )
        self.assertEqual(first.payload["predictionRevision"], "first")
        self.assertEqual(second.payload["predictionRevision"], "second")
        self.assertEqual(second.payload["classes"], ["Damaged"] * 2)
        with open(first.attrs_path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["classes"], ["NotDamaged"] * 2)

    def test_sidecar_failure_does_not_return_success(self) -> None:
        with patch(
            "hastegeo.core.processors.building_predictions.write_prediction_attrs",
            side_effect=OSError("local disk full"),
        ), self.assertRaises(OSError):
            self.write([{"id": i, "damaged": 0} for i in range(2)])

    def test_empty_footprint_layer_writes_valid_zero_count_artifacts(
        self,
    ) -> None:
        fiona.remove(self.footprints, driver="GPKG")
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:6933",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
        ):
            pass
        result = self.write([])
        self.assertEqual(result.count, 0)
        self.assertEqual(result.payload["n"], 0)
        self.assertEqual(result.payload["classes"], [])
        with fiona.open(self.gpkg, layer="predictions") as src:
            self.assertEqual(len(src), 0)
            self.assertEqual(src.crs.to_epsg(), 6933)
