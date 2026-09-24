# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from unittest.mock import AsyncMock, patch

import azure.functions as func
from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.processors.footprint_tiles import FOOTPRINT_TILE_FIELDS
from hastegeo.core.utils.blob import BlobRange
from hastegeo.core.utils.metadata import MetadataUtils

from .test_building_validation_routes import (
    LAYER_ID,
    PROJECT_ID,
    function_app,
    make_request,
    response_json,
)


class TestFootprintArtifactRoutes(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.metadata = self.enterContext(
            patch.object(function_app, "MetadataProcessor")
        ).return_value
        self.config = self.enterContext(
            patch.object(function_app, "config", wraps=function_app.config)
        )
        self.config.artifact_storage_type = "blob"
        self.config.artifact_storage_config = {"container": "data"}
        self.config.storage_config = {"container": "data"}
        self.url = (
            "https://acct.blob.core.windows.net/data/"
            f"{MetadataUtils.hash_string(PROJECT_ID)}/footprints_{LAYER_ID}.pmtiles"
        )
        self.layer = ImageLayer(
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            footprintPmtilesUrl=self.url,
            footprintTilesStatus="Processed",
        )
        self.metadata.load.return_value = self.layer.model_dump()

    async def test_layer_edits_cannot_replace_server_owned_tile_fields(
        self,
    ) -> None:
        body = {
            **self.layer.model_dump(),
            "name": "renamed",
            "footprintPmtilesUrl": "https://acct.blob.core.windows.net/private/secret",
            "footprintTilesStatus": "Failed",
            "footprintTilesRequestId": "forged",
        }
        response = await function_app.PutLayer(make_request(body))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response_json(response)["footprintPmtilesUrl"], self.url
        )
        written = self.metadata.save.call_args.args[1]
        self.assertFalse(FOOTPRINT_TILE_FIELDS & written.keys())
        self.assertEqual(written["name"], "renamed")

    async def test_new_layer_discards_client_tile_outputs_before_processing(
        self,
    ) -> None:
        self.metadata.load.side_effect = FileNotFoundError()
        with patch.object(
            function_app, "ImageryPreProcessor"
        ) as imagery, patch.object(function_app, "StatsPreProcessor"):
            imagery.return_value.queue_for_processing.side_effect = (
                lambda: imagery.call_args.kwargs["image_data"]
            )
            response = await function_app.PutLayer(
                make_request(self.layer.model_dump())
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(
            imagery.call_args.kwargs["image_data"].footprintPmtilesUrl
        )

    async def test_layer_artifact_validates_namespace_before_privileged_read(
        self,
    ) -> None:
        req = func.HttpRequest(
            method="GET",
            url="http://localhost/api/GetModelArtifact",
            headers={"Range": "bytes=0-3"},
            params={
                "projectId": PROJECT_ID,
                "imageLayerId": LAYER_ID,
                "kind": "footprint_pmtiles",
            },
            body=b"",
        )
        with patch.object(
            function_app, "read_blob_range", new_callable=AsyncMock
        ) as read:
            for url in (
                "https://acct.blob.core.windows.net/private/secret.json",
                self.url.replace(LAYER_ID, PROJECT_ID),
                self.url.replace(
                    MetadataUtils.hash_string(PROJECT_ID), "another-project"
                ),
            ):
                self.metadata.load.return_value = {
                    **self.layer.model_dump(),
                    "footprintPmtilesUrl": url,
                }
                self.assertEqual(
                    (await function_app.GetModelArtifact(req)).status_code, 400
                )
            read.assert_not_called()
            self.metadata.load.return_value = self.layer.model_dump()
            read.return_value = BlobRange(
                b"data", 20, "application/vnd.pmtiles", "etag"
            )
            response = await function_app.GetModelArtifact(req)
            self.assertEqual(response.status_code, 206)
            read.assert_awaited_once_with(self.url, 0, 4)
