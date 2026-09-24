# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from contextlib import nullcontext
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func
from azure.core.exceptions import HttpResponseError

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("DATA_PATH", "/tmp/haste-results-api-tests")

from hastegeo.core.processors.project_details import (  # noqa: E402
    ProjectDetailsProcessor,
)
from hastegeo.core.utils.async_cache import AsyncTTLCache  # noqa: E402
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

    def detail_metadata(self) -> None:
        layer = {**self.layer.model_dump(), "creationDate": "2026-09-18"}
        models = [
            {
                **self.record,
                "modelId": key,
                "modelType": kind,
                "creationDate": "2026-09-18",
                "labelsUrl": "existing-labels.geojson",
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
                store.load_map.return_value = {
                    model["modelId"]: {"trainingZipUrl": "existing.zip"}
                    for model in models
                }
            elif data_type == "labels":
                store.load_all_from_partition.return_value = []
            elif data_type == "validation":
                store.load_map.return_value = {LAYER_ID: {"labels": {}}}
            return store

        self.enterContext(
            patch.object(
                function_app, "MetadataProcessor", side_effect=metadata
            )
        )
        self.enterContext(
            patch(
                "hastegeo.core.processors.prediction_results.MetadataProcessor",
                side_effect=lambda kind, project_id, config: metadata(kind),
            )
        )
        self.enterContext(
            patch.object(
                function_app,
                "ProjectDetailsProcessor",
                side_effect=lambda project_id, config: ProjectDetailsProcessor(
                    project_id, config, processor_factory=metadata
                ),
            )
        )
        self.enterContext(
            patch.object(
                function_app,
                "_project_details_cache",
                AsyncTTLCache(ttl_seconds=15, max_entries=16),
            )
        )

    async def test_all_model_row_routes_share_readiness_for_both_workflows(
        self,
    ) -> None:
        for state, ready, raw_ready in (
            ("ready", True, True),
            ("missing_attributes", False, True),
            ("missing_footprint_tiles", False, True),
            ("empty", False, False),
        ):
            with self.subTest(state=state):
                self.record["predictionAttrsUrl"] = (
                    None
                    if state == "missing_attributes"
                    else "https://storage/old.json"
                )
                self.record["predictedBuildingCount"] = (
                    0 if state == "empty" else 2
                )
                self.layer.footprintPmtilesUrl = (
                    None
                    if state == "missing_footprint_tiles"
                    else "https://storage/tiles"
                )
                self.detail_metadata()
                project = await function_app.GetProjectDetails(
                    self.http(includeModels="True")
                )
                detail = await function_app.GetLayerDetailView(self.http())
                listing = await function_app.GetLayerModelsDetails(self.http())
                for response in (project, detail, listing):
                    self.assertEqual(response.status_code, 200)
                project_rows = json.loads(project.get_body())["imageLayer"][0][
                    "models"
                ]
                detail_rows = json.loads(detail.get_body())["models"]
                listed_rows = json.loads(listing.get_body())
                self.assertEqual(
                    {row["modelType"] for row in project_rows},
                    {"trained", "embedding"},
                )
                for rows in (project_rows, detail_rows, listed_rows):
                    self.assertEqual(len(rows), 2)
                    for row in rows:
                        self.assertEqual(row["predictionsReady"], ready)
                        self.assertEqual(row["rawPredictionsReady"], raw_ready)
                        self.assertEqual(
                            row["predictionsReadiness"]["reason"], state
                        )
                        self.assertEqual(bool(row["gpkgUrl"]), raw_ready)
                        self.assertEqual(
                            row["labelsUrl"], "existing-labels.geojson"
                        )
                for row in project_rows:
                    self.assertEqual(
                        row["artifacts"]["trainingZipUrl"], "existing.zip"
                    )
                for row, detailed, listed in zip(
                    project_rows, detail_rows, listed_rows
                ):
                    for (
                        key
                    ) in function_app.PredictionResultsProcessor.response(
                        function_app.Model.model_validate(self.record),
                        self.layer,
                    ):
                        self.assertEqual(row[key], detailed[key])
                        self.assertEqual(row[key], listed[key])

    async def test_all_model_row_routes_keep_current_edited_source(
        self,
    ) -> None:
        self.record["gpkgUrl"] = None
        self.record["editedPredictions"] = [
            {
                "version": version,
                "gpkgUrl": f"https://storage/edited-{version}.gpkg",
                "predictionAttrsUrl": f"https://storage/edited-{version}.json",
                "sourcePredictionRevision": revision,
                "buildingCount": 2,
                "editedCount": 1,
            }
            for version, revision in ((1, "old"), (2, "retired"), (3, "old"))
        ]
        self.detail_metadata()
        project = await function_app.GetProjectDetails(
            self.http(includeModels="True")
        )
        detail = await function_app.GetLayerDetailView(self.http())
        listing = await function_app.GetLayerModelsDetails(self.http())
        for response in (project, detail, listing):
            self.assertEqual(response.status_code, 200)
        for rows in (
            json.loads(project.get_body())["imageLayer"][0]["models"],
            json.loads(detail.get_body())["models"],
            json.loads(listing.get_body()),
        ):
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertEqual(row["predictionVersion"], 3)
                self.assertEqual(row["currentPredictionRevision"], "old")
                self.assertTrue(row["hasEditedPredictions"])
                self.assertTrue(row["predictionsReady"])
                self.assertFalse(row["rawPredictionsReady"])
                self.assertIn("version=3", row["gpkgUrl"])
                self.assertIn("version=3", row["predictionAttrsUrl"])
                self.assertEqual(len(row["editedPredictions"]), 3)

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

    async def test_storage_500_logs_safe_service_diagnostics(self) -> None:
        error = HttpResponseError("https://storage/blob?sig=private-token")
        error.status_code = 403
        error.error_code = "AuthorizationPermissionMismatch"
        with patch.object(
            function_app.PredictionResultsProcessor,
            "save_building_predictions",
            side_effect=error,
        ), patch.object(function_app, "logger") as logger:
            response = await function_app.PutBuildingPredictions(
                self.http(self.request().model_dump())
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_body(), b"Error saving building predictions."
        )
        diagnostics = logger.error.call_args.args[2][0]
        self.assertEqual(diagnostics["status"], 403)
        self.assertEqual(
            diagnostics["code"], "AuthorizationPermissionMismatch"
        )
        self.assertTrue(diagnostics["frames"])
        self.assertNotIn("private-token", str(logger.mock_calls))

    async def test_renewal_lease_loss_returns_conflict_without_publication(
        self,
    ) -> None:
        lease = MagicMock()
        error = HttpResponseError("lease lost")
        error.status_code = 409
        error.error_code = "LeaseIdMismatchWithLeaseOperation"
        lease.renew.side_effect = error
        with patch(
            "hastegeo.core.processors.prediction_results.prediction_edit_lock",
            return_value=nullcontext(lease),
        ):
            response = await function_app.PutBuildingPredictions(
                self.http(self.request(predictions=[]).model_dump())
            )
        self.assertEqual(response.status_code, 409)
        self.metadata.save.assert_not_called()
        self.assertEqual(self.record["predictionRevision"], "old")

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
        self.assertNotIn("Content-Disposition", response.headers)
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

    async def test_download_resolves_url_and_filename_from_one_model_read(
        self,
    ) -> None:
        baseline = {
            **self.record,
            "predictionGpkgFilename": "original.gpkg",
            "editedPredictions": [
                {
                    "version": 2,
                    "gpkgUrl": "https://storage/edited.gpkg",
                    "sourcePredictionRevision": "old",
                    "buildingCount": 2,
                }
            ],
        }
        replacement = {
            **baseline,
            "gpkgUrl": "https://storage/replacement.gpkg",
            "predictionRevision": "replacement",
            "predictionGpkgFilename": "replacement.gpkg",
        }
        for params, expected_url, filename in (
            ({}, baseline["gpkgUrl"], "original.gpkg"),
            (
                {"predictionRevision": "old"},
                baseline["gpkgUrl"],
                "original.gpkg",
            ),
            (
                {"version": "2", "predictionRevision": "old"},
                "https://storage/edited.gpkg",
                f"building_predictions_{MODEL_ID}_v2.gpkg",
            ),
        ):
            with self.subTest(params=params):
                self.metadata.load.reset_mock()
                self.metadata.load.side_effect = [baseline, replacement]
                with patch.object(
                    function_app,
                    "read_result_artifact",
                    new=AsyncMock(
                        return_value=BlobRange(
                            b"gpkg", 4, "application/geopackage+sqlite3", None
                        )
                    ),
                ) as read:
                    response = await function_app.GetModelArtifact(
                        self.http(kind="gpkg", **params)
                    )
                self.assertEqual(response.status_code, 206)
                self.assertEqual(
                    response.headers["Content-Disposition"],
                    f'attachment; filename="{filename}"',
                )
                read.assert_awaited_once_with(expected_url, 0, 4, self.config)
                self.metadata.load.assert_called_once_with(MODEL_ID)

    async def test_nonversioned_artifact_kinds_reject_explicit_raw_zero(
        self,
    ) -> None:
        for kind in ("sidecar", "geojson", "footprint_pmtiles"):
            for version in ("0", "1"):
                response = await function_app.GetModelArtifact(
                    self.http(kind=kind, version=version)
                )
                self.assertEqual(response.status_code, 400)
