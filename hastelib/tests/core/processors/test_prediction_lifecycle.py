# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from unittest.mock import patch

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.data_layer.unified import UnifiedDataLayer
from hastegeo.core.models.prediction_results import ModelArtifactRequest
from hastegeo.core.processors.building_predictions import (
    write_building_predictions,
)
from hastegeo.core.processors.prediction_generations import (
    PredictionGenerationRepository,
    PredictionSupersededError,
)
from hastegeo.core.utils.prediction_readiness import raw_predictions_readiness

from .test_prediction_results import (
    MODEL_ID,
    OTHER_LAYER,
    PROJECT_ID,
    ResultsTestCase,
)


class TestPredictionAuthorityLifecycle(ResultsTestCase):
    def recreate(self) -> None:
        self.save_record(
            "model",
            MODEL_ID,
            self.model.model_copy(update={"name": "Replacement"}).model_dump(),
        )

    def test_delete_and_same_id_recreation_never_overlay_old_results(
        self,
    ) -> None:
        self.save_predictions()
        previous = self.current()
        self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
        with self.assertRaises(FileNotFoundError):
            self.current()
        self.recreate()
        replacement = self.current()
        self.assertEqual(replacement.name, "Replacement")
        self.assertNotEqual(
            replacement.predictionRevision, previous.predictionRevision
        )
        self.assertIsNone(replacement.gpkgUrl)
        self.assertIsNone(replacement.predictionAttrsUrl)
        self.assertFalse(raw_predictions_readiness(replacement)["ready"])
        self.assertEqual(replacement.inferenceJobs, [])
        self.assertIsNone(replacement.currentInferenceTaskId)
        self.assertTrue(self.storage.artifact_exists(previous.gpkgUrl))
        with self.assertRaises(FileNotFoundError):
            self.processor.resolve_artifact(
                ModelArtifactRequest(
                    projectId=PROJECT_ID,
                    modelId=MODEL_ID,
                    kind="prediction_attrs",
                    predictionRevision=previous.predictionRevision,
                )
            )
        self.assertTrue(self.save_predictions()["predictionsReady"])

    def test_recreated_model_can_have_a_different_layer(self) -> None:
        self.save_predictions()
        self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
        self.save_record(
            "model",
            MODEL_ID,
            self.model.model_copy(
                update={"imageLayerId": OTHER_LAYER}
            ).model_dump(),
        )
        replacement = self.current()
        self.assertEqual(replacement.imageLayerId, OTHER_LAYER)
        self.assertIsNone(replacement.gpkgUrl)

    def test_first_request_validating_across_delete_recreate_is_superseded(
        self,
    ) -> None:
        self.assertIsNone(self.current().predictionRevision)

        def validate_then_replace(*args: Any, **kwargs: Any) -> Any:
            artifacts = write_building_predictions(*args, **kwargs)
            self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
            self.recreate()
            return artifacts

        with patch(
            "hastegeo.core.processors.prediction_results.write_building_predictions",
            side_effect=validate_then_replace,
        ), patch.object(UnifiedArtifactStorage, "store_artifact") as upload:
            with self.assertRaises(PredictionSupersededError):
                self.save_predictions()
        upload.assert_not_called()
        self.assertIsNone(self.current().gpkgUrl)
        self.assertEqual(self.current().name, "Replacement")

    def test_upload_finishing_after_delete_recreate_cannot_publish(
        self,
    ) -> None:
        original = UnifiedArtifactStorage.store_artifact
        replaced = False

        def replace_then_upload(
            storage: UnifiedArtifactStorage, **kwargs: Any
        ) -> str:
            nonlocal replaced
            if not replaced:
                replaced = True
                self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
                self.recreate()
            return original(storage, **kwargs)

        with patch.object(
            UnifiedArtifactStorage, "store_artifact", replace_then_upload
        ):
            with self.assertRaises(PredictionSupersededError):
                self.save_predictions()
        self.assertIsNone(self.current().gpkgUrl)
        self.assertEqual(self.current().name, "Replacement")

    def test_clear_started_before_delete_cannot_clear_recreated_results(
        self,
    ) -> None:
        original_context = self.processor.context

        def replace_after_context(request: Any) -> Any:
            context = original_context(request)
            self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
            self.recreate()
            self.processor.__class__(self.config).save_building_predictions(
                self.request()
            )
            return context

        with patch.object(
            self.processor, "context", side_effect=replace_after_context
        ):
            with self.assertRaises(PredictionSupersededError):
                self.save_predictions(predictions=[])
        self.assertEqual(self.current().predictionState, "ready")
        self.assertIsNotNone(self.current().gpkgUrl)
        self.assertEqual(self.current().name, "Replacement")

    def test_delete_waits_for_the_existing_publisher_lock(self) -> None:
        other = PredictionGenerationRepository(self.config)
        attempted = Event()
        deleted = Event()

        def delete() -> None:
            attempted.set()
            other.delete_model_metadata(PROJECT_ID, MODEL_ID)
            deleted.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.repository.lock(PROJECT_ID, MODEL_ID):
                future = executor.submit(delete)
                self.assertTrue(attempted.wait(2))
                self.assertFalse(deleted.wait(0.05))
            future.result(timeout=2)
        self.assertTrue(deleted.is_set())

    def test_barrier_write_failure_leaves_existing_model_and_authority(
        self,
    ) -> None:
        self.save_predictions()
        before = self.current().model_dump()
        with patch.object(
            UnifiedDataLayer,
            "save",
            side_effect=RuntimeError("storage unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
        self.assertEqual(self.current().model_dump(), before)
