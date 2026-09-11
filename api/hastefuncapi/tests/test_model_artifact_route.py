# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, Mock, patch

import azure.functions as func
from hastegeo.core.utils.blob import BlobRange

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-model-artifact-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-model-artifact-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"


class TestGetModelArtifact(unittest.IsolatedAsyncioTestCase):
    async def test_gpkg_response_is_a_named_download(self) -> None:
        request = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GetModelArtifact",
            headers={},
            params={
                "projectId": PROJECT_ID,
                "modelId": "42",
                "kind": "gpkg",
            },
            route_params={},
            body=b"",
        )
        processor = Mock()
        processor.load.return_value = {
            "gpkgUrl": "https://account.test/model.gpkg"
        }
        blob = BlobRange(
            data=b"gpkg",
            total_size=4,
            content_type="application/octet-stream",
            etag='"etag"',
        )

        with patch.object(
            function_app, "MetadataProcessor", return_value=processor
        ), patch.object(
            function_app,
            "read_blob_range",
            new=AsyncMock(return_value=blob),
        ):
            response = await function_app.GetModelArtifact(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="building_predictions_42.gpkg"',
        )


if __name__ == "__main__":
    unittest.main()
