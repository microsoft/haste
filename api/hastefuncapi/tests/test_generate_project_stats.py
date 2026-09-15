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
os.environ.setdefault("DATA_PATH", "/tmp/haste-project-stats-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-project-stats-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app


class TestGenerateProjectStats(unittest.IsolatedAsyncioTestCase):
    async def test_unlabeled_layer_counts_zero_and_labels_load_once(
        self,
    ) -> None:
        types = function_app.config.get_metadata_types()
        processors = {
            (types.PROJECT.value, None): Mock(),
            (types.IMAGELAYER.value, "project-1"): Mock(),
            (types.MODEL.value, "project-1"): Mock(),
            (types.LABELS.value, "project-1"): Mock(),
        }
        processors[(types.PROJECT.value, None)].load_all.return_value = [
            {
                "projectId": "project-1",
                "name": "Project",
                "description": "Description",
                "creationDate": "2026-01-01T00:00:00Z",
                "affectedCountries": [],
            }
        ]
        processors[
            (types.IMAGELAYER.value, "project-1")
        ].load_all_from_partition.return_value = [
            {"imageLayerId": "labeled"},
            {"imageLayerId": "unlabeled"},
        ]
        processors[
            (types.MODEL.value, "project-1")
        ].load_all_from_partition.return_value = []
        labels = processors[(types.LABELS.value, "project-1")]
        labels.load_all_from_partition.return_value = [
            {"imageLayerId": "labeled", "labels": [{"id": "label-1"}]}
        ]

        def processor_factory(*, data_type, partition_key=None):
            return processors[(data_type, partition_key)]

        request = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GenerateProjectStats",
            headers={},
            params={},
            route_params={},
            body=b"",
        )
        with patch.object(
            function_app, "MetadataProcessor", side_effect=processor_factory
        ):
            response = await function_app.GenerateProjectStats(request)

        self.assertEqual(response.status_code, 200)
        project = json.loads(response.get_body())["projects"][0]
        self.assertEqual(project["labelsCount"], 1)
        self.assertEqual(
            project["imageLayerStats"],
            [
                {"imageLayerId": "labeled", "labelsCount": 1},
                {"imageLayerId": "unlabeled", "labelsCount": 0},
            ],
        )
        labels.load_all_from_partition.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
