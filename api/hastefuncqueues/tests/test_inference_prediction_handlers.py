# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from unittest.mock import patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("DATA_PATH", "/tmp/haste-inference-queue-tests")

from api.hastefuncqueues import function_app  # noqa: E402


class TestInferenceQueue(unittest.IsolatedAsyncioTestCase):
    async def test_existing_model_payload_is_delegated_without_logging_urls(
        self,
    ) -> None:
        message = func.QueueMessage(
            body=b"""{
            "projectId":"p","imageLayerId":"l","modelId":"42",
            "currentInferenceTaskId":"task","gpkgUrl":"https://storage?sig=private"
        }"""
        )
        with patch.object(function_app, "logger") as logger, patch.object(
            function_app, "process_inference_request", return_value=None
        ) as process:
            await function_app.GetRunInferenceQueueMessage(message)
        self.assertEqual(
            process.call_args.args[0].currentInferenceTaskId, "task"
        )
        self.assertNotIn("private", str(logger.mock_calls))

    async def test_processing_error_propagates_for_retry_without_secret_text(
        self,
    ) -> None:
        with patch.object(
            function_app,
            "process_inference_request",
            side_effect=RuntimeError("sig=private"),
        ), patch.object(function_app, "logger") as logger:
            with self.assertRaises(RuntimeError) as error:
                await function_app.GetRunInferenceQueueMessage(
                    func.QueueMessage(body=b'{"modelId":"42"}')
                )
        self.assertNotIn("private", str(error.exception))
        self.assertNotIn("private", str(logger.mock_calls))
