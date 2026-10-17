# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-catalog-queue-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-catalog-queue-tests")

from api.hastefuncqueues import function_app  # noqa: E402


class TestCatalogQueueDispatch(unittest.IsolatedAsyncioTestCase):
    async def test_sparse_messages_bypass_the_legacy_metadata_fallback(
        self,
    ) -> None:
        payload = {
            "projectId": "11111111-1111-4111-8111-111111111111",
            "modelId": "1234",
            "inferenceRequestId": str(uuid4()),
        }
        processor = Mock()
        processor.process.side_effect = TimeoutError("queue unavailable")
        with patch.object(
            function_app, "CatalogInferenceProcessor", return_value=processor
        ), patch.object(function_app, "MetadataProcessor") as legacy_metadata:
            with self.assertRaises(TimeoutError):
                await function_app.GetRunInferenceQueueMessage(
                    func.QueueMessage(id="message", body=json.dumps(payload))
                )
        processor.process.assert_called_once_with(
            payload["projectId"],
            payload["modelId"],
            payload["inferenceRequestId"],
        )
        legacy_metadata.assert_not_called()
