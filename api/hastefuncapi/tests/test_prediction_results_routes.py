# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

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
