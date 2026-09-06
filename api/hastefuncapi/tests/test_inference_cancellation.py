# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from unittest.mock import patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-cancellation-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-cancellation-tests")

from hastegeo.core.models.prediction_results import (  # noqa: E402
    InferenceQueueRequest,
)
from hastegeo.core.processors import inference  # noqa: E402
from hastegeo.core.utils.prediction_readiness import (  # noqa: E402
    raw_predictions_readiness,
)

from api.hastefuncapi import function_app  # noqa: E402
from hastelib.tests.core.processors.test_inference_predictions import (  # noqa: E402
    InferenceTestCase,
)
from hastelib.tests.core.processors.test_prediction_results import (  # noqa: E402
    MODEL_ID,
    PROJECT_ID,
)


class TestInferenceCancellationEndpoint(
    InferenceTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "config", self.config))
        self.enterContext(patch.object(function_app, "logger"))
        self.training = self.enterContext(
            patch.object(function_app, "TrainPreprocessor")
        )

    async def cancel(self) -> func.HttpResponse:
        return await function_app.PutCancelModelQueueMessage(
            func.HttpRequest(
                method="PUT",
                url="http://localhost/api/PutCancelModelQueueMessage",
                headers={},
                body=json.dumps(
                    {
                        "projectId": PROJECT_ID,
                        "modelId": MODEL_ID,
                    }
                ).encode(),
            )
        )

    async def test_queued_cancel_uses_authority_before_old_message_delivery(
        self,
    ) -> None:
        original = self.accept()
        # A stale training snapshot and stale terminal inference mirror must
        # neither divert cancellation to training nor make it a no-op.
        self.save_record(
            "model",
            MODEL_ID,
            {"status": "Failed", "inferenceStatus": "Processed"},
        )
        response = await self.cancel()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.current().inferenceStatus, "Cancelled")
        cancel_message = InferenceQueueRequest.model_validate_json(
            self.queue.put_message.call_args.args[0]
        )
        inference.process_inference_request(original, self.config)
        self.assertEqual(self.current().predictionState, "cancelled")
        self.assertFalse(raw_predictions_readiness(self.current())["ready"])
        self.assertIsNone(
            inference.process_inference_request(cancel_message, self.config)
        )
        self.runner.add_task.assert_not_called()
        self.runner.cancel_task.assert_not_called()
        self.training.assert_not_called()

    async def test_running_cancel_stops_authoritative_task_before_late_completion(
        self,
    ) -> None:
        poll = self.submit()
        job = self.current().inferenceJobs[-1]
        self.save_record("model", MODEL_ID, {"inferenceStatus": "Processed"})
        response = await self.cancel()
        self.assertEqual(response.status_code, 200)
        self.runner.get_task_status.return_value = "Processed"
        inference.process_inference_request(poll, self.config)
        self.runner.cancel_task.assert_called_once_with(
            job_id=job.jobId, task_id=job.taskId
        )
        self.runner.get_task_status.assert_not_called()
        self.assertEqual(self.current().predictionState, "cancelled")
        self.assertEqual(self.current().inferenceJobs[-1].status, "Cancelled")
        self.assertIsNotNone(self.current().inferenceJobs[-1].completedDate)
        self.assertIsNone(self.current().gpkgUrl)
        self.assertIsNone(self.current().predictionAttrsUrl)
        self.runner.add_task.assert_called_once()
        self.training.assert_not_called()

    async def test_failed_cancel_publish_leaves_intent_for_existing_poll(
        self,
    ) -> None:
        poll = self.submit()
        self.queue.put_message.side_effect = RuntimeError("queue unavailable")
        response = await self.cancel()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.current().predictionState, "pending")
        self.assertEqual(self.current().inferenceStatus, "Cancelled")
        inference.process_inference_request(poll, self.config)
        self.runner.cancel_task.assert_called_once()
        self.assertEqual(self.current().predictionState, "cancelled")

    async def test_fast_cancel_consumer_is_not_clobbered_by_outer_save(
        self,
    ) -> None:
        self.accept()

        def consume(message: str) -> None:
            inference.process_inference_request(
                InferenceQueueRequest.model_validate_json(message), self.config
            )

        self.queue.put_message.side_effect = consume
        response = await self.cancel()
        self.assertEqual(response.status_code, 200)
        mirror = self.repository.metadata(PROJECT_ID).load_strict(MODEL_ID)
        self.assertEqual(mirror["predictionState"], "cancelled")
        self.assertEqual(self.current().predictionState, "cancelled")
        self.runner.add_task.assert_not_called()

    async def test_paused_cancel_cannot_cancel_same_id_replacement(
        self,
    ) -> None:
        original_poll = self.submit()
        replacement_poll: InferenceQueueRequest | None = None
        send_to_queue = inference.InferencePreprocessor.send_to_queue

        def replace_before_cancellation(
            processor: inference.InferencePreprocessor,
            status: str | None = None,
        ) -> inference.Model:
            nonlocal replacement_poll
            if status == self.config.get_status_types().CANCELLED.value:
                self.repository.delete_model_metadata(PROJECT_ID, MODEL_ID)
                self.save_record("model", MODEL_ID, self.model.model_dump())
                self.save_record(
                    "experiment_config",
                    MODEL_ID,
                    {"experiment_name": "replacement", "inference": {}},
                    data_format="yaml",
                )
                replacement_poll = self.submit()
                self.queue.put_message.reset_mock()
            return send_to_queue(processor, status=status)

        with patch.object(
            inference.InferencePreprocessor,
            "send_to_queue",
            autospec=True,
            side_effect=replace_before_cancellation,
        ):
            response = await self.cancel()

        self.assertEqual(response.status_code, 409)
        self.assertIsNotNone(replacement_poll)
        self.assertEqual(
            self.current().predictionRevision,
            replacement_poll.predictionRevision,
        )
        self.assertEqual(self.current().inferenceStatus, "InProgress")
        self.queue.put_message.assert_not_called()
        self.runner.cancel_task.assert_not_called()
        self.assertIsNone(
            inference.process_inference_request(original_poll, self.config)
        )
