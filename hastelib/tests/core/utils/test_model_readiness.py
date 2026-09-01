# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the shared "does this model have results?" rule.

Three consumers used to answer this question three different ways (the
trained-model Results button, the embedding row, and the publishing
source resolver). ``hastegeo.core.utils.model_readiness`` is the one
rule they all defer to, surfaced to the UI as ``predictionsReady``, so
these tests pin the behaviour for BOTH workflows — including the states
where a model looks finished but has nothing to read.
"""

import unittest

from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model
from hastegeo.core.utils.model_readiness import (
    REASON_NO_BUILDINGS,
    REASON_NO_PREDICTIONS,
    REASON_NOT_PROCESSED,
    REASON_READY,
    WORKFLOW_EMBEDDING,
    WORKFLOW_INFERENCE,
    annotate_predictions_ready,
    model_is_complete,
    model_workflow,
    prediction_readiness,
    predictions_ready,
)

STATUSES = Config.get_status_types()
PROCESSED = STATUSES.COMPLETED.value

GPKG_URL = "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas"
RASTER_URL = "https://acct.blob/c/hash/m_visualizer.tif?sas"


def _trained(**overrides) -> dict:
    """A trained-inference model document that finished inference."""
    data = {
        "modelId": "5557",
        "projectId": "proj-1",
        "imageLayerId": "layer-1",
        "modelType": "trained",
        "status": PROCESSED,
        "inferenceStatus": PROCESSED,
        "gpkgUrl": GPKG_URL,
        "predictedDamageLayerUrl": RASTER_URL,
    }
    data.update(overrides)
    return data


def _embedding(**overrides) -> dict:
    """An embedding model document with saved building predictions."""
    data = {
        "modelId": "5558",
        "projectId": "proj-1",
        "imageLayerId": "layer-1",
        "modelType": "embedding",
        "status": PROCESSED,
        "gpkgUrl": GPKG_URL,
        "predictedBuildingCount": 1200,
    }
    data.update(overrides)
    return data


class TestModelWorkflow(unittest.TestCase):
    def test_embedding_model_type_selects_embedding_workflow(self):
        self.assertEqual(model_workflow(_embedding()), WORKFLOW_EMBEDDING)

    def test_default_model_type_selects_inference_workflow(self):
        self.assertEqual(model_workflow({}), WORKFLOW_INFERENCE)
        self.assertEqual(model_workflow(_trained()), WORKFLOW_INFERENCE)


class TestModelIsComplete(unittest.TestCase):
    """The publishing eligibility rule, now shared."""

    def test_trained_model_gates_on_inference_status(self):
        self.assertTrue(model_is_complete(_trained()))
        self.assertFalse(
            model_is_complete(_trained(inferenceStatus="InProgress"))
        )

    def test_trained_model_ignores_its_training_status(self):
        # Training finished but inference has not: not complete, even
        # though `status` says Processed.
        self.assertFalse(model_is_complete(_trained(inferenceStatus="Queued")))

    def test_embedding_model_gates_on_status(self):
        self.assertTrue(model_is_complete(_embedding()))
        self.assertFalse(model_is_complete(_embedding(status="Failed")))

    def test_embedding_model_ignores_missing_inference_status(self):
        # Embedding models never run inference, so inferenceStatus is
        # None; gating on it is what used to hide them from the viewer.
        model = _embedding()
        self.assertIsNone(model.get("inferenceStatus"))
        self.assertTrue(model_is_complete(model))


class TestTrainedWorkflowReadiness(unittest.TestCase):
    def test_ready_with_predictions(self):
        readiness = prediction_readiness(_trained())

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason, REASON_READY)
        self.assertEqual(readiness.workflow, WORKFLOW_INFERENCE)
        self.assertEqual(readiness.status, PROCESSED)
        self.assertEqual(readiness.detail, "")

    def test_ready_with_only_the_raster(self):
        # Models predating the GeoPackage output still have the COG.
        readiness = prediction_readiness(_trained(gpkgUrl=None))

        self.assertTrue(readiness.ready)

    def test_not_ready_while_inference_runs(self):
        readiness = prediction_readiness(
            _trained(inferenceStatus="InProgress")
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NOT_PROCESSED)
        self.assertEqual(readiness.status, "InProgress")
        self.assertIn("Inference", readiness.detail)

    def test_not_ready_when_inference_failed(self):
        readiness = prediction_readiness(_trained(inferenceStatus="Failed"))

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NOT_PROCESSED)

    def test_not_ready_without_any_output(self):
        readiness = prediction_readiness(
            _trained(gpkgUrl=None, predictedDamageLayerUrl=None)
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NO_PREDICTIONS)


class TestEmbeddingWorkflowReadiness(unittest.TestCase):
    def test_ready_with_saved_predictions(self):
        readiness = prediction_readiness(_embedding())

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.reason, REASON_READY)
        self.assertEqual(readiness.workflow, WORKFLOW_EMBEDDING)

    def test_not_ready_while_embedding_runs(self):
        readiness = prediction_readiness(_embedding(status="InProgress"))

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NOT_PROCESSED)

    def test_not_ready_without_saved_predictions(self):
        readiness = prediction_readiness(
            _embedding(gpkgUrl=None, predictedBuildingCount=None)
        )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NO_PREDICTIONS)

    def test_not_ready_after_labels_are_cleared(self):
        # "Clear labels" PUTs an empty prediction list, which still
        # writes a valid all-zero GeoPackage and still sets gpkgUrl.
        readiness = prediction_readiness(_embedding(predictedBuildingCount=0))

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, REASON_NO_BUILDINGS)

    def test_ready_for_models_predating_the_building_count(self):
        # No count recorded at all: fall back to "a GeoPackage exists"
        # rather than reporting an old model as empty.
        readiness = prediction_readiness(
            _embedding(predictedBuildingCount=None)
        )

        self.assertTrue(readiness.ready)


class TestReadinessInputShapes(unittest.TestCase):
    def test_accepts_a_model_instance(self):
        self.assertTrue(predictions_ready(Model(**_trained())))
        self.assertTrue(predictions_ready(Model(**_embedding())))

    def test_model_instance_and_dict_agree(self):
        for document in (_trained(inferenceStatus="Queued"), _embedding()):
            self.assertEqual(
                predictions_ready(document),
                predictions_ready(Model(**document)),
            )

    def test_readiness_serializes_for_a_payload(self):
        payload = prediction_readiness(_embedding(status="Queued")).to_dict()

        self.assertEqual(
            set(payload),
            {"ready", "reason", "detail", "workflow", "status"},
        )
        self.assertFalse(payload["ready"])


class TestAnnotatePredictionsReady(unittest.TestCase):
    def test_stamps_the_flag_in_place(self):
        document = _trained()

        result = annotate_predictions_ready(document)

        self.assertIs(result, document)
        self.assertTrue(document["predictionsReady"])

    def test_stamps_false_without_results(self):
        document = _embedding(predictedBuildingCount=0)

        annotate_predictions_ready(document)

        self.assertFalse(document["predictionsReady"])

    def test_flag_is_always_a_bool(self):
        # The UI falls back to its own rule only when the field is
        # absent, so it must never be None/undefined.
        document = annotate_predictions_ready({})

        self.assertIsInstance(document["predictionsReady"], bool)


if __name__ == "__main__":
    unittest.main()
