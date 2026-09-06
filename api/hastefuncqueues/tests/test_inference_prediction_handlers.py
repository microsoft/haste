# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import traceback
import unittest
from unittest.mock import patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-results-queue-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-results-queue-tests")

from hastegeo.core.models.prediction_results import (  # noqa: E402
    InferenceQueueRequest,
)

from api.hastefuncqueues import function_app  # noqa: E402


class TestInferencePredictionHandlers(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_secret_fields_are_not_forwarded_or_logged(
        self,
    ) -> None:
        message = func.QueueMessage(
            body=b"""{
            "projectId":"123e4567-e89b-12d3-a456-426614174000",
            "imageLayerId":"550e8400-e29b-41d4-a716-446655440000",
            "modelId":"0042","predictionRevision":"generation-1",
            "gpkgUrl":"https://storage?sig=secret"
        }"""
        )
        with patch.object(function_app, "logger") as logger, patch.object(
            function_app, "process_inference_request", return_value=None
        ) as process, patch.object(
            function_app, "enqueue_inference_artifacts"
        ) as zip_queue:
            await function_app.GetRunInferenceQueueMessage(message)
        parsed = process.call_args.args[0]
        self.assertIsInstance(parsed, InferenceQueueRequest)
        self.assertNotIn("secret", parsed.model_dump_json())
        self.assertNotIn("secret", str(logger.mock_calls))
        zip_queue.assert_not_called()

    async def test_unexpected_failure_propagates_without_saving_old_snapshot(
        self,
    ) -> None:
        message = func.QueueMessage(
            body=b"""{
            "projectId":"123e4567-e89b-12d3-a456-426614174000",
            "imageLayerId":"550e8400-e29b-41d4-a716-446655440000",
            "modelId":"0042","predictionRevision":"generation-1"
        }"""
        )
        with patch.object(function_app, "logger") as logger, patch.object(
            function_app,
            "process_inference_request",
            side_effect=RuntimeError("https://storage?sig=secret"),
        ), patch.object(function_app, "MetadataProcessor") as metadata:
            try:
                await function_app.GetRunInferenceQueueMessage(message)
            except RuntimeError:
                self.assertNotIn("secret", traceback.format_exc())
            else:
                self.fail("Queue failure must retry")
        metadata.assert_not_called()
        self.assertNotIn("secret", str(logger.mock_calls))
