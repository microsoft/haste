# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import base64
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import azure.functions as func
from hastegeo.core.models.projects import Model
from hastegeo.core.models.training import CatalogModel

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-catalog-api-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-catalog-api-tests")

with redirect_stderr(io.StringIO()):
    from api.hastefuncapi import function_app

PROJECT = "11111111-1111-4111-8111-111111111111"
LAYER = "22222222-2222-4222-8222-222222222222"


def request(
    body: object = None,
    params: dict | None = None,
    roles: list[str] | None = None,
) -> func.HttpRequest:
    principal = {
        "userId": "trusted-user",
        "userDetails": "trusted@example.test",
        "userRoles": roles or [],
    }
    headers = {}
    if roles is not None:
        headers["x-ms-client-principal"] = base64.b64encode(
            json.dumps(principal).encode()
        ).decode()
    return func.HttpRequest(
        method="PUT",
        url="http://localhost/api/catalog",
        headers=headers,
        params=params or {},
        route_params={},
        body=json.dumps(body).encode(),
    )


class TestCatalogRoutes(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.catalog = Mock()
        self.inference = Mock()
        self.enterContext(
            patch.object(
                function_app,
                "ModelCatalogProcessor",
                return_value=self.catalog,
            )
        )
        self.enterContext(
            patch.object(
                function_app,
                "CatalogInferenceProcessor",
                return_value=self.inference,
            )
        )

    async def test_development_catalog_distinguishes_empty_and_failure(
        self,
    ) -> None:
        self.catalog.list.return_value = []
        response = await function_app.GetModelCatalog(request())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body()), {"modelCatalog": []})
        self.catalog.list.side_effect = RuntimeError("offline")
        response = await function_app.GetModelCatalog(request())
        self.assertEqual(response.status_code, 500)

    async def test_catalog_passes_capability_and_validated_target(
        self,
    ) -> None:
        self.catalog.list.return_value = []
        response = await function_app.GetModelCatalog(
            request(
                params={
                    "capability": "inference",
                    "projectId": PROJECT,
                    "imageLayerId": LAYER,
                }
            )
        )
        self.assertEqual(response.status_code, 200)
        self.catalog.layer.assert_called_once_with(PROJECT, LAYER)
        self.assertEqual(
            self.catalog.list.call_args.kwargs["capability"], "inference"
        )
        response = await function_app.GetModelCatalog(
            request(
                params={
                    "projectId": PROJECT,
                }
            )
        )
        self.assertEqual(response.status_code, 400)

    async def test_submit_returns_accepted_root_model_without_training(
        self,
    ) -> None:
        self.inference.start.return_value = Model(
            projectId=PROJECT,
            imageLayerId=LAYER,
            modelId="1234",
            modelType="pretrained",
            inferenceStatus="Queued",
        )
        response = await function_app.PutRunCatalogInferenceQueueMessage(
            request(
                {
                    "projectId": PROJECT,
                    "imageLayerId": LAYER,
                    "baseModelName": "DINOv3",
                    "clientRequestId": str(uuid4()),
                }
            )
        )
        self.assertEqual(response.status_code, 202)
        result = json.loads(response.get_body())
        self.assertEqual(result["modelType"], "pretrained")
        self.assertIsNone(result["trainingJob"])

    async def test_submit_does_not_accept_browser_checkpoint_urls(
        self,
    ) -> None:
        response = await function_app.PutRunCatalogInferenceQueueMessage(
            request(
                {
                    "projectId": PROJECT,
                    "imageLayerId": LAYER,
                    "baseModelName": "DINOv3",
                    "clientRequestId": str(uuid4()),
                    "checkpointFilePath": "https://untrusted.test/model.ckpt",
                }
            )
        )
        self.assertEqual(response.status_code, 400)
        self.inference.start.assert_not_called()

    async def test_production_management_requires_administrator(self) -> None:
        with patch.object(function_app, "DEVELOPMENT_MODE", False):
            for roles in (None, ["authenticated"], ["contributors"]):
                with self.subTest(roles=roles):
                    response = await function_app.DeleteModelCatalog(
                        request(
                            params={"baseModelName": "External"}, roles=roles
                        )
                    )
                    self.assertEqual(response.status_code, 403)
        self.catalog.delete.assert_not_called()

    async def test_production_creator_comes_from_trusted_identity(
        self,
    ) -> None:
        self.catalog.add.side_effect = lambda entry: entry
        body = CatalogModel(
            source="external",
            baseModelName="External",
            checkpointFilePath="catalog/approved.ckpt",
            cataloguedByUser="forged@example.test",
        ).model_dump(mode="json")
        with patch.object(function_app, "DEVELOPMENT_MODE", False):
            response = await function_app.PutModelCatalog(
                request(body, roles=["administrators"])
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.catalog.add.call_args.args[0].cataloguedByUser,
            "trusted@example.test",
        )

    async def test_production_reader_cannot_submit_inference(self) -> None:
        with patch.object(function_app, "DEVELOPMENT_MODE", False):
            response = await function_app.PutRunCatalogInferenceQueueMessage(
                request({}, roles=["authenticated"])
            )
        self.assertEqual(response.status_code, 403)
        self.inference.start.assert_not_called()

    async def test_external_delete_uses_name_without_model_id(self) -> None:
        self.catalog.delete.return_value = {"baseModelName": "External"}
        response = await function_app.DeleteModelCatalog(
            request(params={"baseModelName": "External"})
        )
        self.assertEqual(response.status_code, 200)
        self.catalog.delete.assert_called_once_with("External", None)

    async def test_catalog_rejects_non_object_input_without_writes(
        self,
    ) -> None:
        response = await function_app.PutModelCatalog(request([]))
        self.assertEqual(response.status_code, 400)
        self.catalog.add.assert_not_called()

    async def test_catalog_results_have_full_extent_without_training_labels(
        self,
    ) -> None:
        records = {
            "model": {
                "projectId": PROJECT,
                "imageLayerId": LAYER,
                "modelId": "1234",
                "modelType": "pretrained",
                "inferenceStatus": "Processed",
                "predictedDamageLayerUrl": "https://example.test/model_visualizer.tif",
            },
            "project": {"projectId": PROJECT, "name": "Project"},
            "imagelayer": {"projectId": PROJECT, "imageLayerId": LAYER},
            "labels": {},
        }
        stores = {kind: Mock() for kind in records}
        for kind, store in stores.items():
            store.load.return_value = records[kind]
            store.load_all_from_partition.return_value = []
        feature = {
            "type": "Feature",
            "bbox": [-1, -1, 1, 1],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]]
                ],
            },
        }
        with patch.object(
            function_app,
            "MetadataProcessor",
            side_effect=lambda **kwargs: stores[kwargs["data_type"]],
        ), patch(
            "hastegeo.core.utils.aoi.raster_extent_feature",
            return_value=feature,
        ) as extent:
            response = await function_app.GetVisualizerResults(
                request(
                    params={
                        "projectId": PROJECT,
                        "imageLayerId": LAYER,
                        "modelId": "1234",
                    }
                )
            )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_body())
        self.assertEqual(data["studyArea"][0]["bbox"], [-1, -1, 1, 1])
        self.assertEqual(
            data["predictedDamageLayer"]["bounds"], [-1, -1, 1, 1]
        )
        self.assertEqual(data["postDisasterImagery"]["url"], "")
        extent.assert_called_once()
        for store in stores.values():
            store.save.assert_not_called()

    async def test_inference_overlays_request_png_for_all_model_types(
        self,
    ) -> None:
        image_url = "https://example.test/imagery.tif"
        visualizer_url = "https://example.test/model_visualizer.tif"
        for model_type in ("trained", "pretrained"):
            with self.subTest(model_type=model_type):
                records = {
                    "model": {
                        "projectId": PROJECT,
                        "imageLayerId": LAYER,
                        "modelId": "1234",
                        "modelType": model_type,
                        "inferenceStatus": "Processed",
                        "predictedDamageLayerUrl": visualizer_url,
                    },
                    "project": {"projectId": PROJECT, "name": "Project"},
                    "imagelayer": {
                        "projectId": PROJECT,
                        "imageLayerId": LAYER,
                        "postEventProcessedImageryUrl": image_url,
                    },
                }
                stores = {kind: Mock() for kind in (*records, "labels")}
                for kind, record in records.items():
                    stores[kind].load.return_value = record
                feature = {"type": "Feature", "bbox": [-1, -1, 1, 1]}
                stores["labels"].load_all_from_partition.return_value = [
                    {"imageLayerId": LAYER, "features": [feature]}
                ]
                with patch.object(
                    function_app,
                    "MetadataProcessor",
                    side_effect=lambda **kwargs: stores[kwargs["data_type"]],
                ), patch(
                    "hastegeo.core.utils.aoi.raster_extent_feature",
                    return_value=feature,
                ):
                    response = await function_app.GetVisualizerResults(
                        request(
                            params={
                                "projectId": PROJECT,
                                "imageLayerId": LAYER,
                                "modelId": "1234",
                            }
                        )
                    )
                self.assertEqual(response.status_code, 200)
                data = json.loads(response.get_body())
                for overlay in ("predictedDamageLayer", "predictionsLayer"):
                    self.assertTrue(
                        urlsplit(data[overlay]["url"]).path.endswith(
                            "/{z}/{x}/{y}.png"
                        )
                    )
                raw_query = parse_qs(
                    urlsplit(data["predictionsLayer"]["url"]).query
                )
                colormap = json.loads(raw_query["colormap"][0])
                self.assertEqual(colormap["1"], [0, 0, 0, 0])
                self.assertEqual(colormap["3"], [255, 0, 0, 255])
                self.assertEqual(
                    raw_query["url"],
                    [visualizer_url.replace("_visualizer", "_predictions")],
                )
                self.assertFalse(
                    urlsplit(data["postDisasterImagery"]["url"]).path.endswith(
                        ".png"
                    )
                )
