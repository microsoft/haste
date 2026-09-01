# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the shared prediction attribute sidecar builder.

The builder used to live in
``hastegeo.workflows.prepare_prediction_tiles`` next to the tippecanoe
helpers, which made it unreachable from the Functions app. These tests
pin two things:

* the move was **behaviour preserving** — the workflow's re-export is
  literally the same object, and the payload is byte-identical for both
  prediction flavors;
* the edited-version extension (``classes``) reads the analyst's final
  call out of the GeoPackage instead of re-deriving it from thresholds.
"""

import json
import os
import shutil
import tempfile
import unittest

import fiona
from hastegeo.core.utils import prediction_attrs
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
# apply_edits' output: the source columns plus the edit columns.
EDITED_SCHEMA = {
    "geometry": "Polygon",
    "properties": {
        "id": "int",
        "damage_pct_0m": "float",
        "damaged": "int",
        "unknown_pct": "float",
        "edited_class": "str",
        "edit_threshold": "float",
        "overture_id": "str",
    },
}


def _square(index: int) -> Polygon:
    x = -122.0 + index * 0.001
    y = 47.0 + index * 0.001
    return Polygon(
        [(x, y), (x + 0.0001, y), (x + 0.0001, y + 0.0001), (x, y + 0.0001)]
    )


def write_footprints(path: str, count: int) -> None:
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


def write_trained_predictions(path: str, damages: list, unknowns: list):
    with fiona.open(
        path, "w", driver="GPKG", crs="EPSG:32610", schema=TRAINED_SCHEMA
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damage_pct_0m": damage,
                        "damaged": 1 if damage > 0 else 0,
                        "unknown_pct": unknowns[index],
                    },
                }
            )


def write_edited_predictions(
    path: str, damages: list, unknowns: list, classes: list
):
    """Write what ``apply_edits`` produces for the same three rows."""
    with fiona.open(
        path, "w", driver="GPKG", crs="EPSG:32610", schema=EDITED_SCHEMA
    ) as dst:
        for index, damage in enumerate(damages):
            dst.write(
                {
                    "geometry": mapping(_square(index)),
                    "properties": {
                        "id": index,
                        "damage_pct_0m": damage,
                        "damaged": 1 if classes[index] == "Damaged" else 0,
                        "unknown_pct": unknowns[index],
                        "edited_class": classes[index],
                        "edit_threshold": 0.5,
                        "overture_id": f"overture-{index}",
                    },
                }
            )


class _TempFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="haste-attrs-")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        self.footprints = os.path.join(self.tmpdir, "footprints.gpkg")
        self.predictions = os.path.join(self.tmpdir, "predictions.gpkg")


class TestTheMoveIsBehaviourPreserving(_TempFiles):
    def test_workflow_reexports_the_shared_functions(self):
        # Identity, not equality: the workflow must not keep a copy that
        # could drift from the one the Functions app calls.
        self.assertIs(
            ppt.build_prediction_attrs,
            prediction_attrs.build_prediction_attrs,
        )
        self.assertIs(
            ppt.write_prediction_attrs,
            prediction_attrs.write_prediction_attrs,
        )
        self.assertIs(
            ppt.FootprintPredictionMismatchError,
            prediction_attrs.FootprintPredictionMismatchError,
        )

    def test_payload_shape_is_unchanged(self):
        damages = [0.0, 0.25, 1.0]
        unknowns = [0.0, 0.1, 0.5]
        write_footprints(self.footprints, 3)
        write_trained_predictions(self.predictions, damages, unknowns)

        payload = prediction_attrs.build_prediction_attrs(
            self.predictions, self.footprints
        )

        self.assertEqual(
            sorted(payload),
            ["damage", "damaged", "ids", "n", "overtureIds", "unknown"],
        )
        self.assertEqual(payload["n"], 3)
        self.assertEqual(payload["ids"], [0, 1, 2])
        self.assertEqual(payload["damage"], damages)
        self.assertEqual(payload["unknown"], unknowns)
        self.assertEqual(payload["damaged"], [0, 1, 1])
        self.assertEqual(
            payload["overtureIds"],
            ["overture-0", "overture-1", "overture-2"],
        )

    def test_row_count_mismatch_is_still_a_value_error(self):
        write_footprints(self.footprints, 4)
        write_trained_predictions(self.predictions, [0.0, 1.0], [0.0, 0.0])

        with self.assertRaises(ValueError) as caught:
            prediction_attrs.build_prediction_attrs(
                self.predictions, self.footprints
            )
        self.assertIn("positional", str(caught.exception))

    def test_write_round_trips_json(self):
        write_footprints(self.footprints, 2)
        write_trained_predictions(self.predictions, [0.0, 0.75], [0.0, 0.0])
        attrs_path = os.path.join(self.tmpdir, "attrs.json")

        payload = prediction_attrs.write_prediction_attrs(
            self.predictions, self.footprints, attrs_path
        )

        with open(attrs_path) as handle:
            self.assertEqual(json.load(handle), payload)

    def test_shared_module_does_not_need_tippecanoe(self):
        # The whole point of the move: no workflow import, no subprocess.
        self.assertFalse(
            hasattr(prediction_attrs, "run_tippecanoe"),
            "the sidecar builder must not pull in the tiling helpers",
        )


class TestEditedVersionSidecar(_TempFiles):
    def test_classes_come_from_the_edited_class_column(self):
        write_footprints(self.footprints, 3)
        # Row 0 is pristine but the analyst forced it to Unknown; row 2
        # is heavily damaged but the analyst cleared it.
        write_edited_predictions(
            self.predictions,
            damages=[0.0, 0.6, 0.9],
            unknowns=[0.0, 0.0, 0.0],
            classes=["Unknown", "Damaged", "NotDamaged"],
        )

        payload = prediction_attrs.build_edited_prediction_attrs(
            self.predictions, self.footprints
        )

        self.assertEqual(
            payload["classes"], ["Unknown", "Damaged", "NotDamaged"]
        )
        # `damaged` agrees with the edit, so a client that ignores
        # `classes` still renders damaged-vs-not correctly.
        self.assertEqual(payload["damaged"], [0, 1, 0])
        # The raw fractions are preserved: only the class was edited.
        self.assertEqual(payload["damage"], [0.0, 0.6, 0.9])

    def test_classes_are_omitted_for_a_raw_prediction_file(self):
        write_footprints(self.footprints, 2)
        write_trained_predictions(self.predictions, [0.0, 1.0], [0.0, 0.0])

        payload = prediction_attrs.build_edited_prediction_attrs(
            self.predictions, self.footprints
        )

        self.assertNotIn("classes", payload)
        self.assertEqual(payload["n"], 2)

    def test_read_edited_classes_returns_none_without_the_column(self):
        write_footprints(self.footprints, 1)
        write_trained_predictions(self.predictions, [0.0], [0.0])

        self.assertIsNone(
            prediction_attrs.read_edited_classes(self.predictions)
        )

    def test_write_edited_round_trips_json(self):
        write_footprints(self.footprints, 2)
        write_edited_predictions(
            self.predictions,
            damages=[0.0, 1.0],
            unknowns=[0.0, 0.0],
            classes=["NotDamaged", "Damaged"],
        )
        attrs_path = os.path.join(self.tmpdir, "attrs_v1.json")

        payload = prediction_attrs.write_edited_prediction_attrs(
            self.predictions, self.footprints, attrs_path
        )

        with open(attrs_path) as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk, payload)
        self.assertEqual(on_disk["classes"], ["NotDamaged", "Damaged"])


class TestArtifactNames(unittest.TestCase):
    def test_raw_sidecar_name(self):
        self.assertEqual(
            prediction_attrs.attrs_artifact_name("5557"),
            "prediction_attrs_5557.json",
        )

    def test_version_sidecar_name_embeds_the_version(self):
        self.assertEqual(
            prediction_attrs.version_attrs_artifact_name("5557", 2),
            "prediction_attrs_5557_v2.json",
        )

    def test_version_name_never_collides_with_the_raw_one(self):
        self.assertNotEqual(
            prediction_attrs.version_attrs_artifact_name("5557", 1),
            prediction_attrs.attrs_artifact_name("5557"),
        )


if __name__ == "__main__":
    unittest.main()
