# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("DATA_PATH", "/tmp/haste-results-api-tests")

from hastegeo.core.utils.blob import BlobRange  # noqa: E402

from api.hastefuncapi import function_app  # noqa: E402
from hastelib.tests.core.processors.test_prediction_results import (  # noqa: E402
    LAYER_ID,
    MODEL_ID,
    OTHER_LAYER,
    PROJECT_ID,
    ResultsTestCase,
)


class TestResultsRoutes(ResultsTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "config", self.config))

    def detail_metadata(self) -> tuple[dict, list[dict]]:
        layer = self.layer.model_dump()
        layer["creationDate"] = "2026-09-07T00:00:00Z"
        models = [
            {
                **self.record,
                "modelId": key,
                "modelType": kind,
                "creationDate": "2026-09-07T00:00:00Z",
            }
            for key, kind in ((MODEL_ID, "trained"), ("0043", "embedding"))
        ]

        def metadata(data_type: str, **_kwargs: Any) -> MagicMock:
            store = MagicMock()
            if data_type == "project":
                store.load.return_value = {"projectId": PROJECT_ID}
            elif data_type == "imagelayer":
                store.load.return_value = layer
                store.load_all_from_partition.return_value = [layer]
            elif data_type == "model":
                store.load_all_from_partition.return_value = models
            elif (
                data_type
                == self.config.get_metadata_types().MODEL_ARTIFACTS.value
            ):
                store.load.return_value = {"trainingZipUrl": "existing.zip"}
            elif data_type == "labels":
                store.load_all_from_partition.return_value = []
            elif data_type == "validation":
                store.load.return_value = {"labels": {}}
            else:
                store.export.return_value = "existing-labels.geojson"
            return store

        self.enterContext(
            patch.object(
                function_app, "MetadataProcessor", side_effect=metadata
            )
        )
        return layer, models

    async def test_project_rows_include_readiness_for_both_workflows(
        self,
    ) -> None:
        self.detail_metadata()
        response = await function_app.GetProjectDetails(
            self.http(includeModels="True")
        )
        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.get_body())["imageLayer"][0]["models"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row["predictionsReady"])
            self.assertEqual(row["buildingCount"], 2)
            self.assertEqual(row["predictionRevision"], "old")
            self.assertEqual(
                row["artifacts"]["trainingZipUrl"], "existing.zip"
            )

    async def test_layer_detail_uses_complete_readiness_not_url_presence(
        self,
    ) -> None:
        self.detail_metadata()
        response = await function_app.GetLayerDetailView(self.http())
        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.get_body())["models"]
        self.assertTrue(all(row["predictionsReady"] for row in rows))

        self.layer.footprintPmtilesUrl = None
        self.detail_metadata()
        response = await function_app.GetLayerDetailView(self.http())
        rows = json.loads(response.get_body())["models"]
        self.assertTrue(all(not row["predictionsReady"] for row in rows))
        self.assertTrue(all(row["rawPredictionsReady"] for row in rows))

    def http(self, body: Any = None, **params: str) -> func.HttpRequest:
        return func.HttpRequest(
            method="PUT" if body is not None else "GET",
            url="http://localhost/api/results",
            headers={"Range": "bytes=0-3"},
            params={
                "projectId": PROJECT_ID,
                "imageLayerId": LAYER_ID,
                "modelId": MODEL_ID,
                **params,
            },
            body=json.dumps(body).encode() if body is not None else b"",
        )

    async def test_clear_and_invalid_body_contracts(self) -> None:
        response = await function_app.PutBuildingPredictions(
            self.http(self.request(predictions=[]).model_dump())
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body())["buildingCount"], 0)
        for body in ({}, {"predictions": None}, {"predictions": "bad"}):
            self.assertEqual(
                (
                    await function_app.PutBuildingPredictions(self.http(body))
                ).status_code,
                400,
            )

    async def test_wrong_layer_and_storage_failure_are_distinct(self) -> None:
        response = await function_app.PutBuildingPredictions(
            self.http(self.request(imageLayerId=OTHER_LAYER).model_dump())
        )
        self.assertEqual(response.status_code, 400)
        self.metadata.load.side_effect = ValueError("corrupt Model JSON")
        response = await function_app.PutBuildingPredictions(
            self.http(self.request().model_dump())
        )
        self.assertEqual(response.status_code, 500)

    async def test_protected_artifact_query_range_and_cache(self) -> None:
        with patch.object(
            function_app,
            "read_result_artifact",
            new=AsyncMock(
                return_value=BlobRange(b"data", 20, "application/json", "etag")
            ),
        ) as read:
            response = await function_app.GetModelArtifact(
                self.http(kind="prediction_attrs", predictionRevision="old")
            )
        self.assertEqual(response.status_code, 206)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Content-Range"], "bytes 0-3/20")
        read.assert_awaited_once()
        self.assertEqual(
            (
                await function_app.GetModelArtifact(
                    self.http(kind="gpkg", predictionRevision="stale")
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            (
                await function_app.GetModelArtifact(
                    self.http(kind="gpkg", imageLayerId=OTHER_LAYER)
                )
            ).status_code,
            400,
        )

    async def test_legacy_raw_does_not_require_viewer_attributes(self) -> None:
        self.record["predictionAttrsUrl"] = None
        with patch.object(
            function_app,
            "read_result_artifact",
            new=AsyncMock(
                return_value=BlobRange(
                    b"gpkg", 4, "application/octet-stream", None
                )
            ),
        ):
            response = await function_app.GetModelArtifact(
                self.http(kind="gpkg", version="0")
            )
        self.assertEqual(response.status_code, 206)
        self.assertIn("attachment", response.headers["Content-Disposition"])

    async def test_download_preserves_safe_authoritative_inference_basename(
        self,
    ) -> None:
        for stored, expected in (
            ("inference/run-42.gpkg", "run-42.gpkg"),
            ("", f"building_predictions_{MODEL_ID}_raw.gpkg"),
            (
                'bad"\r\nInjected: true.gpkg',
                f"building_predictions_{MODEL_ID}_raw.gpkg",
            ),
        ):
            self.record["predictionGpkgFilename"] = stored
            with patch.object(
                function_app,
                "read_result_artifact",
                new=AsyncMock(
                    return_value=BlobRange(
                        b"gpkg", 4, "application/geopackage+sqlite3", None
                    )
                ),
            ):
                response = await function_app.GetModelArtifact(
                    self.http(kind="gpkg")
                )
            self.assertEqual(response.status_code, 206)
            self.assertEqual(
                response.headers["Content-Disposition"],
                f'attachment; filename="{expected}"',
            )
