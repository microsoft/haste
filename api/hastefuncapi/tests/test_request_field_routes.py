# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-request-field-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-request-field-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
LAYER_ID = "550e8400-e29b-41d4-a716-446655440000"


def make_layer_request(status: str | None) -> func.HttpRequest:
    body = {
        "projectId": PROJECT_ID,
        "imageLayerId": LAYER_ID,
        "name": "Renamed layer",
    }
    if status is not None:
        body["status"] = status
    return func.HttpRequest(
        method="PUT",
        url="http://localhost/api/PutLayer",
        headers={},
        params={},
        route_params={},
        body=json.dumps(body).encode(),
    )


class TestPutLayerServerManagedFields(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.processor = Mock()
        self.processor.load.return_value = {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "name": "Original layer",
            "status": "Processed",
        }
        patcher = patch.object(
            function_app, "MetadataProcessor", return_value=self.processor
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    async def test_edit_accepts_unchanged_server_managed_values(self) -> None:
        response = await function_app.PutLayer(make_layer_request("Processed"))

        self.assertEqual(response.status_code, 200)
        self.processor.save.assert_called_once()

    async def test_edit_rejects_changed_server_managed_values(self) -> None:
        response = await function_app.PutLayer(make_layer_request("Failed"))

        self.assertEqual(response.status_code, 400)
        self.processor.save.assert_not_called()

    async def test_partial_edit_preserves_omitted_server_state(self) -> None:
        response = await function_app.PutLayer(make_layer_request(None))

        self.assertEqual(response.status_code, 200)
        saved = self.processor.save.call_args.args[1]
        self.assertEqual(saved["status"], "Processed")


if __name__ == "__main__":
    unittest.main()
