# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the prediction-tiles data-preparation workflow.

The workflow has two halves:

* the **attribute sidecar** builder, which is pure geospatial I/O and is
  exercised here against small synthetic GeoPackages written to a temp
  dir — in BOTH prediction flavors (trained-inference merge output and
  the interactive labeler's ``predictions`` layer);
* the **PMTiles** builder, which shells out to ``tippecanoe``. That
  binary ships only in the training docker image, so every test here
  either mocks the subprocess call or asserts on the actionable error
  raised when the binary is missing. Nothing in this file requires
  tippecanoe to be installed.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import fiona
from hastegeo.workflows import prepare_prediction_tiles as ppt
from shapely.geometry import Polygon, mapping

FOOTPRINT_SCHEMA = {
    "geometry": "Polygon",
    "properties": {"id": "str", "subtype": "str", "class": "str"},
}
# merge_with_building_footprints.py's output schema (trained inference).
TRAINED_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damage_pct_10m": "float",
        "damage_pct_20m": "float",
        "damaged": "int",
        "unknown_pct": "float",
    },
}
# PutBuildingPredictions' output schema (interactive labeler).
EMBEDDING_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "id": "int",
        "damaged": "int",
        "damage_pct_0m": "float",
        "unknown_pct": "float",
        "area": "float",
    },
}


def _square(index: int) -> Polygon:
    """A 1e-4 degree square offset by ``index`` so squares never overlap."""
    x = -122.0 + index * 0.001
    y = 47.0 + index * 0.001
    return Polygon(
        [(x, y), (x + 0.0001, y), (x + 0.0001, y + 0.0001), (x, y + 0.0001)]
    )


def write_footprints(path: str, count: int, crs: str = "EPSG:4326") -> None:
    """Write a synthetic Overture-shaped footprints GeoPackage."""
    with fiona.open(
        path, "w", driver="GPKG", crs=crs, schema=FOOTPRINT_SCHEMA
    ) as dst:
        for index in range(count):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": f"overture-{index}",
                        "subtype": "residential",
                        "class": "house",
                    },
                }
            )


def write_trained_predictions(
    path: str, damages: list, unknowns: list, crs: str = "EPSG:32610"
) -> None:
    """Write a trained-inference prediction GeoPackage (default layer).

    Written in a projected CRS on purpose: the real merge script writes
    in the raster CRS, not EPSG:4326.
    """
    with fiona.open(
        path, "w", driver="GPKG", crs=crs, schema=TRAINED_SCHEMA
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damage_pct_0m": damage,
                        "damage_pct_10m": damage,
                        "damage_pct_20m": damage,
                        "damaged": 1 if damage > 0 else 0,
                        "unknown_pct": unknowns[index],
                    },
                }
            )


def write_embedding_predictions(
    path: str, damaged_flags: list, unknowns: list
) -> None:
    """Write an interactive-labeler prediction GeoPackage."""
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        crs="EPSG:4326",
        schema=EMBEDDING_SCHEMA,
        layer="predictions",
    ) as dst:
        for index, flag in enumerate(damaged_flags):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damaged": int(flag),
                        "damage_pct_0m": float(flag),
                        "unknown_pct": unknowns[index],
                        "area": 100.0,
                    },
                }
            )


class TestBuildPredictionAttrs(unittest.TestCase):
    """The columnar sidecar, against both prediction GPKG flavors."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-pred-tiles-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.footprints = os.path.join(self.tmpdir, "footprints.gpkg")
        self.predictions = os.path.join(self.tmpdir, "predictions.gpkg")

    def test_trained_flavor_columns_align(self):
        damages = [0.0, 0.25, 0.9, 1.0]
        unknowns = [0.0, 0.1, 0.0, 0.5]
        write_footprints(self.footprints, len(damages))
        write_trained_predictions(self.predictions, damages, unknowns)

        payload = ppt.build_prediction_attrs(self.predictions, self.footprints)

        self.assertEqual(payload["n"], 4)
        self.assertEqual(payload["ids"], [0, 1, 2, 3])
        self.assertEqual(payload["damage"], damages)
        self.assertEqual(payload["unknown"], unknowns)
        self.assertEqual(payload["damaged"], [0, 1, 1, 1])
        self.assertEqual(
            payload["overtureIds"],
            ["overture-0", "overture-1", "overture-2", "overture-3"],
        )

    def test_embedding_flavor_columns_align(self):
        flags = [1, 0, 1]
        unknowns = [0.0, 0.0, 0.25]
        write_footprints(self.footprints, len(flags))
        write_embedding_predictions(self.predictions, flags, unknowns)

        payload = ppt.build_prediction_attrs(self.predictions, self.footprints)

        self.assertEqual(payload["n"], 3)
        self.assertEqual(payload["ids"], [0, 1, 2])
        # damage_pct_0m is a degenerate 0.0/1.0 copy of `damaged` here.
        self.assertEqual(payload["damage"], [1.0, 0.0, 1.0])
        self.assertEqual(payload["damaged"], flags)
        self.assertEqual(payload["unknown"], unknowns)
        self.assertEqual(
            payload["overtureIds"],
            ["overture-0", "overture-1", "overture-2"],
        )

    def test_all_arrays_have_equal_length(self):
        damages = [0.1, 0.2, 0.3, 0.4, 0.5]
        unknowns = [0.0] * 5
        write_footprints(self.footprints, len(damages))
        write_trained_predictions(self.predictions, damages, unknowns)

        payload = ppt.build_prediction_attrs(self.predictions, self.footprints)

        lengths = {
            key: len(payload[key])
            for key in ("ids", "overtureIds", "damage", "unknown", "damaged")
        }
        self.assertEqual(set(lengths.values()), {payload["n"]})

    def test_rows_are_ordered_by_row_index(self):
        # A strictly increasing damage ramp makes any reordering visible.
        damages = [i / 10.0 for i in range(10)]
        unknowns = [0.0] * 10
        write_footprints(self.footprints, len(damages))
        write_trained_predictions(self.predictions, damages, unknowns)

        payload = ppt.build_prediction_attrs(self.predictions, self.footprints)

        self.assertEqual(payload["ids"], sorted(payload["ids"]))
        self.assertEqual(payload["damage"], damages)
        for index, overture_id in enumerate(payload["overtureIds"]):
            self.assertEqual(overture_id, f"overture-{index}")

    def test_overture_ids_follow_footprint_row_order(self):
        # Footprint ids deliberately NOT sorted lexicographically, so a
        # sort-by-id bug would be caught.
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:4326",
            schema=FOOTPRINT_SCHEMA,
        ) as dst:
            for index, oid in enumerate(["zeta", "alpha", "mu"]):
                dst.write(
                    {
                        "geometry": mapping(_square(index)),
                        "properties": {
                            "id": oid,
                            "subtype": "residential",
                            "class": "house",
                        },
                    }
                )
        write_trained_predictions(
            self.predictions, [0.0, 0.5, 1.0], [0.0, 0.0, 0.0]
        )

        payload = ppt.build_prediction_attrs(self.predictions, self.footprints)

        self.assertEqual(payload["overtureIds"], ["zeta", "alpha", "mu"])
        self.assertEqual(payload["damage"], [0.0, 0.5, 1.0])

    def test_length_mismatch_raises_clear_error(self):
        write_footprints(self.footprints, 5)
        write_trained_predictions(
            self.predictions, [0.0, 1.0, 0.5], [0.0, 0.0, 0.0]
        )

        with self.assertRaises(ppt.FootprintPredictionMismatchError) as caught:
            ppt.build_prediction_attrs(self.predictions, self.footprints)

        message = str(caught.exception)
        self.assertIn("3 predictions", message)
        self.assertIn("5 footprints", message)
        self.assertIn("positional", message)

    def test_length_mismatch_is_a_value_error(self):
        # Callers (and the queue trigger) catch ValueError; keep that
        # contract even though the subclass carries the detail.
        write_footprints(self.footprints, 2)
        write_embedding_predictions(self.predictions, [1], [0.0])

        with self.assertRaises(ValueError):
            ppt.build_prediction_attrs(self.predictions, self.footprints)

    def test_write_prediction_attrs_round_trips_json(self):
        damages = [0.0, 0.75]
        unknowns = [0.125, 0.0]
        write_footprints(self.footprints, len(damages))
        write_trained_predictions(self.predictions, damages, unknowns)
        attrs_path = os.path.join(self.tmpdir, "attrs.json")

        payload = ppt.write_prediction_attrs(
            self.predictions, self.footprints, attrs_path
        )

        with open(attrs_path) as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk, payload)
        self.assertEqual(
            sorted(on_disk),
            ["damage", "damaged", "ids", "n", "overtureIds", "unknown"],
        )


class TestFootprintTiling(unittest.TestCase):
    """Tiling inputs: CRS handling, id emission, tippecanoe invocation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-pred-tiles-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.footprints = os.path.join(self.tmpdir, "footprints.gpkg")
        self.geojson = os.path.join(self.tmpdir, "footprints_4326.geojson")

    def test_geojson_carries_row_index_and_overture_id(self):
        write_footprints(self.footprints, 3)

        count = ppt.footprints_to_tiling_geojson(self.footprints, self.geojson)

        self.assertEqual(count, 3)
        with open(self.geojson) as handle:
            collection = json.load(handle)
        properties = [f["properties"] for f in collection["features"]]
        self.assertEqual([p["id"] for p in properties], [0, 1, 2])
        self.assertEqual(
            [p["overture_id"] for p in properties],
            ["overture-0", "overture-1", "overture-2"],
        )
        # Damage values must NOT ride in the tiles.
        for props in properties:
            self.assertEqual(set(props), {"id", "overture_id"})

    def test_projected_footprints_are_reprojected_to_4326(self):
        # UTM 10N coordinates; tiles must always come out geographic.
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs="EPSG:32610",
            schema=FOOTPRINT_SCHEMA,
        ) as dst:
            for index in range(2):
                dst.write(
                    {
                        "geometry": mapping(
                            Polygon(
                                [
                                    (500000 + index * 10, 5200000),
                                    (500010 + index * 10, 5200000),
                                    (500010 + index * 10, 5200010),
                                    (500000 + index * 10, 5200010),
                                ]
                            )
                        ),
                        "properties": {
                            "id": f"overture-{index}",
                            "subtype": "residential",
                            "class": "house",
                        },
                    }
                )

        ppt.footprints_to_tiling_geojson(self.footprints, self.geojson)

        with fiona.open(self.geojson) as src:
            self.assertEqual(src.crs.to_epsg(), 4326)
            longitudes = [
                feature["geometry"]["coordinates"][0][0][0] for feature in src
            ]
        for longitude in longitudes:
            self.assertTrue(-180.0 <= longitude <= 180.0)

    def test_footprints_without_crs_are_rejected(self):
        with fiona.open(
            self.footprints,
            "w",
            driver="GPKG",
            crs=None,
            schema=FOOTPRINT_SCHEMA,
        ) as dst:
            dst.write(
                {
                    "geometry": mapping(_square(0)),
                    "properties": {
                        "id": "overture-0",
                        "subtype": None,
                        "class": None,
                    },
                }
            )

        with self.assertRaises(ValueError) as caught:
            ppt.footprints_to_tiling_geojson(self.footprints, self.geojson)
        self.assertIn("no CRS", str(caught.exception))

    def test_missing_tippecanoe_raises_actionable_error(self):
        with mock.patch.object(ppt.shutil, "which", return_value=None):
            with self.assertRaises(ppt.TippecanoeNotFoundError) as caught:
                ppt.require_tippecanoe()
        message = str(caught.exception)
        self.assertIn("tippecanoe", message)
        self.assertIn("training image", message)

    def test_build_footprint_pmtiles_fails_fast_without_binary(self):
        write_footprints(self.footprints, 2)
        pmtiles = os.path.join(self.tmpdir, "tiles.pmtiles")
        with mock.patch.object(ppt.shutil, "which", return_value=None):
            with self.assertRaises(ppt.TippecanoeNotFoundError):
                ppt.build_footprint_pmtiles(self.footprints, pmtiles)
        # Fails before doing any work.
        self.assertFalse(os.path.exists(pmtiles))

    def test_tippecanoe_command_preserves_feature_id_promotion(self):
        pmtiles = os.path.join(self.tmpdir, "tiles.pmtiles")
        with mock.patch.object(
            ppt.shutil, "which", return_value="/usr/bin/tippecanoe"
        ):
            with mock.patch.object(ppt.subprocess, "run") as runner:
                ppt.run_tippecanoe(self.geojson, pmtiles)

        cmd = runner.call_args.args[0]
        self.assertIn("--use-attribute-for-id=id", cmd)
        self.assertEqual(cmd[cmd.index("-o") + 1], pmtiles)
        self.assertEqual(cmd[cmd.index("-l") + 1], "buildings")
        # Only id + overture_id survive into the tiles.
        keep = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-y"]
        self.assertEqual(keep, ["id", "overture_id"])
        self.assertIn("--minimum-zoom=10", cmd)
        self.assertIn("--maximum-zoom=15", cmd)
        self.assertIn("--no-tile-size-limit", cmd)
        self.assertTrue(runner.call_args.kwargs["check"])

    def test_tippecanoe_failure_is_wrapped(self):
        pmtiles = os.path.join(self.tmpdir, "tiles.pmtiles")
        error = subprocess.CalledProcessError(3, ["tippecanoe"])
        with mock.patch.object(
            ppt.shutil, "which", return_value="/usr/bin/tippecanoe"
        ):
            with mock.patch.object(ppt.subprocess, "run", side_effect=error):
                with self.assertRaises(ppt.TippecanoeError) as caught:
                    ppt.run_tippecanoe(self.geojson, pmtiles)
        self.assertIn("exit code 3", str(caught.exception))


class TestArtifactNaming(unittest.TestCase):
    def test_names_come_from_artifact_templates(self):
        self.assertEqual(
            ppt.default_pmtiles_name("layer-1"), "footprints_layer-1.pmtiles"
        )
        self.assertEqual(
            ppt.default_attrs_name("model-1"),
            "prediction_attrs_model-1.json",
        )


class TestWorkflowRun(unittest.TestCase):
    """End-to-end ``run()`` with tippecanoe and storage mocked out."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-pred-tiles-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.output_dir = os.path.join(self.tmpdir, "outputs")
        os.makedirs(self.output_dir)
        self.footprints = os.path.join(self.tmpdir, "footprints.gpkg")
        self.predictions = os.path.join(self.tmpdir, "predictions.gpkg")
        write_footprints(self.footprints, 3)
        write_trained_predictions(
            self.predictions, [0.0, 0.5, 1.0], [0.0, 0.0, 0.1]
        )

    def _config(self, build_pmtiles: bool) -> dict:
        return {
            "project_id": "proj-1",
            "image_layer_id": "layer-1",
            "model_id": "model-1",
            "files": {
                "footprints": self.footprints,
                "predictions": self.predictions,
            },
            "tiles": {"build_pmtiles": build_pmtiles},
            "store_artifacts": False,
        }

    def test_run_builds_tiles_and_sidecar(self):
        def fake_run(cmd, check=False):
            # Stand in for tippecanoe: touch the -o target.
            with open(cmd[cmd.index("-o") + 1], "wb") as handle:
                handle.write(b"PMTiles")
            return mock.Mock(returncode=0)

        with mock.patch.object(
            ppt.shutil, "which", return_value="/usr/bin/tippecanoe"
        ):
            with mock.patch.object(
                ppt.subprocess, "run", side_effect=fake_run
            ):
                manifest = ppt.run(self._config(True), self.output_dir)

        self.assertTrue(manifest["pmtiles_built"])
        self.assertEqual(
            manifest["pmtiles_filename"], "footprints_layer-1.pmtiles"
        )
        self.assertEqual(
            manifest["attrs_filename"], "prediction_attrs_model-1.json"
        )
        self.assertEqual(manifest["building_count"], 3)
        self.assertTrue(manifest["supports_threshold"])
        self.assertTrue(
            os.path.exists(
                os.path.join(self.output_dir, manifest["attrs_filename"])
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(self.output_dir, manifest["pmtiles_filename"])
            )
        )
        # The tiling GeoJSON is scratch and must not be uploaded.
        self.assertFalse(
            os.path.exists(
                os.path.join(self.output_dir, "footprints_4326.geojson")
            )
        )
        with open(
            os.path.join(self.output_dir, ppt.MANIFEST_FILENAME)
        ) as handle:
            self.assertEqual(json.load(handle), manifest)

    def test_run_skips_tiles_when_layer_already_has_them(self):
        with mock.patch.object(ppt.subprocess, "run") as runner:
            manifest = ppt.run(self._config(False), self.output_dir)

        runner.assert_not_called()
        self.assertFalse(manifest["pmtiles_built"])
        self.assertEqual(manifest["pmtiles_filename"], "")
        self.assertEqual(manifest["building_count"], 3)

    def test_run_requires_identifiers(self):
        config = self._config(False)
        config.pop("model_id")
        with self.assertRaises(ValueError):
            ppt.run(config, self.output_dir)

    def test_run_reports_missing_inputs(self):
        config = self._config(False)
        config["files"]["predictions"] = os.path.join(
            self.tmpdir, "does-not-exist.gpkg"
        )
        with self.assertRaises(FileNotFoundError):
            ppt.run(config, self.output_dir)


if __name__ == "__main__":
    unittest.main()
