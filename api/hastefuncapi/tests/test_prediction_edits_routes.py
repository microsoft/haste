# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import azure.functions as func

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-edit-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-edit-api-tests")

from hastegeo.core.processors.prediction_edits import (  # noqa: E402
    PredictionEditConflict,
)

from api.hastefuncapi import function_app  # noqa: E402
from hastelib.tests.core.processors.test_prediction_edits import (  # noqa: E402
    EditTestCase,
)
from hastelib.tests.core.processors.test_prediction_results import (  # noqa: E402
    LAYER_ID,
    MODEL_ID,
    OTHER_LAYER,
    PROJECT_ID,
)


class TestPredictionEditingRoutes(
    EditTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "config", self.config))
        self.enterContext(patch.object(function_app, "DEVELOPMENT_MODE", True))
        self.logger = self.enterContext(patch.object(function_app, "logger"))

    def params(self, **extra: str) -> dict[str, str]:
        return {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "modelId": MODEL_ID,
            **extra,
        }

    def http(
        self, body: dict | None = None, **params: str
    ) -> func.HttpRequest:
        return func.HttpRequest(
            method="PUT" if body is not None else "GET",
            url="http://localhost/api/predictions",
            headers={},
            params=self.params(**params),
            body=json.dumps(body).encode() if body is not None else b"",
        )

    async def save_http(self, body: dict | None = None) -> func.HttpResponse:
        return await function_app.PutEditedPredictions(
            self.http(
                body
                if body is not None
                else self.edit_request().model_dump(mode="json", by_alias=True)
            )
        )

    async def test_save_returns_exact_reload_identity_and_real_pair(
        self,
    ) -> None:
        result = await self.save_http()
        self.assertEqual(result.status_code, 200)
        saved = json.loads(result.get_body())
        self.assertTrue(
            {
                "version",
                "predictionRevision",
                "gpkgUrl",
                "predictionAttrsUrl",
                "buildingCount",
                "editedCount",
            }.issubset(saved)
        )
        self.assertEqual(saved["version"], 1)
        self.assertEqual(
            self.current().editedPredictions[0].createdBy, "development@local"
        )
        visualizer = await function_app.GetVisualizerResults(self.http())
        view = json.loads(visualizer.get_body())
        self.assertEqual(view["predictionVersion"], 1)
        self.assertTrue(view["editReadiness"]["ready"])
        self.assertEqual(
            view["predictionRevision"], saved["predictionRevision"]
        )
        self.assertEqual(
            view["predictionVersions"][0]["predictionRevision"],
            saved["predictionRevision"],
        )
        attrs_response = await function_app.GetModelArtifact(
            self.http(
                kind="prediction_attrs",
                version="1",
                predictionRevision=saved["predictionRevision"],
            )
        )
        self.assertEqual(attrs_response.status_code, 200)
        self.assertEqual(
            json.loads(attrs_response.get_body())["predictionVersion"], 1
        )
        self.assertIn("no-store", attrs_response.headers["Cache-Control"])

    async def test_unknown_positive_version_is_404_and_bad_version_is_400(
        self,
    ) -> None:
        for handler in (
            function_app.GetVisualizerResults,
            function_app.GetValidationReport,
            function_app.GetAssessmentReport,
        ):
            self.assertEqual(
                (await handler(self.http(version="123"))).status_code, 404
            )
            self.assertEqual(
                (await handler(self.http(version="-1"))).status_code, 400
            )
        self.assertEqual(
            (
                await function_app.GetModelArtifact(
                    self.http(kind="gpkg", version="123")
                )
            ).status_code,
            404,
        )
        self.assertFalse(hasattr(function_app, "GetPredictionEditSession"))

    async def test_malformed_save_is_400_before_execution(self) -> None:
        body = self.edit_request().model_dump(mode="json", by_alias=True)
        for change in (
            {"clientRequestId": "bad"},
            {"baseVersion": True},
            {"overrides": [{"id": 0, "class": "Invalid"}]},
            {"createdBy": "spoofed"},
        ):
            response = await self.save_http({**body, **change})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                json.loads(response.get_body())["error"]["code"],
                "invalid_request",
            )
        self.assertEqual(self.current().editedPredictions, [])

    async def test_exact_building_location_uses_existing_footprint_endpoint(
        self,
    ) -> None:
        path = Path(self.directory, "location-input.gpkg")
        shutil.copyfile(
            self.local_path(self.layer.buildingFootprintsUrl), path
        )
        with patch.object(
            function_app, "MetadataProcessor"
        ) as metadata, patch.object(
            function_app,
            "download_blob_to_tempfile",
            new=AsyncMock(return_value=str(path)),
        ):
            metadata.return_value.load.return_value = self.layer.model_dump()
            response = await function_app.GetBuildingFootprintsGeoJSON(
                self.http(buildingId="building-1", sample="1")
            )
        self.assertEqual(response.status_code, 200)
        features = json.loads(response.get_body())["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(
            features[0]["properties"], {"id": "building-1", "rowId": 1}
        )
        self.assertEqual(features[0]["geometry"]["type"], "Point")
        self.assertFalse(path.exists())

    async def test_invalid_building_lookup_does_not_read_storage(self) -> None:
        with patch.object(function_app, "MetadataProcessor") as metadata:
            for building_id in ("", " leading", "x" * 1025):
                response = await function_app.GetBuildingFootprintsGeoJSON(
                    self.http(buildingId=building_id)
                )
                self.assertEqual(response.status_code, 400)
            metadata.assert_not_called()

    async def test_conflicts_keep_status_and_machine_readable_code(
        self,
    ) -> None:
        for code in ("source_changed", "request_conflict", "save_conflict"):
            with patch.object(
                function_app.PredictionEditsProcessor,
                "save",
                side_effect=PredictionEditConflict(
                    code, "Safe conflict detail"
                ),
            ):
                response = await self.save_http()
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                json.loads(response.get_body())["error"]["code"], code
            )

    async def test_internal_storage_error_is_sanitized_500_not_bad_request(
        self,
    ) -> None:
        with patch.object(
            function_app.PredictionEditsProcessor,
            "save",
            side_effect=ValueError("https://storage?sig=private-token"),
        ):
            response = await self.save_http()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            json.loads(response.get_body())["error"]["code"], "internal_error"
        )
        self.assertNotIn("private-token", str(self.logger.mock_calls))
        self.assertNotIn(b"private-token", response.get_body())

    async def test_wrong_layer_is_rejected_across_version_consumers(
        self,
    ) -> None:
        self.edit()
        handlers = (
            function_app.GetEditedPredictionVersions,
            function_app.GetVisualizerResults,
            function_app.GetValidationReport,
            function_app.GetAssessmentReport,
        )
        for handler in handlers:
            response = await handler(
                self.http(imageLayerId=OTHER_LAYER, version="1")
                if handler != function_app.GetEditedPredictionVersions
                else self.http(imageLayerId=OTHER_LAYER)
            )
            self.assertEqual(response.status_code, 400)
        response = await function_app.GetModelArtifact(
            self.http(imageLayerId=OTHER_LAYER, kind="gpkg", version="1")
        )
        self.assertEqual(response.status_code, 400)

    async def test_historical_selection_works_after_clear_but_new_edit_conflicts(
        self,
    ) -> None:
        request = self.edit_request()
        body = request.model_dump(mode="json", by_alias=True)
        first = json.loads((await self.save_http(body)).get_body())
        self.save_predictions(predictions=[])
        replay = await self.save_http(body)
        self.assertEqual(json.loads(replay.get_body()), first)
        historical = await function_app.GetVisualizerResults(
            self.http(version="1")
        )
        view = json.loads(historical.get_body())
        self.assertEqual(view["predictionVersion"], 1)
        self.assertTrue(view["predictionsReady"])
        self.assertFalse(view["editReadiness"]["ready"])
        default = json.loads(
            (await function_app.GetVisualizerResults(self.http())).get_body()
        )
        self.assertEqual(default["predictionVersion"], 0)
        self.assertFalse(default["predictionsReady"])
        response = await self.save_http(
            self.edit_request(
                predictionRevision=request.predictionRevision, baseVersion=1
            ).model_dump(mode="json", by_alias=True)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            json.loads(response.get_body())["error"]["code"], "source_changed"
        )

    async def test_contributor_permission_is_required(self) -> None:
        with patch.object(
            function_app,
            "_get_active_publishing_caller",
            new=AsyncMock(
                return_value=({"id": "reader", "roles": {"readers"}}, None)
            ),
        ):
            response = await self.save_http()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.current().editedPredictions, [])

    async def test_missing_principal_is_rejected_outside_development_mode(
        self,
    ) -> None:
        with patch.object(function_app, "DEVELOPMENT_MODE", False):
            response = await self.save_http()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.current().editedPredictions, [])

    async def test_positive_download_keeps_range_and_version_filename(
        self,
    ) -> None:
        self.edit()
        response = await function_app.GetModelArtifact(
            func.HttpRequest(
                method="GET",
                url="http://localhost/api/GetModelArtifact",
                params=self.params(kind="gpkg", version="1"),
                headers={"Range": "bytes=0-15"},
                body=b"",
            )
        )
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.get_body()), 16)
        self.assertIn("_v1.gpkg", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
