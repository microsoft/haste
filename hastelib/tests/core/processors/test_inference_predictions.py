# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from azure.core.exceptions import HttpResponseError
from hastegeo.core.models.prediction_results import InferenceQueueRequest
from hastegeo.core.models.training import Inference
from hastegeo.core.processors import inference
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.utils.metadata import MetadataUtils
from pydantic import ValidationError

from .test_prediction_results import MODEL_ID, PROJECT_ID, ResultsTestCase


class InferenceTestCase(ResultsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.model.modelType = "trained"
        self.model.checkpointPath = "checkpoints/current"
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.save_record(
            "experiment_config",
            MODEL_ID,
            {
                "experiment_name": "test",
                "inference": {},
            },
            data_format="yaml",
        )
        self.runner = self.enterContext(
            patch.object(inference, "UnifiedRunner")
        ).return_value
        self.runner.add_task.side_effect = lambda **kwargs: (
            kwargs["job_id"],
            kwargs["task_id"],
        )
        self.runner.get_filecontent_from_task.return_value = None
        self.queue = self.enterContext(
            patch.object(inference, "AzureQueueHandler")
        ).return_value
        self.config.runner_type = "local"

    def accept(self) -> InferenceQueueRequest:
        inference.InferencePreprocessor(
            self.model, self.config
        ).send_to_queue()
        return InferenceQueueRequest.model_validate_json(
            self.queue.put_message.call_args.args[0]
        )

    def submit(self) -> InferenceQueueRequest:
        inference.process_inference_request(self.accept(), self.config)
        return InferenceQueueRequest.model_validate_json(
            self.queue.put_message.call_args.args[0]
        )

    def upload_pair(
        self, *, revision: str | None = None, attrs: bool = True
    ) -> None:
        model = self.current()
        namespace = [model.currentInferenceTaskId]
        if self.config.runner_type == "local":
            namespace.append("inference")
        gpkg_name = model.predictionGpkgFilename
        self.storage.store_artifact(
            artifact_name=gpkg_name,
            src_path=self.storage.get_file_path("cached.gpkg"),
            namespace=namespace,
        )
        if attrs:
            self.storage.store_artifact(
                artifact_name=f"prediction_attrs_{MODEL_ID}.json",
                data={
                    "schemaVersion": 1,
                    "predictionRevision": revision or model.predictionRevision,
                    "flavor": "inference",
                    "n": 2,
                    "ids": [0, 1],
                    "overtureIds": ["building-0", "building-1"],
                    "damage": [0.0, 1.0],
                    "unknown": [0.0, None],
                    "damaged": [0, 1],
                    "classes": ["NotDamaged", "Unknown"],
                },
                namespace=namespace,
            )


class TestInferenceGenerations(InferenceTestCase):
    def test_acceptance_is_persisted_before_identifiers_only_publish(
        self,
    ) -> None:
        def consume(message: str) -> None:
            payload = json.loads(message)
            self.assertEqual(
                self.current().predictionRevision,
                payload["predictionRevision"],
            )
            self.assertEqual(self.current().predictionState, "pending")
            self.assertNotIn("gpkgUrl", payload)
            self.assertNotIn("sig=", message)

        self.queue.put_message.side_effect = consume
        self.accept()

    def test_configuration_and_resolver_share_filename_and_revision(
        self,
    ) -> None:
        request = self.submit()
        config_id = f"{MODEL_ID}-{request.predictionRevision}"
        config_path = Path(
            self.config.storage_config["directory"],
            MetadataUtils.hash_string(PROJECT_ID),
            f"experiment_config_{config_id}.yaml",
        )
        payload = json.loads(config_path.read_text())
        settings = payload["inference"]
        self.assertEqual(
            settings["prediction_attrs_filename"],
            f"prediction_attrs_{MODEL_ID}.json",
        )
        self.assertEqual(
            settings["prediction_revision"], request.predictionRevision
        )
        self.assertEqual(
            settings["predictions_gpkg_fileprefix"],
            "predicted_damage_Flood-Sao-1",
        )

    def test_local_and_batch_completion_require_actual_uploaded_pair(
        self,
    ) -> None:
        for runner_type in ("local", "azure_batch"):
            with self.subTest(runner_type=runner_type):
                self.config.runner_type = runner_type
                self.runner.get_task_status.return_value = (
                    self.config.get_status_types().COMPLETED.value
                )
                request = self.submit()
                self.upload_pair()
                output = inference.process_inference_request(
                    request, self.config
                )
                current = self.current()
                self.assertEqual(current.predictionState, "ready")
                self.assertEqual(
                    current.predictionReadyRevision, request.predictionRevision
                )
                self.assertEqual(current.predictedBuildingCount, 2)
                self.assertEqual(output.inferenceStatus, "Processed")
                self.assertEqual(
                    current.predictionAttrsUrl, output.predictionAttrsUrl
                )
                self.assertEqual(
                    "/inference/" in current.predictionAttrsUrl,
                    runner_type == "local",
                )

    def test_missing_uploads_do_not_publish_ready_or_clean_the_task(
        self,
    ) -> None:
        request = self.submit()
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().COMPLETED.value
        )
        output = inference.process_inference_request(request, self.config)
        self.assertEqual(output.predictionState, "failed")
        self.assertIsNone(self.current().gpkgUrl)
        self.assertIsNone(self.current().predictionAttrsUrl)
        self.runner.cleanup_task.assert_not_called()

    def test_missing_or_wrong_revision_sidecar_is_not_ready(self) -> None:
        for attrs, revision in ((False, None), (True, "obsolete")):
            request = self.submit()
            self.upload_pair(attrs=attrs, revision=revision)
            self.runner.get_task_status.return_value = (
                self.config.get_status_types().COMPLETED.value
            )
            output = inference.process_inference_request(request, self.config)
            self.assertEqual(output.predictionState, "failed")
            self.assertIsNone(self.current().predictionAttrsUrl)
        self.runner.cleanup_task.assert_not_called()

    def test_transient_storage_failure_retries_and_recovers(self) -> None:
        request = self.submit()
        self.upload_pair()
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().COMPLETED.value
        )
        with patch(
            "hastegeo.core.artifact_storage.unified_artifact_storage.UnifiedArtifactStorage.read_artifact_bytes",
            side_effect=RuntimeError("storage temporarily unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                inference.process_inference_request(request, self.config)
        self.assertEqual(self.current().predictionState, "pending")
        self.assertIsNone(self.current().predictionAttrsUrl)
        self.runner.cleanup_task.assert_not_called()
        inference.process_inference_request(request, self.config)
        self.assertEqual(self.current().predictionState, "ready")

    def test_stale_queue_snapshot_never_restores_old_results(self) -> None:
        request = self.submit()
        before = self.current().model_dump()
        for stale in (
            request.model_copy(update={"predictionRevision": "obsolete"}),
            request.model_copy(
                update={"currentInferenceTaskId": "older-task"}
            ),
            request.model_copy(update={"predictionRevision": None}),
        ):
            self.assertIsNone(
                inference.process_inference_request(stale, self.config)
            )
        self.assertEqual(self.current().model_dump(), before)
        self.runner.get_task_status.assert_not_called()

    def test_deleted_model_inference_cannot_attach_to_same_id_recreation(
        self,
    ) -> None:
        request = self.submit()
        self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.assertIsNone(
            inference.process_inference_request(request, self.config)
        )
        self.assertEqual(self.current().inferenceJobs, [])
        self.assertIsNone(self.current().currentInferenceTaskId)
        self.assertIsNone(self.current().gpkgUrl)
        self.runner.get_task_status.assert_not_called()

    def test_terminal_redelivery_and_duplicate_pending_do_not_submit_again(
        self,
    ) -> None:
        first = self.accept()
        inference.process_inference_request(first, self.config)
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().IN_PROGRESS.value
        )
        inference.process_inference_request(first, self.config)
        self.runner.add_task.assert_called_once()
        self.upload_pair()
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().COMPLETED.value
        )
        inference.process_inference_request(first, self.config)
        self.assertIsNone(
            inference.process_inference_request(first, self.config)
        )
        self.runner.add_task.assert_called_once()

    def test_poll_publish_failure_retries_without_resubmitting(self) -> None:
        request = self.accept()
        self.queue.put_message.side_effect = RuntimeError("queue unavailable")
        with self.assertRaises(RuntimeError):
            inference.process_inference_request(request, self.config)
        self.assertEqual(
            self.current().inferenceStatus,
            self.config.get_status_types().IN_PROGRESS.value,
        )
        self.queue.put_message.side_effect = None
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().IN_PROGRESS.value
        )
        inference.process_inference_request(request, self.config)
        self.runner.add_task.assert_called_once()

    def test_model_rename_does_not_change_an_accepted_output_filename(
        self,
    ) -> None:
        request = self.submit()
        self.upload_pair()
        self.save_record(
            "model", MODEL_ID, {"name": "Renamed after submission"}
        )
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().COMPLETED.value
        )
        inference.process_inference_request(request, self.config)
        self.assertEqual(self.current().predictionState, "ready")
        self.assertIn(
            "predicted_damage_Flood-Sao-1.gpkg", self.current().gpkgUrl
        )

    def test_previous_completion_cannot_restore_outputs_after_new_acceptance(
        self,
    ) -> None:
        old_request = self.submit()
        self.upload_pair()
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().COMPLETED.value
        )
        inference.process_inference_request(old_request, self.config)
        new_request = self.accept()
        self.assertNotEqual(
            old_request.predictionRevision, new_request.predictionRevision
        )
        self.assertIsNone(
            inference.process_inference_request(old_request, self.config)
        )
        self.assertEqual(
            self.current().predictionRevision, new_request.predictionRevision
        )
        self.assertIsNone(self.current().gpkgUrl)
        self.assertIsNone(self.current().predictionAttrsUrl)

    def test_initial_queue_failure_is_visible_not_ready(self) -> None:
        self.queue.put_message.side_effect = RuntimeError("queue unavailable")
        with self.assertRaises(RuntimeError):
            self.accept()
        self.assertEqual(self.current().predictionState, "failed")
        self.assertEqual(
            self.current().inferenceStatus,
            self.config.get_status_types().FAILED.value,
        )
        self.assertIsNone(self.current().predictionAttrsUrl)

    def test_acceptance_mirror_failure_still_publishes_and_consumer_repairs_it(
        self,
    ) -> None:
        original = MetadataProcessor.save_strict
        writes: list[str] = []

        def fail_mirror(
            processor: MetadataProcessor,
            key: str,
            metadata: dict[str, Any],
            data_format: str = "json",
        ) -> None:
            writes.append(processor.data_type)
            if processor.data_type == "model":
                raise HttpResponseError("https://storage?sig=do-not-log")
            original(processor, key, metadata, data_format)

        with patch.object(
            MetadataProcessor, "save_strict", fail_mirror
        ), patch(
            "hastegeo.core.processors.prediction_generations.Logger.get_logger"
        ) as logger:
            request = self.accept()
        self.assertEqual(writes, ["prediction_results", "model"])
        self.queue.put_message.assert_called_once()
        logger.return_value.warning.assert_called_once()
        self.assertNotIn("do-not-log", str(logger.return_value.mock_calls))
        self.assertEqual(self.current().predictionState, "pending")
        self.assertIsNone(self.current().currentInferenceTaskId)

        # Delivery of the accepted request after storage recovery repairs the
        # compatibility mirror rather than demanding another acceptance.
        inference.process_inference_request(request, self.config)
        mirror = self.repository.metadata(PROJECT_ID).load_strict(MODEL_ID)
        self.assertEqual(
            mirror["predictionRevision"], request.predictionRevision
        )
        self.assertEqual(
            mirror["currentInferenceTaskId"],
            self.current().currentInferenceTaskId,
        )
        self.runner.add_task.assert_called_once()
        self.runner.get_task_status.return_value = (
            self.config.get_status_types().IN_PROGRESS.value
        )
        inference.process_inference_request(request, self.config)
        self.runner.add_task.assert_called_once()

    def test_mirror_and_queue_failure_allow_new_acceptance_after_recovery(
        self,
    ) -> None:
        original = MetadataProcessor.save_strict

        def fail_mirror(
            processor: MetadataProcessor,
            key: str,
            metadata: dict[str, Any],
            data_format: str = "json",
        ) -> None:
            if processor.data_type == "model":
                raise HttpResponseError("mirror unavailable")
            original(processor, key, metadata, data_format)

        self.queue.put_message.side_effect = RuntimeError("queue unavailable")
        with patch.object(MetadataProcessor, "save_strict", fail_mirror):
            with self.assertRaises(RuntimeError):
                self.accept()
        failed = self.current()
        self.assertEqual(failed.predictionState, "failed")
        self.assertEqual(
            failed.inferenceStatus, self.config.get_status_types().FAILED.value
        )
        self.queue.put_message.side_effect = None
        request = self.accept()
        self.assertNotEqual(
            request.predictionRevision, failed.predictionRevision
        )
        inference.process_inference_request(request, self.config)
        self.runner.add_task.assert_called_once()

    def test_invalid_attrs_config_is_rejected(self) -> None:
        for filename in (
            "../attrs.json",
            "/attrs.json",
            "a\\attrs.json",
            "attrs.txt",
            ".json",
        ):
            with self.assertRaises(ValidationError):
                Inference(prediction_attrs_filename=filename)

    def test_cancel_runner_failure_retries_without_false_acknowledgement(
        self,
    ) -> None:
        poll = self.submit()
        inference.InferencePreprocessor(
            self.current(), self.config
        ).send_to_queue(status=self.config.get_status_types().CANCELLED.value)
        self.runner.cancel_task.side_effect = RuntimeError(
            "https://storage?sig=do-not-log"
        )
        with patch.object(inference.Logger, "get_logger") as logger:
            with self.assertRaises(RuntimeError) as raised:
                inference.process_inference_request(poll, self.config)
        self.assertNotIn("do-not-log", str(raised.exception))
        self.assertNotIn("do-not-log", str(logger.return_value.mock_calls))
        self.assertEqual(self.current().predictionState, "pending")
        self.assertEqual(self.current().inferenceStatus, "Cancelled")
        self.assertEqual(self.current().inferenceJobs[-1].status, "InProgress")
        self.assertIsNone(self.current().inferenceJobs[-1].completedDate)
        self.runner.cancel_task.side_effect = None
        inference.process_inference_request(poll, self.config)
        self.assertEqual(self.current().predictionState, "cancelled")
        self.runner.add_task.assert_called_once()

    def test_cancel_rechecks_completion_after_its_snapshot(self) -> None:
        poll = self.submit()
        stale = self.current()
        self.upload_pair()
        self.runner.get_task_status.return_value = "Processed"
        inference.process_inference_request(poll, self.config)
        count = self.queue.put_message.call_count
        output = inference.InferencePreprocessor(
            stale, self.config
        ).send_to_queue(status=self.config.get_status_types().CANCELLED.value)
        self.assertEqual(output.predictionState, "ready")
        self.assertEqual(self.current().inferenceStatus, "Processed")
        self.assertEqual(self.queue.put_message.call_count, count)
        self.runner.cancel_task.assert_not_called()

    def test_explicit_legacy_cancel_adopts_control_revision_without_resubmit(
        self,
    ) -> None:
        self.submit()
        legacy = self.current().model_copy(
            update={
                "predictionRevision": None,
                "predictionState": None,
                "inferenceTotalSteps": 0,
            }
        )
        self.repository.metadata(PROJECT_ID, generations=True).delete(MODEL_ID)
        self.save_record("model", MODEL_ID, legacy.model_dump())
        inference.InferencePreprocessor(legacy, self.config).send_to_queue(
            status=self.config.get_status_types().CANCELLED.value
        )
        request = InferenceQueueRequest.model_validate_json(
            self.queue.put_message.call_args.args[0]
        )
        self.assertIsNotNone(request.predictionRevision)
        inference.process_inference_request(request, self.config)
        self.assertEqual(self.current().predictionState, "cancelled")
        self.runner.cancel_task.assert_called_once()
        self.runner.add_task.assert_called_once()

    def test_legacy_cancel_snapshot_cannot_adopt_a_new_generation(
        self,
    ) -> None:
        legacy = self.current()
        request = self.accept()
        self.queue.put_message.reset_mock()

        with self.assertRaises(inference.PredictionSupersededError):
            inference.InferencePreprocessor(legacy, self.config).send_to_queue(
                status=self.config.get_status_types().CANCELLED.value
            )

        self.assertEqual(
            self.current().predictionRevision, request.predictionRevision
        )
        self.assertEqual(self.current().inferenceStatus, "Queued")
        self.queue.put_message.assert_not_called()
        self.runner.cancel_task.assert_not_called()

    def test_cancel_missing_current_task_never_cancels_another_job(
        self,
    ) -> None:
        self.submit()
        model = self.current().model_copy(
            update={"currentInferenceTaskId": "missing-task"}
        )
        processor = inference.InferencePostprocessor(model, config=self.config)
        with self.assertRaises(RuntimeError):
            processor.cancel()
        self.runner.cancel_task.assert_not_called()
