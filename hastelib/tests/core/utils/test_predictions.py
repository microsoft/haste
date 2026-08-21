# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.predictions.

Builds tiny synthetic GeoPackages for both prediction producers (the
trained-inference merge script and the interactive building labeler) and
checks that the reader normalises them identically.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import fiona
import geopandas as gpd
from fiona.crs import CRS
from fiona.model import Feature
from hastegeo.core.utils.predictions import (
    EMBEDDING_FLAVOR,
    INFERENCE_FLAVOR,
    read_footprint_ids,
    read_predictions,
)
from shapely.geometry import Polygon

INFERENCE_SCHEMA = {
    "geometry": "MultiPolygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damage_pct_10m": "float",
        "damage_pct_20m": "float",
        "damaged": "int",
        "unknown_pct": "float",
    },
}


def square(index: int) -> Polygon:
    """Return a unit square offset along x so rows stay distinguishable."""
    x = float(index)
    return Polygon([(x, 0), (x + 1, 0), (x + 1, 1), (x, 1)])


def multipolygon_mapping(index: int) -> dict:
    x = float(index)
    ring = [(x, 0.0), (x + 1, 0.0), (x + 1, 1.0), (x, 1.0), (x, 0.0)]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def write_inference_gpkg(
    path: str,
    damage_values: list,
    unknown_values: list = None,
    layer: str = None,
    epsg: int = 32610,
) -> str:
    """Write a GeoPackage shaped like merge_with_building_footprints.py."""
    unknown_values = unknown_values or [0.0] * len(damage_values)
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs=CRS.from_epsg(epsg),
        schema=INFERENCE_SCHEMA,
        layer=layer,
    ) as dst:
        for index, damage in enumerate(damage_values):
            dst.write(
                Feature.from_dict(
                    **{
                        "type": "Feature",
                        "geometry": multipolygon_mapping(index),
                        "properties": {
                            "id": index,
                            "damage_pct_0m": damage,
                            "damage_pct_10m": damage,
                            "damage_pct_20m": damage,
                            "damaged": 1 if damage > 0 else 0,
                            "unknown_pct": unknown_values[index],
                        },
                    }
                )
            )
    return path


def write_embedding_gpkg(
    path: str,
    damaged_values: list,
    unknown_values: list = None,
    epsg: int = 4326,
) -> str:
    """Write a GeoPackage shaped like the interactive labeler's output."""
    unknown_values = unknown_values or [0.0] * len(damaged_values)
    frame = gpd.GeoDataFrame(
        {
            "id": list(range(len(damaged_values))),
            "damaged": damaged_values,
            "damage_pct_0m": [float(d) for d in damaged_values],
            "unknown_pct": unknown_values,
            "area": [100.0] * len(damaged_values),
            "geometry": [square(i) for i in range(len(damaged_values))],
        },
        crs=f"EPSG:{epsg}",
    )
    frame.to_file(path, layer="predictions", driver="GPKG")
    return path


def write_footprints_gpkg(path: str, ids: list, epsg: int = 4326) -> str:
    """Write a footprints GeoPackage carrying Overture string ids."""
    frame = gpd.GeoDataFrame(
        {
            "id": ids,
            "subtype": ["residential"] * len(ids),
            "class": ["house"] * len(ids),
            "geometry": [square(i) for i in range(len(ids))],
        },
        crs=f"EPSG:{epsg}",
    )
    frame.to_file(path, driver="GPKG")
    return path


class PredictionFixtureMixin(unittest.TestCase):
    """Temp-dir lifecycle shared by the prediction reader tests."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="haste-predictions-")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def path(self, name: str) -> str:
        return os.path.join(self.tmp_dir, name)


class TestFlavorDetection(PredictionFixtureMixin):
    def test_inference_flavor(self):
        path = write_inference_gpkg(
            self.path("inference.gpkg"), [0.0, 0.25, 0.9, 1.0]
        )

        predictions = read_predictions(path)

        self.assertEqual(predictions.flavor, INFERENCE_FLAVOR)
        self.assertTrue(predictions.supports_threshold)
        self.assertEqual(predictions.layer_name, "inference")
        self.assertEqual(len(predictions), 4)

    def test_embedding_flavor_from_layer_and_area(self):
        path = write_embedding_gpkg(
            self.path("embedding.gpkg"), [0, 1, 1, 0, 1]
        )

        predictions = read_predictions(path)

        self.assertEqual(predictions.flavor, EMBEDDING_FLAVOR)
        self.assertFalse(predictions.supports_threshold)
        self.assertEqual(predictions.layer_name, "predictions")

    def test_embedding_flavor_from_degenerate_damage_values(self):
        # Inference-shaped layer (no area column, different layer name)
        # whose damage fractions are only ever 0.0/1.0 is still the
        # labeler's degenerate output.
        path = write_inference_gpkg(
            self.path("degenerate.gpkg"), [0.0, 1.0, 1.0, 0.0]
        )

        predictions = read_predictions(path)

        self.assertEqual(predictions.flavor, EMBEDDING_FLAVOR)
        self.assertFalse(predictions.supports_threshold)

    def test_single_fractional_value_keeps_inference_flavor(self):
        path = write_inference_gpkg(
            self.path("mostly-binary.gpkg"), [0.0, 1.0, 0.5, 1.0]
        )

        predictions = read_predictions(path)

        self.assertEqual(predictions.flavor, INFERENCE_FLAVOR)

    def test_empty_layer_defaults_to_inference(self):
        path = write_inference_gpkg(self.path("empty.gpkg"), [])

        predictions = read_predictions(path)

        self.assertEqual(predictions.rows, [])
        self.assertEqual(predictions.flavor, INFERENCE_FLAVOR)


class TestReadPredictions(PredictionFixtureMixin):
    def test_rows_follow_file_order(self):
        damage = [0.9, 0.0, 0.4, 0.1, 0.75]
        path = write_inference_gpkg(self.path("ordered.gpkg"), damage)

        predictions = read_predictions(path)

        self.assertEqual(
            [row.row_index for row in predictions.rows], list(range(5))
        )
        self.assertEqual(
            [row.damage_fraction for row in predictions.rows], damage
        )

    def test_normalises_both_producers_to_same_fields(self):
        inference = read_predictions(
            write_inference_gpkg(self.path("a.gpkg"), [0.0, 0.6])
        )
        embedding = read_predictions(
            write_embedding_gpkg(self.path("b.gpkg"), [0, 1])
        )

        self.assertEqual(
            [row.damaged for row in inference.rows],
            [row.damaged for row in embedding.rows],
        )
        self.assertEqual(
            [row.unknown_fraction for row in embedding.rows], [0.0, 0.0]
        )

    def test_unknown_fraction_is_read(self):
        path = write_inference_gpkg(
            self.path("unknown.gpkg"),
            [0.0, 0.5, 0.5],
            unknown_values=[0.0, 0.3, 1.0],
        )

        predictions = read_predictions(path)

        self.assertEqual(
            [row.unknown_fraction for row in predictions.rows],
            [0.0, 0.3, 1.0],
        )

    def test_crs_is_preserved(self):
        path = write_inference_gpkg(
            self.path("crs.gpkg"), [0.0, 0.5], epsg=32610
        )

        predictions = read_predictions(path)

        self.assertEqual(predictions.crs.to_epsg(), 32610)

    def test_missing_footprints_leaves_ids_unset(self):
        path = write_inference_gpkg(self.path("noids.gpkg"), [0.0, 0.5])

        predictions = read_predictions(path)

        self.assertTrue(
            all(row.overture_id is None for row in predictions.rows)
        )

    @patch("hastegeo.core.utils.predictions.fiona.listlayers", return_value=[])
    def test_no_layers_raises(self, _listlayers):
        with self.assertRaises(ValueError) as ctx:
            read_predictions(self.path("layerless.gpkg"))

        self.assertIn("no layers", str(ctx.exception))


class TestOvertureIdResolution(PredictionFixtureMixin):
    def test_ids_resolved_positionally(self):
        overture_ids = ["ovt-a", "ovt-b", "ovt-c"]
        predictions_path = write_inference_gpkg(
            self.path("preds.gpkg"), [0.0, 0.5, 1.0]
        )
        footprints_path = write_footprints_gpkg(
            self.path("footprints.gpkg"), overture_ids
        )

        predictions = read_predictions(
            predictions_path, footprints_path=footprints_path
        )

        self.assertEqual(
            [row.overture_id for row in predictions.rows], overture_ids
        )

    def test_ids_resolved_for_embedding_flavor(self):
        overture_ids = ["ovt-1", "ovt-2"]
        predictions_path = write_embedding_gpkg(self.path("emb.gpkg"), [1, 0])
        footprints_path = write_footprints_gpkg(
            self.path("fp.gpkg"), overture_ids
        )

        predictions = read_predictions(
            predictions_path, footprints_path=footprints_path
        )

        self.assertEqual(
            [row.overture_id for row in predictions.rows], overture_ids
        )

    def test_length_mismatch_raises(self):
        predictions_path = write_inference_gpkg(
            self.path("preds.gpkg"), [0.0, 0.5, 1.0]
        )
        footprints_path = write_footprints_gpkg(
            self.path("footprints.gpkg"), ["ovt-a", "ovt-b"]
        )

        with self.assertRaises(ValueError) as ctx:
            read_predictions(predictions_path, footprints_path=footprints_path)

        message = str(ctx.exception)
        self.assertIn("2 footprints", message)
        self.assertIn("3 predictions", message)
        self.assertIn("positional", message)

    def test_footprints_without_id_column_raises(self):
        path = self.path("bad-footprints.gpkg")
        frame = gpd.GeoDataFrame(
            {"name": ["a", "b"], "geometry": [square(0), square(1)]},
            crs="EPSG:4326",
        )
        frame.to_file(path, driver="GPKG")

        with self.assertRaises(ValueError) as ctx:
            read_footprint_ids(path)

        self.assertIn("'id' column", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
