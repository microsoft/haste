# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the prediction-editing HTTP wire contracts.

These models are the API layer's input boundary: a malformed editor
request must fail here with a validation error rather than reach the
geospatial code. The tests pin the exact allowlists and bounds the
routes rely on.
"""

import unittest

from hastegeo.core.models.predictions import (
    PREDICTION_EDIT_CLASSES,
    PREDICTION_EDIT_DEFAULT_THRESHOLD,
    EditedPredictionsRequest,
    PredictionOverrideRequest,
    PreparePredictionTilesRequest,
)
from hastegeo.core.utils.assessment import DAMAGED, NOT_DAMAGED, UNKNOWN
from pydantic import ValidationError

GUID = "8ee4b0ea-3f24-4c05-b8c1-9ec2f8d5b6a1"
OTHER_GUID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"


def _edit_body(**overrides) -> dict:
    body = {
        "projectId": GUID,
        "imageLayerId": OTHER_GUID,
        "modelId": "5557",
    }
    body.update(overrides)
    return body


class TestPredictionOverrideRequest(unittest.TestCase):
    def test_accepts_the_wire_aliases(self):
        override = PredictionOverrideRequest.model_validate(
            {"id": 12, "class": DAMAGED}
        )
        self.assertEqual(override.rowIndex, 12)
        self.assertEqual(override.editedClass, DAMAGED)

    def test_rejects_negative_row_index(self):
        with self.assertRaises(ValidationError):
            PredictionOverrideRequest.model_validate(
                {"id": -1, "class": DAMAGED}
            )

    def test_rejects_unknown_class(self):
        with self.assertRaises(ValidationError):
            PredictionOverrideRequest.model_validate(
                {"id": 0, "class": "Destroyed"}
            )

    def test_allowed_classes_come_from_the_assessment_utility(self):
        self.assertEqual(
            PREDICTION_EDIT_CLASSES, (DAMAGED, NOT_DAMAGED, UNKNOWN)
        )


class TestEditedPredictionsRequest(unittest.TestCase):
    def test_defaults(self):
        request = EditedPredictionsRequest.model_validate(_edit_body())
        self.assertEqual(request.threshold, PREDICTION_EDIT_DEFAULT_THRESHOLD)
        self.assertEqual(request.unknownThreshold, 0.0)
        self.assertEqual(request.overrides, [])

    def test_rejects_non_guid_ids(self):
        for field in ("projectId", "imageLayerId"):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    EditedPredictionsRequest.model_validate(
                        _edit_body(**{field: "not-a-guid"})
                    )

    def test_rejects_non_numeric_model_id(self):
        with self.assertRaises(ValidationError):
            EditedPredictionsRequest.model_validate(
                _edit_body(modelId="../secrets")
            )

    def test_rejects_thresholds_outside_the_unit_interval(self):
        for field in ("threshold", "unknownThreshold"):
            for value in (-0.01, 1.01):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        EditedPredictionsRequest.model_validate(
                            _edit_body(**{field: value})
                        )

    def test_rejects_duplicate_override_ids(self):
        with self.assertRaises(ValidationError):
            EditedPredictionsRequest.model_validate(
                _edit_body(
                    overrides=[
                        {"id": 3, "class": DAMAGED},
                        {"id": 3, "class": NOT_DAMAGED},
                    ]
                )
            )

    def test_accepts_distinct_override_ids(self):
        request = EditedPredictionsRequest.model_validate(
            _edit_body(
                threshold=0.25,
                unknownThreshold=1.0,
                overrides=[
                    {"id": 3, "class": DAMAGED},
                    {"id": 4, "class": UNKNOWN},
                ],
            )
        )
        self.assertEqual(
            [override.rowIndex for override in request.overrides], [3, 4]
        )
        self.assertEqual(request.threshold, 0.25)


class TestPreparePredictionTilesRequest(unittest.TestCase):
    def test_force_defaults_to_false(self):
        request = PreparePredictionTilesRequest.model_validate(
            {
                "projectId": GUID,
                "imageLayerId": OTHER_GUID,
                "modelId": "5557",
            }
        )
        self.assertFalse(request.force)

    def test_accepts_force(self):
        request = PreparePredictionTilesRequest.model_validate(
            {
                "projectId": GUID,
                "imageLayerId": OTHER_GUID,
                "modelId": "5557",
                "force": True,
            }
        )
        self.assertTrue(request.force)

    def test_rejects_non_guid_ids(self):
        for field in ("projectId", "imageLayerId"):
            with self.subTest(field=field):
                payload = {
                    "projectId": GUID,
                    "imageLayerId": OTHER_GUID,
                    "modelId": "5557",
                }
                payload[field] = "1234"
                with self.assertRaises(ValidationError):
                    PreparePredictionTilesRequest.model_validate(payload)

    def test_rejects_missing_model_id(self):
        with self.assertRaises(ValidationError):
            PreparePredictionTilesRequest.model_validate(
                {"projectId": GUID, "imageLayerId": OTHER_GUID}
            )


if __name__ == "__main__":
    unittest.main()
