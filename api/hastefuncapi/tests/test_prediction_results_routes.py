# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-results-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-results-api-tests")

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


def request(
    body: object = None, params: dict | None = None, method: str = "GET"
) -> func.HttpRequest:
    return func.HttpRequest(
        method=method,
        url="http://localhost/api/results",
        headers={},
        params=params or {},
        route_params={},
        body=json.dumps(body).encode() if body is not None else b"",
    )


class TestPredictionResultsRoutes(
    ResultsTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "config", self.config))
        self.logger = self.enterContext(patch.object(function_app, "logger"))

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

    def params(self, **kwargs: str) -> dict:
        return {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "modelId": MODEL_ID,
            **kwargs,
        }

    async def test_legacy_gpkg_downloads_without_attrs_or_tiles(self) -> None:
        self.save_record(
            "model",
            MODEL_ID,
            {
                "gpkgUrl": self.storage.get_download_url(
                    identifier="cached.gpkg"
                )
            },
        )
        self.save_record("imagelayer", LAYER_ID, {"footprintPmtilesUrl": None})
        response = await function_app.GetModelArtifact(
            request(params=self.params(kind="gpkg", version="0"))
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_body().startswith(b"SQLite format 3"))
        visualizer = await function_app.GetVisualizerResults(
            request(params=self.params())
        )
        payload = json.loads(visualizer.get_body())
        self.assertTrue(payload["rawPredictionsReady"])
        self.assertFalse(payload["predictionsReady"])

    async def test_put_then_get_requires_no_preparation_call(self) -> None:
        with patch(
            "hastegeo.core.utils.queues.AzureQueueHandler.put_message"
        ) as queue:
            saved = await function_app.PutBuildingPredictions(
                request(self.request().model_dump(), method="PUT")
            )
            self.assertEqual(saved.status_code, 200)
            result = await function_app.GetVisualizerResults(
                request(params=self.params())
            )
        queue.assert_not_called()
        payload = json.loads(result.get_body())
        self.assertEqual(result.status_code, 200)
        self.assertTrue(payload["predictionsReady"])
        self.assertEqual(payload["buildingCount"], 2)
        self.assertEqual(payload["flavor"], "embedding")
        self.assertIsNone(payload["predictedDamageLayer"])
        self.assertIn("predictionRevision=", payload["predictionAttrsUrl"])

    async def test_invalid_put_bodies_do_not_clear_existing_results(
        self,
    ) -> None:
        self.save_predictions()
        before = self.current().model_dump()
        valid = self.request().model_dump()
        for body in (
            [],
            None,
            {},
            {**valid, "predictions": None},
            {**valid, "predictions": "not a list"},
            {**valid, "predictions": [{"id": True, "damaged": 1}]},
            {**valid, "predictions": [{"id": 0, "damaged": 2}]},
            {
                **valid,
                "predictions": [
                    {"id": 0, "damaged": 1, "unknown": float("nan")}
                ],
            },
            {**valid, "imageLayerId": OTHER_LAYER},
        ):
            response = await function_app.PutBuildingPredictions(
                request(body, method="PUT")
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.current().model_dump(), before)

    async def test_clear_returns_zero_without_downloading_features(
        self,
    ) -> None:
        self.save_predictions()
        with patch(
            "hastegeo.core.artifact_storage.unified_artifact_storage.UnifiedArtifactStorage.fetch_artifact"
        ) as fetch:
            response = await function_app.PutBuildingPredictions(
                request(
                    self.request(predictions=[]).model_dump(), method="PUT"
                )
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body())["count"], 0)
        fetch.assert_not_called()
        rows = await function_app.GetLayerModelsDetails(
            request(
                params={
                    "projectId": PROJECT_ID,
                    "imageLayerId": LAYER_ID,
                }
            )
        )
        row = json.loads(rows.get_body())[0]
        self.assertFalse(row["predictionsReady"])
        self.assertEqual(row["buildingCount"], 0)

    async def test_artifact_wrong_layer_is_rejected_for_every_kind(
        self,
    ) -> None:
        with patch.object(
            function_app, "read_result_artifact", new_callable=AsyncMock
        ) as read:
            for kind in (
                "gpkg",
                "prediction_attrs",
                "footprint_pmtiles",
                "sidecar",
                "geojson",
            ):
                response = await function_app.GetModelArtifact(
                    request(
                        params=self.params(
                            imageLayerId=OTHER_LAYER,
                            kind=kind,
                        )
                    )
                )
                self.assertEqual(response.status_code, 400)
        read.assert_not_called()

    async def test_revision_pinned_attrs_are_proxied_without_cache_fallback(
        self,
    ) -> None:
        self.save_predictions()
        revision = self.current().predictionRevision
        params = self.params(
            kind="prediction_attrs", predictionRevision=revision
        )
        response = await function_app.GetModelArtifact(request(params=params))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(
            json.loads(response.get_body())["predictionRevision"], revision
        )
        self.save_predictions()
        retired = await function_app.GetModelArtifact(request(params=params))
        self.assertEqual(retired.status_code, 404)
        self.assertIn("no-store", retired.headers["Cache-Control"])

    async def test_raw_version_zero_keeps_range_download_semantics(
        self,
    ) -> None:
        self.save_predictions()
        req = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GetModelArtifact",
            params=self.params(kind="gpkg", version="0"),
            headers={"Range": "bytes=0-15"},
            body=b"",
        )
        response = await function_app.GetModelArtifact(req)
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.get_body()), 16)
        self.assertIn("bytes 0-15/", response.headers["Content-Range"])
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])

    async def test_artifact_missing_is_404_but_transport_failure_is_error(
        self,
    ) -> None:
        self.save_predictions()
        for error, status in (
            (ResourceNotFoundError("missing"), 404),
            (RuntimeError("https://storage?sig=secret"), 502),
        ):
            with patch.object(
                function_app,
                "read_result_artifact",
                new_callable=AsyncMock,
                side_effect=error,
            ):
                response = await function_app.GetModelArtifact(
                    request(params=self.params(kind="gpkg"))
                )
            self.assertEqual(response.status_code, status)
        self.assertNotIn("sig=secret", str(self.logger.mock_calls))

    async def test_malformed_version_requests_are_400(self) -> None:
        for overrides in (
            {"version": "-1"},
            {"predictionRevision": "../other"},
            {"modelId": "not-a-model"},
            {"kind": "prediction_tiles"},
            {"imageLayerId": "invalid"},
        ):
            response = await function_app.GetModelArtifact(
                request(
                    params={
                        **self.params(kind="gpkg"),
                        **overrides,
                    }
                )
            )
            self.assertEqual(response.status_code, 400)

    async def test_download_resolves_url_and_filename_from_one_model_read(
        self,
    ) -> None:
        baseline = {
            **self.record,
            "predictionGpkgFilename": "original.gpkg",
        }
        replacement = {
            **baseline,
            "gpkgUrl": "https://storage/replacement.gpkg",
            "predictionRevision": "replacement",
            "predictionGpkgFilename": "replacement.gpkg",
        }
        for params in ({}, {"predictionRevision": "old"}):
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
                    'attachment; filename="original.gpkg"',
                )
                read.assert_awaited_once_with(
                    baseline["gpkgUrl"], 0, 4, self.config
                )
                self.metadata.load.assert_called_once_with(MODEL_ID)

    async def test_framework_function_key_query_is_not_part_of_artifact_schema(
        self,
    ) -> None:
        self.save_predictions()
        response = await function_app.GetModelArtifact(
            request(
                params=self.params(
                    kind="PREDICTION_ATTRS",
                    code="function-key-secret",
                )
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("function-key-secret", str(self.logger.mock_calls))

    async def test_internal_validation_error_is_not_reported_as_bad_query(
        self,
    ) -> None:
        with patch(
            "hastegeo.core.processors.prediction_results.PredictionResultsProcessor.resolve_artifact",
            side_effect=ValueError("invalid stored metadata"),
        ):
            response = await function_app.GetModelArtifact(
                request(params=self.params(kind="gpkg"))
            )
        self.assertEqual(response.status_code, 500)

    async def test_valid_clear_with_corrupt_authority_is_sanitized_500(
        self,
    ) -> None:
        self.save_predictions()
        metadata = self.repository.metadata(PROJECT_ID, generations=True)
        authority = metadata.load_strict(MODEL_ID)
        path = Path(
            metadata.storage.get_file_remote_path(MODEL_ID, metadata.data_type)
        )
        for corrupt in (
            '{"private": "do-not-log",',
            json.dumps({**authority, "predictedBuildingCount": -1}),
        ):
            path.write_text(corrupt)
            response = await function_app.PutBuildingPredictions(
                request(
                    self.request(predictions=[]).model_dump(), method="PUT"
                )
            )
            self.assertEqual(response.status_code, 500)
            self.assertNotIn(b"Invalid JSON", response.get_body())
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    async def test_corrupt_authority_is_500_for_all_result_read_boundaries(
        self,
    ) -> None:
        self.save_predictions()
        metadata = self.repository.metadata(PROJECT_ID, generations=True)
        path = Path(
            metadata.storage.get_file_remote_path(MODEL_ID, metadata.data_type)
        )
        path.write_text('{"private": "do-not-log",')
        for name, params in (
            ("GetModelArtifact", self.params(kind="gpkg")),
            ("GetVisualizerResults", self.params()),
            ("GetLayerModelsDetails", self.params()),
            ("GetValidationReport", self.params()),
            ("GetAssessmentReport", self.params()),
        ):
            with self.subTest(handler=name):
                response = await getattr(function_app, name)(
                    request(params=params)
                )
                self.assertEqual(response.status_code, 500)
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    async def test_valid_body_with_invalid_coverage_remains_a_400(
        self,
    ) -> None:
        self.save_predictions()
        revision = self.current().predictionRevision
        response = await function_app.PutBuildingPredictions(
            request(
                self.request(
                    predictions=[{"id": 0, "damaged": 1}]
                ).model_dump(),
                method="PUT",
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.current().predictionRevision, revision)
        self.assertEqual(self.current().predictionState, "ready")

    async def test_delete_model_recreation_does_not_reuse_its_authority(
        self,
    ) -> None:
        self.save_predictions()
        previous = self.current().predictionRevision
        with patch.object(function_app, "StatsPreProcessor"):
            response = await function_app.DeleteModel(
                request(params=self.params(), method="DELETE")
            )
        self.assertEqual(response.status_code, 200)
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.assertNotEqual(self.current().predictionRevision, previous)
        self.assertIsNone(self.current().gpkgUrl)
        response = await function_app.GetModelArtifact(
            request(params=self.params(kind="gpkg"))
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(self.save_predictions()["predictionsReady"])

    async def test_layer_delete_cascade_also_retires_model_authority(
        self,
    ) -> None:
        self.save_predictions()
        previous = self.current().predictionRevision
        with patch.object(function_app, "StatsPreProcessor"):
            response = await function_app.DeleteLayer(
                request(params=self.params(), method="DELETE")
            )
        self.assertEqual(response.status_code, 200)
        self.save_record("imagelayer", LAYER_ID, self.layer.model_dump())
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.assertNotEqual(self.current().predictionRevision, previous)
        self.assertIsNone(self.current().gpkgUrl)
