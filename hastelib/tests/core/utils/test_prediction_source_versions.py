# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Version resolution for the per-version attribute sidecar.

``describe_prediction_source`` now answers two more questions the
results viewer needs:

* **which sidecar** describes the selected GeoPackage — the model-level
  one for the raw output, the version's own for an edited version. The
  map renders from the sidecar, so pairing the wrong one with a
  GeoPackage draws the wrong classes;
* **whether the selection is the newest saved state**. Version selection
  changes the map only; the Assessment and Validation reports always
  read the newest version, so the UI has to be able to say when the two
  diverge instead of recomputing it.
"""

import unittest

from hastegeo.core.models.projects import EditedPredictionVersion, Model
from hastegeo.core.utils.predictions import (
    PredictionVersionNotFoundError,
    describe_prediction_source,
)

RAW_URL = "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas"
RAW_ATTRS = "https://acct.blob/c/hash/prediction_attrs_5557.json?sas"


def _edit(version: int, attrs: bool = True, **overrides) -> dict:
    entry = {
        "version": version,
        "gpkgUrl": (
            "https://acct.blob/c/hash/edited_predictions_5557_v"
            f"{version}.gpkg?sas"
        ),
        "predictionAttrsUrl": (
            "https://acct.blob/c/hash/prediction_attrs_5557_v"
            f"{version}.json?sas"
            if attrs
            else None
        ),
        "createdAt": f"2026-08-2{version}T05:10:48+00:00",
        "createdBy": "analyst@example.com",
        "threshold": 0.5,
        "unknownThreshold": 0.0,
        "editedCount": version * 10,
        "sourceGpkgUrl": RAW_URL,
    }
    entry.update(overrides)
    return entry


def _model(*edits, **overrides) -> dict:
    data = {
        "modelId": "5557",
        "projectId": "proj-1",
        "imageLayerId": "layer-1",
        "gpkgUrl": RAW_URL,
        "predictionAttrsUrl": RAW_ATTRS,
        "editedPredictions": list(edits),
    }
    data.update(overrides)
    return data


class TestSidecarSelection(unittest.TestCase):
    def test_raw_output_uses_the_model_level_sidecar(self):
        source = describe_prediction_source(_model())

        self.assertEqual(source.url, RAW_URL)
        self.assertEqual(source.attrs_url, RAW_ATTRS)

    def test_version_zero_uses_the_model_level_sidecar(self):
        source = describe_prediction_source(_model(_edit(1)), version=0)

        self.assertEqual(source.url, RAW_URL)
        self.assertEqual(source.attrs_url, RAW_ATTRS)
        self.assertIsNone(source.version)

    def test_absent_version_uses_the_newest_edit_sidecar(self):
        source = describe_prediction_source(_model(_edit(1), _edit(2)))

        self.assertEqual(source.version, 2)
        self.assertTrue(source.attrs_url.endswith("_v2.json?sas"))

    def test_pinned_version_uses_its_own_sidecar(self):
        source = describe_prediction_source(
            _model(_edit(1), _edit(2)), version=1
        )

        self.assertEqual(source.version, 1)
        self.assertTrue(source.attrs_url.endswith("_v1.json?sas"))
        self.assertNotEqual(source.attrs_url, RAW_ATTRS)

    def test_version_without_a_sidecar_reports_an_empty_url(self):
        # Never fall back to the raw sidecar: it describes the model's
        # classes, not the analyst's, so it would silently mis-draw.
        source = describe_prediction_source(
            _model(_edit(1, attrs=False)), version=1
        )

        self.assertEqual(source.attrs_url, "")
        self.assertTrue(source.url)

    def test_unknown_version_raises(self):
        with self.assertRaises(PredictionVersionNotFoundError) as caught:
            describe_prediction_source(_model(_edit(1)), version=7)

        message = str(caught.exception)
        self.assertIn("version 7", message)
        self.assertIn("[1]", message)

    def test_source_is_json_serializable(self):
        payload = describe_prediction_source(_model(_edit(1))).to_dict()

        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["attrsUrl"].endswith("_v1.json?sas"))
        self.assertTrue(payload["isLatest"])


class TestIsLatest(unittest.TestCase):
    def test_raw_output_is_latest_without_edits(self):
        self.assertTrue(describe_prediction_source(_model()).is_latest)

    def test_raw_output_is_not_latest_once_edits_exist(self):
        source = describe_prediction_source(_model(_edit(1)), version=0)

        self.assertFalse(source.is_latest)

    def test_newest_edit_is_latest(self):
        source = describe_prediction_source(_model(_edit(1), _edit(2)))

        self.assertTrue(source.is_latest)

    def test_older_edit_is_not_latest(self):
        source = describe_prediction_source(
            _model(_edit(1), _edit(2)), version=1
        )

        self.assertFalse(source.is_latest)

    def test_latest_is_by_version_number_not_list_order(self):
        source = describe_prediction_source(
            _model(_edit(2), _edit(1)), version=2
        )

        self.assertTrue(source.is_latest)


class TestModelInstances(unittest.TestCase):
    """Model documents reach this module as dicts AND as objects."""

    def _instance(self, attrs: bool) -> Model:
        return Model(
            modelId="5557",
            projectId="proj-1",
            imageLayerId="layer-1",
            gpkgUrl=RAW_URL,
            predictionAttrsUrl=RAW_ATTRS,
            editedPredictions=[
                EditedPredictionVersion(**_edit(1, attrs=attrs))
            ],
        )

    def test_version_sidecar_is_read_off_the_entry_object(self):
        source = describe_prediction_source(self._instance(True), version=1)

        self.assertTrue(source.attrs_url.endswith("_v1.json?sas"))
        self.assertTrue(source.is_latest)

    def test_missing_sidecar_is_empty_not_the_raw_one(self):
        source = describe_prediction_source(self._instance(False), version=1)

        self.assertEqual(source.attrs_url, "")
        self.assertNotEqual(source.attrs_url, RAW_ATTRS)

    def test_instance_and_dict_agree(self):
        instance = describe_prediction_source(self._instance(True))
        as_dict = describe_prediction_source(_model(_edit(1)))

        self.assertEqual(instance.to_dict(), as_dict.to_dict())


if __name__ == "__main__":
    unittest.main()
