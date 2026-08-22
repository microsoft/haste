# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for prediction-source resolution (raw vs analyst edits).

``Model.gpkgUrl`` is the RAW model output and is never rewritten; every
save of the prediction editor appends a new numbered entry to
``Model.editedPredictions`` (ADR-0005). Readers therefore need one rule
for "which GeoPackage should I open?", and ADR-0005 deliberately did not
add a mutable "active version" pointer: newest edit wins, with an
explicit ``version`` override.

No GeoPackages are read here — this is pure metadata selection.
"""

import unittest

from hastegeo.core.models.projects import Model
from hastegeo.core.utils.predictions import (
    PredictionVersionNotFoundError,
    describe_prediction_source,
    edited_prediction_versions,
    resolve_prediction_source,
)

RAW_URL = "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas"


def _edit(version: int, **overrides) -> dict:
    entry = {
        "version": version,
        "gpkgUrl": f"https://acct.blob/c/hash/edited_predictions_5557_v"
        f"{version}.gpkg?sas",
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
        "editedPredictions": list(edits),
    }
    data.update(overrides)
    return data


class TestResolveWithoutEdits(unittest.TestCase):
    def test_falls_back_to_the_raw_model_output(self):
        self.assertEqual(resolve_prediction_source(_model()), RAW_URL)

    def test_missing_edited_list_is_treated_as_no_edits(self):
        model = _model()
        del model["editedPredictions"]

        self.assertEqual(resolve_prediction_source(model), RAW_URL)

    def test_source_is_flagged_as_not_edited(self):
        source = describe_prediction_source(_model())

        self.assertIsNone(source.version)
        self.assertFalse(source.is_edited)
        self.assertEqual(source.edited_count, 0)

    def test_model_without_predictions_resolves_to_empty(self):
        # Callers surface the empty URL as a 404 rather than a crash.
        self.assertEqual(resolve_prediction_source(_model(gpkgUrl=None)), "")


class TestResolveWithEdits(unittest.TestCase):
    def test_single_edit_wins_over_the_raw_output(self):
        source = describe_prediction_source(_model(_edit(1)))

        self.assertEqual(source.url, _edit(1)["gpkgUrl"])
        self.assertEqual(source.version, 1)
        self.assertTrue(source.is_edited)
        self.assertEqual(source.created_by, "analyst@example.com")
        self.assertEqual(source.edited_count, 10)

    def test_newest_of_several_edits_wins(self):
        model = _model(_edit(1), _edit(2), _edit(3))

        self.assertEqual(resolve_prediction_source(model), _edit(3)["gpkgUrl"])

    def test_newest_is_by_version_number_not_list_order(self):
        # The list is append-only today, but readers must not rely on it.
        model = _model(_edit(3), _edit(1), _edit(2))

        source = describe_prediction_source(model)

        self.assertEqual(source.version, 3)

    def test_entries_without_a_url_are_skipped(self):
        model = _model(_edit(1), _edit(2, gpkgUrl=""))

        source = describe_prediction_source(model)

        self.assertEqual(source.version, 1)

    def test_raw_output_is_never_mutated(self):
        model = _model(_edit(1), _edit(2))

        resolve_prediction_source(model)

        self.assertEqual(model["gpkgUrl"], RAW_URL)


class TestExplicitVersion(unittest.TestCase):
    def test_pins_an_older_version(self):
        model = _model(_edit(1), _edit(2), _edit(3))

        source = describe_prediction_source(model, version=2)

        self.assertEqual(source.version, 2)
        self.assertEqual(source.url, _edit(2)["gpkgUrl"])

    def test_version_zero_selects_the_raw_model_output(self):
        model = _model(_edit(1), _edit(2))

        source = describe_prediction_source(model, version=0)

        self.assertEqual(source.url, RAW_URL)
        self.assertIsNone(source.version)
        self.assertFalse(source.is_edited)

    def test_missing_version_raises(self):
        model = _model(_edit(1), _edit(2))

        with self.assertRaises(PredictionVersionNotFoundError) as ctx:
            describe_prediction_source(model, version=7)

        message = str(ctx.exception)
        self.assertIn("7", message)
        self.assertIn("5557", message)
        self.assertIn("[2, 1]", message)

    def test_missing_version_raises_when_there_are_no_edits(self):
        with self.assertRaises(PredictionVersionNotFoundError):
            resolve_prediction_source(_model(), version=1)

    def test_version_not_found_is_a_value_error(self):
        # The HTTP layer catches it specifically for a 404; keeping it a
        # ValueError means a generic handler still rejects the request.
        self.assertTrue(issubclass(PredictionVersionNotFoundError, ValueError))


class TestVersionListing(unittest.TestCase):
    def test_newest_first(self):
        model = _model(_edit(1), _edit(3), _edit(2))

        versions = edited_prediction_versions(model)

        self.assertEqual([v["version"] for v in versions], [3, 2, 1])

    def test_empty_without_edits(self):
        self.assertEqual(edited_prediction_versions(_model()), [])

    def test_entries_are_json_serializable_dicts(self):
        # A Model instance carries EditedPredictionVersion objects; the
        # API has to hand plain dicts to json.dumps either way.
        versions = edited_prediction_versions(Model(**_model(_edit(1))))

        self.assertIsInstance(versions[0], dict)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["editedCount"], 10)


class TestModelInstanceInput(unittest.TestCase):
    def test_resolves_from_a_model_instance(self):
        model = Model(**_model(_edit(1), _edit(2)))

        self.assertEqual(resolve_prediction_source(model), _edit(2)["gpkgUrl"])

    def test_model_instance_and_dict_agree(self):
        document = _model(_edit(1), _edit(2))

        self.assertEqual(
            resolve_prediction_source(document),
            resolve_prediction_source(Model(**document)),
        )


if __name__ == "__main__":
    unittest.main()
