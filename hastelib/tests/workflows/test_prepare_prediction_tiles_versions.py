# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for the backfill half of the prediction-tiles workflow.

The workflow rebuilds the attribute sidecar of every edited version the
processor listed in ``config["versions"]``. Two properties matter:

* the sidecar is built from the VERSION's GeoPackage, so its classes are
  the analyst's and not the model's;
* one unreadable revision is reported, not fatal — the model's own
  sidecar and the layer's tiles still have to reach storage, and the
  next preparation request retries whatever is still missing.
"""

import json
import os
import shutil
import tempfile
import unittest

import fiona
from hastegeo.workflows import prepare_prediction_tiles as ppt
from shapely.geometry import Polygon, mapping

FOOTPRINT_SCHEMA = {
    "geometry": "Polygon",
    "properties": {"id": "str", "subtype": "str", "class": "str"},
}
TRAINED_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damaged": "int",
        "unknown_pct": "float",
    },
}
EDITED_SCHEMA = dict(
    TRAINED_SCHEMA,
    properties=dict(
        TRAINED_SCHEMA["properties"],
        edited_class="str",
        edit_threshold="float",
        overture_id="str",
    ),
)


def _square(index: int) -> Polygon:
    x = -122.0 + index * 0.001
    y = 47.0 + index * 0.001
    return Polygon(
        [(x, y), (x + 0.0001, y), (x + 0.0001, y + 0.0001), (x, y + 0.0001)]
    )


def write_footprints(path: str, count: int) -> str:
    with fiona.open(
        path, "w", driver="GPKG", crs="EPSG:4326", schema=FOOTPRINT_SCHEMA
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
    return path


def write_predictions(path: str, damages: list) -> str:
    with fiona.open(
        path, "w", driver="GPKG", crs="EPSG:4326", schema=TRAINED_SCHEMA
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damage_pct_0m": damage,
                        "damaged": 1 if damage >= 0.5 else 0,
                        "unknown_pct": 0.0,
                    },
                }
            )
    return path


def write_edited(path: str, damages: list, classes: list) -> str:
    with fiona.open(
        path, "w", driver="GPKG", crs="EPSG:4326", schema=EDITED_SCHEMA
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damage_pct_0m": damage,
                        "damaged": 1 if classes[index] == "Damaged" else 0,
                        "unknown_pct": 0.0,
                        "edited_class": classes[index],
                        "edit_threshold": 0.8,
                        "overture_id": f"overture-{index}",
                    },
                }
            )
    return path


class BackfillFixture(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-backfill-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.output_dir = os.path.join(self.tmpdir, "outputs")
        os.makedirs(self.output_dir)
        self.footprints = write_footprints(
            os.path.join(self.tmpdir, "footprints.gpkg"), 3
        )
        self.predictions = write_predictions(
            os.path.join(self.tmpdir, "predictions.gpkg"), [0.0, 0.6, 0.9]
        )
        # v1 raised the threshold to 0.8; v2 also cleared the last row.
        self.v1 = write_edited(
            os.path.join(self.tmpdir, "edited_v1.gpkg"),
            [0.0, 0.6, 0.9],
            ["NotDamaged", "NotDamaged", "Damaged"],
        )
        self.v2 = write_edited(
            os.path.join(self.tmpdir, "edited_v2.gpkg"),
            [0.0, 0.6, 0.9],
            ["Unknown", "NotDamaged", "NotDamaged"],
        )

    def read_output(self, filename: str) -> dict:
        with open(os.path.join(self.output_dir, filename)) as handle:
            return json.load(handle)

    def _config(self, versions: list) -> dict:
        return {
            "project_id": "proj-1",
            "image_layer_id": "layer-1",
            "model_id": "model-1",
            "files": {
                "footprints": self.footprints,
                "predictions": self.predictions,
            },
            "tiles": {"build_pmtiles": False},
            "store_artifacts": False,
            "versions": versions,
        }

    def _version_entry(self, version: int, path: str) -> dict:
        return {
            "version": version,
            "predictions": path,
            "attrs": f"prediction_attrs_model-1_v{version}.json",
        }


class TestBuildVersionAttrs(BackfillFixture):
    def test_builds_one_sidecar_per_version(self):
        records = ppt.build_version_attrs(
            [
                self._version_entry(1, self.v1),
                self._version_entry(2, self.v2),
            ],
            self.footprints,
            self.output_dir,
            "model-1",
        )

        self.assertEqual([record["version"] for record in records], [1, 2])
        self.assertEqual(
            [record["filename"] for record in records],
            [
                "prediction_attrs_model-1_v1.json",
                "prediction_attrs_model-1_v2.json",
            ],
        )
        self.assertEqual([record["n"] for record in records], [3, 3])
        self.assertEqual([record["error"] for record in records], ["", ""])

    def test_each_sidecar_describes_its_own_version(self):
        ppt.build_version_attrs(
            [
                self._version_entry(1, self.v1),
                self._version_entry(2, self.v2),
            ],
            self.footprints,
            self.output_dir,
            "model-1",
        )

        first = self.read_output("prediction_attrs_model-1_v1.json")
        second = self.read_output("prediction_attrs_model-1_v2.json")

        self.assertEqual(
            first["classes"], ["NotDamaged", "NotDamaged", "Damaged"]
        )
        self.assertEqual(
            second["classes"], ["Unknown", "NotDamaged", "NotDamaged"]
        )
        self.assertNotEqual(first["damaged"], second["damaged"])

    def test_default_artifact_name_is_used_when_absent(self):
        records = ppt.build_version_attrs(
            [{"version": 3, "predictions": self.v1}],
            self.footprints,
            self.output_dir,
            "model-1",
        )

        self.assertEqual(
            records[0]["filename"], "prediction_attrs_model-1_v3.json"
        )
        self.assertEqual(
            ppt.default_version_attrs_name("model-1", 3),
            "prediction_attrs_model-1_v3.json",
        )

    def test_missing_input_is_reported_not_raised(self):
        records = ppt.build_version_attrs(
            [
                self._version_entry(
                    1, os.path.join(self.tmpdir, "missing.gpkg")
                ),
                self._version_entry(2, self.v2),
            ],
            self.footprints,
            self.output_dir,
            "model-1",
        )

        self.assertEqual(records[0]["filename"], "")
        self.assertIn("not found", records[0]["error"])
        # The healthy version is still built.
        self.assertEqual(
            records[1]["filename"], "prediction_attrs_model-1_v2.json"
        )

    def test_row_count_mismatch_is_reported_per_version(self):
        short = write_footprints(
            os.path.join(self.tmpdir, "short_footprints.gpkg"), 2
        )

        records = ppt.build_version_attrs(
            [self._version_entry(1, self.v1)],
            short,
            self.output_dir,
            "model-1",
        )

        self.assertEqual(records[0]["filename"], "")
        self.assertIn("mismatch", records[0]["error"])

    def test_entries_without_a_version_are_skipped(self):
        records = ppt.build_version_attrs(
            [{"predictions": self.v1}, self._version_entry(1, self.v1)],
            self.footprints,
            self.output_dir,
            "model-1",
        )

        self.assertEqual([record["version"] for record in records], [1])

    def test_no_versions_is_a_no_op(self):
        self.assertEqual(
            ppt.build_version_attrs(
                [], self.footprints, self.output_dir, "model-1"
            ),
            [],
        )


class TestRunBackfillsVersions(BackfillFixture):
    def test_manifest_lists_the_versions_it_built(self):
        manifest = ppt.run(
            self._config([self._version_entry(1, self.v1)]), self.output_dir
        )

        self.assertEqual(len(manifest["version_attrs"]), 1)
        record = manifest["version_attrs"][0]
        self.assertEqual(record["version"], 1)
        self.assertEqual(
            record["filename"], "prediction_attrs_model-1_v1.json"
        )
        self.assertTrue(
            os.path.exists(os.path.join(self.output_dir, record["filename"]))
        )

    def test_model_sidecar_is_still_built(self):
        manifest = ppt.run(
            self._config([self._version_entry(1, self.v1)]), self.output_dir
        )

        self.assertEqual(
            manifest["attrs_filename"], "prediction_attrs_model-1.json"
        )
        model_attrs = self.read_output("prediction_attrs_model-1.json")
        # The model-level sidecar keeps the RAW classes...
        self.assertEqual(model_attrs["damaged"], [0, 1, 1])
        self.assertNotIn("classes", model_attrs)
        # ...while the version's own reflects the analyst's threshold.
        version_attrs = self.read_output("prediction_attrs_model-1_v1.json")
        self.assertEqual(version_attrs["damaged"], [0, 0, 1])

    def test_config_without_versions_still_runs(self):
        manifest = ppt.run(self._config([]), self.output_dir)

        self.assertEqual(manifest["version_attrs"], [])
        self.assertEqual(manifest["building_count"], 3)

    def test_absent_versions_key_is_treated_as_none(self):
        config = self._config([])
        del config["versions"]

        manifest = ppt.run(config, self.output_dir)

        self.assertEqual(manifest["version_attrs"], [])

    def test_a_broken_version_does_not_fail_the_job(self):
        manifest = ppt.run(
            self._config(
                [
                    self._version_entry(
                        1, os.path.join(self.tmpdir, "missing.gpkg")
                    )
                ]
            ),
            self.output_dir,
        )

        self.assertTrue(manifest["version_attrs"][0]["error"])
        self.assertIsNone(manifest["version_attrs"][0]["url"])
        # The model sidecar survived the broken revision.
        self.assertTrue(
            os.path.exists(
                os.path.join(self.output_dir, manifest["attrs_filename"])
            )
        )

    def test_manifest_on_disk_matches_the_return_value(self):
        manifest = ppt.run(
            self._config([self._version_entry(2, self.v2)]), self.output_dir
        )

        self.assertEqual(self.read_output(ppt.MANIFEST_FILENAME), manifest)


if __name__ == "__main__":
    unittest.main()
