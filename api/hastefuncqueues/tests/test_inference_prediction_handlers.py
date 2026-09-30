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
    async def test_raw_body_is_delegated_without_logging_url_secrets(
        self,
    ) -> None:
        body = (
            b'{"projectId":"p","imageLayerId":"l","modelId":"42",'
            b'"currentInferenceTaskId":"task",'
            b'"gpkgUrl":"https://storage?sig=private"}'
        )
        message = func.QueueMessage(body=body)
        with patch.object(function_app, "logger") as logger, patch.object(
            function_app, "JobQueueProcessor"
        ) as processor_class:
            await function_app.GetRunInferenceQueueMessage(message)
        processor_class.assert_called_once_with(function_app.config)
        process_message = processor_class.return_value.process_message
        self.assertEqual(
            process_message.call_args.args,
            (function_app.Workload.INFERENCE, body),
        )
        self.assertNotIn("private", str(logger.mock_calls))

    async def test_processing_error_propagates_for_retry_without_secret_text(
        self,
    ) -> None:
        with patch.object(
            function_app.JobQueueProcessor,
            "process",
            side_effect=RuntimeError("sig=private"),
        ), self.assertLogs(
            "hastegeo.core.processors.job_queue", level="ERROR"
        ) as logs:
            with self.assertRaises(RuntimeError) as error:
                await function_app.GetRunInferenceQueueMessage(
                    func.QueueMessage(body=b'{"modelId":"42"}')
                )
        self.assertNotIn("private", str(error.exception))
        self.assertIn(
            "Job queue dispatch failed: RuntimeError", str(error.exception)
        )
        self.assertNotIn("private", "\n".join(logs.output))
