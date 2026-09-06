# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import traceback
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import azure.functions as func
import requests

os.environ.setdefault("DEVELOPMENT_MODE", "true")
os.environ.setdefault("METADATA_STORAGE_TYPE", "local")
os.environ.setdefault("ARTIFACT_STORAGE_TYPE", "local")
os.environ.setdefault("DATA_PATH", "/tmp/haste-footprint-queue-tests")
os.environ.setdefault("TEMP_DATA_PATH", "/tmp/haste-footprint-queue-tests")

from hastegeo.core.models.footprint_tiles import (  # noqa: E402
    FootprintTilesRequest,
)
from hastegeo.core.processors import footprint_tiles  # noqa: E402
from hastegeo.core.utils.blob import fetch_url_text  # noqa: E402

from api.hastefuncqueues import function_app  # noqa: E402
from hastelib.tests.core.processors.test_footprint_tiles import (  # noqa: E402
    SECRET_URL,
    STATUSES,
    FootprintTestCase,
    _job,
    _layer,
)


class TestFootprintQueueHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.logger = self.enterContext(patch.object(function_app, "logger"))
        self.process = self.enterContext(
            patch.object(function_app, "process_tiles_request")
        )

    async def test_legacy_message_delegates_validated_authoritative_request(
        self,
    ) -> None:
        await function_app.GetPrepareFootprintTilesQueueMessage(
            func.QueueMessage(
                id="message-1",
                body=json.dumps(
                    {
                        "projectId": "proj-1",
                        "imageLayerId": _layer().imageLayerId,
                        "sourceFootprintsUrl": SECRET_URL,
                        "force": True,
                    }
                ),
            )
        )
        request = self.process.call_args.args[0]
        self.assertIsInstance(request, FootprintTilesRequest)
        self.assertTrue(request.force)
        self.assertEqual(request.requestId, "message-1")
        self.assertNotIn("do-not-log", request.model_dump_json())
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    async def test_invalid_messages_raise_sanitized_errors_for_poison(
        self,
    ) -> None:
        for body in (
            SECRET_URL,
            "[]",
            json.dumps(
                {
                    "projectId": "proj-1",
                    "imageLayerId": _layer().imageLayerId,
                    "force": SECRET_URL,
                }
            ),
            json.dumps({"projectId": SECRET_URL}),
        ):
            with self.subTest(body=body):
                try:
                    await function_app.GetPrepareFootprintTilesQueueMessage(
                        func.QueueMessage(id="message-1", body=body)
                    )
                except RuntimeError:
                    formatted = traceback.format_exc()
                    self.assertNotIn("do-not-log", formatted)
                    self.assertIn("retry/poison", formatted)
                else:
                    self.fail(
                        "Invalid messages must reach retry/poison handling"
                    )
        self.process.assert_not_called()
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    async def test_unexpected_errors_are_not_acknowledged_or_leaked(
        self,
    ) -> None:
        for error in (
            RuntimeError(SECRET_URL),
            OSError(SECRET_URL),
            ValueError(SECRET_URL),
        ):
            self.process.side_effect = error
            try:
                await function_app.GetPrepareFootprintTilesQueueMessage(
                    func.QueueMessage(
                        id="message-1",
                        body=json.dumps(
                            {
                                "projectId": "proj-1",
                                "imageLayerId": _layer().imageLayerId,
                                "buildingFootprintsUrl": SECRET_URL,
                            }
                        ),
                    )
                )
            except RuntimeError:
                formatted = traceback.format_exc()
                self.assertNotIn("do-not-log", formatted)
                self.assertIn(type(error).__name__, formatted)
            else:
                self.fail("Unexpected errors must not acknowledge the message")
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))


class TestImageryQueueHandoff(
    FootprintTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch.object(function_app, "logger"))
        self.enterContext(patch.object(function_app, "config", self.config))
        # The wrapper's direct metadata calls are the deletion check and
        # LabelProject save. ImageLayer saves use the real core helper.
        self.metadata = self.enterContext(
            patch.object(function_app, "MetadataProcessor")
        ).return_value
        self.metadata.load.return_value = self.record
        self.imagery = self.enterContext(
            patch.object(function_app, "ImageryPostProcessor")
        ).return_value
        self.imagery.process.return_value = _layer(
            status=STATUSES.COMPLETED.value
        )
        self.labels = self.enterContext(
            patch.object(function_app, "LabelTaskGenerator")
        ).return_value
        label_project = MagicMock()
        label_project.labelprojectId = "label-project-1"
        self.labels.generate_task_files.return_value = label_project
        self.enterContext(
            patch.object(function_app, "convert_json_to_geojson")
        )
        self.artifact_processor = self.enterContext(
            patch.object(function_app, "ArtifactProcessor")
        ).return_value
        self.artifact_processor.get_download_url.return_value = (
            "https://acct/labels"
        )

    async def test_full_handler_saves_labels_before_fast_footprint_consumer(
        self,
    ) -> None:
        self.record["buildingFootprintsUrl"] = None

        def consume(message: str, **kwargs: Any) -> None:
            self.assertEqual(self.record["labelProjectId"], "label-project-1")
            self.assertEqual(self.record["labelsUrl"], "https://acct/labels")
            self.assertEqual(self.record["buildingFootprintsUrl"], SECRET_URL)
            request = FootprintTilesRequest.model_validate_json(message)
            if request.taskId:
                self.complete_task()
            footprint_tiles.process_tiles_request(request, config=self.config)

        self.queue.put_message.side_effect = consume
        await function_app.GetProcessImageLayerQueueMessage(
            func.QueueMessage(
                id="imagery-message-1",
                body=_layer(buildingFootprintsUrl=None).model_dump_json(),
            )
        )
        self.runner.add_task.assert_called_once()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.assertEqual(self.record["labelsUrl"], "https://acct/labels")

    async def test_label_failure_does_not_publish_or_clobber_footprint_state(
        self,
    ) -> None:
        self.record["footprintTilesStatus"] = STATUSES.IN_PROGRESS.value
        self.record["footprintTilesRequestId"] = "existing-request"
        self.labels.generate_task_files.side_effect = RuntimeError(
            "label generation failed"
        )
        await function_app.GetProcessImageLayerQueueMessage(
            func.QueueMessage(
                id="imagery-message-1", body=_layer().model_dump_json()
            )
        )
        self.queue.put_message.assert_not_called()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
        )
        self.assertEqual(
            self.record["footprintTilesRequestId"], "existing-request"
        )
        self.assertEqual(self.record["status"], STATUSES.FAILED.value)


class TestRequiredManifestQueueRetry(
    FootprintTestCase, unittest.IsolatedAsyncioTestCase
):
    async def test_actual_503_is_sanitized_and_redelivery_recovers(
        self,
    ) -> None:
        self.record = _layer(
            footprintTilesStatus=STATUSES.IN_PROGRESS.value,
            footprintTilesJob=_job(),
            footprintTilesRequestId="request-1",
        ).model_dump()
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        self.fetch.side_effect = fetch_url_text
        response = requests.Response()
        response.status_code = 503
        response.url = SECRET_URL
        response._content = json.dumps(
            {"pmtiles_url": "https://acct/tiles.pmtiles", "building_count": 42}
        ).encode()
        message = func.QueueMessage(
            id="poll-message",
            body=self.request(taskId="ftl-task").model_dump_json(),
        )
        with patch.object(function_app, "config", self.config), patch.object(
            function_app, "logger"
        ) as logger, patch("requests.get", return_value=response):
            try:
                await function_app.GetPrepareFootprintTilesQueueMessage(
                    message
                )
            except RuntimeError:
                self.assertNotIn("do-not-log", traceback.format_exc())
            else:
                self.fail("Transient retrieval failure must retry")
            self.assertEqual(
                self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
            )
            self.storage.save.assert_not_called()
            self.runner.cleanup_task.assert_not_called()
            self.assertNotIn("do-not-log", str(logger.mock_calls))

            response.status_code = 200
            await function_app.GetPrepareFootprintTilesQueueMessage(message)
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        self.runner.add_task.assert_not_called()
        self.runner.cleanup_task.assert_called_once()
