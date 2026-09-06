# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Footprint requests use authoritative metadata, with no live services."""

import json
import unittest
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import requests
from hastegeo.core.config import Config
from hastegeo.core.models.footprint_tiles import (
    FootprintTilesRequest,
    parse_tiles_request,
)
from hastegeo.core.models.projects import ImageLayer, TrainingJob
from hastegeo.core.processors import footprint_tiles
from hastegeo.core.utils.blob import fetch_url_text
from pydantic import ValidationError

STATUSES = Config.get_status_types()
SECRET_URL = (
    "https://acct/footprints.gpkg?sig=do-not-log"  # pragma: allowlist secret
)


def _layer(**overrides: Any) -> ImageLayer:
    data = {
        "projectId": "proj-1",
        "imageLayerId": "11111111-1111-1111-1111-111111111111",
        "buildingFootprintsUrl": SECRET_URL,
    }
    data.update(overrides)
    return ImageLayer(**data)


def _job() -> TrainingJob:
    return TrainingJob(
        jobId="job-1",
        taskId="ftl-task",
        projectId="proj-1",
        status=STATUSES.IN_PROGRESS.value,
    )


class FootprintTestCase(unittest.TestCase):
    """Exercise the real metadata merge against an isolated memory store."""

    def setUp(self) -> None:
        self.config = Config()
        self.record = _layer().model_dump()
        self.storage = MagicMock()
        self.storage.load.side_effect = lambda **kwargs: deepcopy(self.record)

        def save(**kwargs: Any) -> None:
            self.record = deepcopy(kwargs["data"])

        self.storage.save.side_effect = save
        self.enterContext(
            patch(
                "hastegeo.core.processors.metadata.UnifiedDataLayer",
                return_value=self.storage,
            )
        )
        self.artifacts = self.enterContext(
            patch.object(footprint_tiles, "UnifiedDataLayer")
        ).return_value
        self.artifacts.get_file_remote_path.return_value = (
            "https://acct/uploaded?sig=do-not-log"
        )
        self.runner = self.enterContext(
            patch.object(footprint_tiles, "UnifiedRunner")
        ).return_value
        self.runner.add_task.return_value = ("job-1", "ftl-task")
        self.runner.get_task_status.return_value = STATUSES.IN_PROGRESS.value
        self.runner.get_filecontent_from_task.return_value = None
        self.queue = self.enterContext(
            patch.object(footprint_tiles, "AzureQueueHandler")
        ).return_value
        self.fetch = self.enterContext(
            patch.object(footprint_tiles, "fetch_url_text", return_value=None)
        )
        self.create_job_config = (
            footprint_tiles.FootprintTilesPreprocessor._create_job_config
        )
        self.job_config = self.enterContext(
            patch.object(
                footprint_tiles.FootprintTilesPreprocessor,
                "_create_job_config",
                return_value={
                    "config": {"file_path": "inputs/config.json"},
                },
            )
        )

    def request(self, **overrides: Any) -> FootprintTilesRequest:
        data = {
            "projectId": self.record["projectId"],
            "imageLayerId": self.record["imageLayerId"],
            "requestId": "request-1",
        }
        data.update(overrides)
        return FootprintTilesRequest.model_validate(data)

    def run_request(self, **overrides: Any) -> ImageLayer | None:
        return footprint_tiles.process_tiles_request(
            self.request(**overrides), config=self.config
        )

    def complete_task(self) -> None:
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        self.runner.get_filecontent_from_task.side_effect = lambda **kwargs: (
            json.dumps(
                {
                    "pmtiles_url": "https://acct/tiles.pmtiles",
                    "building_count": 42,
                }
            )
            if kwargs["filename"] == footprint_tiles.MANIFEST_FILENAME
            else None
        )


class TestLayerNeedsFootprintTiles(unittest.TestCase):
    def test_needs_tiles_once_footprints_are_cached(self) -> None:
        self.assertTrue(footprint_tiles.layer_needs_footprint_tiles(_layer()))

    def test_no_footprints_means_nothing_to_tile(self) -> None:
        self.assertFalse(
            footprint_tiles.layer_needs_footprint_tiles(
                _layer(buildingFootprintsUrl=None)
            )
        )

    def test_an_existing_archive_is_not_rebuilt(self) -> None:
        self.assertFalse(
            footprint_tiles.layer_needs_footprint_tiles(
                _layer(footprintPmtilesUrl="https://acct/footprints.pmtiles")
            )
        )

    def test_archive_is_named_for_the_layer_not_a_model(self) -> None:
        self.assertEqual(
            footprint_tiles.pmtiles_artifact_name("layer-7"),
            "footprints_layer-7.pmtiles",
        )


class TestQueueMessage(unittest.TestCase):
    def test_message_carries_identifiers_only(self) -> None:
        message = footprint_tiles.build_tiles_message(
            project_id="p", image_layer_id="l", request_id="request-1"
        )
        self.assertEqual(
            message,
            {
                "projectId": "p",
                "imageLayerId": "l",
                "requestId": "request-1",
                "force": False,
            },
        )

    def test_legacy_urls_are_discarded_and_message_identity_is_used(
        self,
    ) -> None:
        request = parse_tiles_request(
            json.dumps(
                {
                    "projectId": "p",
                    "imageLayerId": "l",
                    "sourceFootprintsUrl": SECRET_URL,
                    "buildingFootprintsUrl": SECRET_URL,
                    "force": True,
                }
            ).encode(),
            "azure-message-1",
        )
        self.assertEqual(request.requestId, "azure-message-1")
        self.assertTrue(request.force)
        self.assertNotIn("do-not-log", request.model_dump_json())

    def test_rejects_invalid_schema_without_bool_coercion(self) -> None:
        for payload in (
            [],
            {},
            {"projectId": "p"},
            {"projectId": 123, "imageLayerId": "l"},
            {"projectId": "p", "imageLayerId": " "},
            {"projectId": SECRET_URL, "imageLayerId": "l"},
            {"projectId": "p", "imageLayerId": "l", "force": "false"},
            {"projectId": "p", "imageLayerId": "l", "force": 1},
            {"projectId": "p", "imageLayerId": "l", "unexpected": SECRET_URL},
            {
                "projectId": "p",
                "imageLayerId": "l",
                "taskId": "t",
                "force": True,
            },
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    parse_tiles_request(
                        json.dumps(payload).encode(), "message-1"
                    )


class TestRequestPreparation(FootprintTestCase):
    def test_persists_pending_before_publishing_identifiers(self) -> None:
        layer = _layer()

        def consume(message: str, **kwargs: Any) -> None:
            self.assertEqual(
                self.record["footprintTilesStatus"], STATUSES.PENDING.value
            )
            self.assertEqual(self.record["buildingFootprintsUrl"], SECRET_URL)
            request = FootprintTilesRequest.model_validate_json(message)
            self.assertEqual(
                request.requestId, self.record["footprintTilesRequestId"]
            )
            self.assertNotIn("do-not-log", message)

        self.queue.put_message.side_effect = consume
        result = footprint_tiles.request_preparation(layer, config=self.config)
        self.assertTrue(result["queued"])
        self.queue.put_message.assert_called_once()

    def test_is_a_no_op_when_the_archive_exists(self) -> None:
        layer = _layer(footprintPmtilesUrl="https://acct/f.pmtiles")
        result = footprint_tiles.request_preparation(layer, config=self.config)
        self.queue.put_message.assert_not_called()
        self.assertFalse(result["queued"])
        self.assertTrue(result["tilesReady"])
        self.assertEqual(layer.footprintTilesStatus, STATUSES.COMPLETED.value)

    def test_force_never_resets_an_in_flight_request(self) -> None:
        for status in (STATUSES.PENDING.value, STATUSES.IN_PROGRESS.value):
            for force in (False, True):
                layer = _layer(
                    footprintTilesStatus=status, footprintTilesJob=_job()
                )
                before = layer.model_dump()
                result = footprint_tiles.request_preparation(
                    layer, force=force, config=self.config
                )
                self.assertFalse(result["queued"])
                self.assertEqual(layer.model_dump(), before)
        self.queue.put_message.assert_not_called()
        self.storage.save.assert_not_called()

    def test_force_rebuilds_an_existing_archive(self) -> None:
        layer = _layer(footprintPmtilesUrl="https://acct/f.pmtiles")
        result = footprint_tiles.request_preparation(
            layer, force=True, config=self.config
        )
        self.assertTrue(result["queued"])
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.PENDING.value
        )

    def test_without_footprints_there_is_nothing_to_tile(self) -> None:
        with self.assertRaises(ValueError):
            footprint_tiles.request_preparation(
                _layer(buildingFootprintsUrl=None), config=self.config
            )
        self.queue.put_message.assert_not_called()

    def test_send_failure_is_visible_and_can_be_recovered(self) -> None:
        self.queue.put_message.side_effect = RuntimeError(SECRET_URL)
        with self.assertRaises(RuntimeError):
            footprint_tiles.request_preparation(_layer(), config=self.config)
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )
        self.assertIn(
            "again to retry", self.record["footprintTilesStatusMessage"]
        )
        self.assertNotIn(
            "do-not-log", self.record["footprintTilesStatusMessage"]
        )
        self.queue.put_message.side_effect = None
        self.run_request(requestId="recovery")
        self.runner.add_task.assert_called_once()

    def test_ambiguous_send_failure_does_not_overwrite_fast_consumer(
        self,
    ) -> None:
        def consume_then_fail(message: str, **kwargs: Any) -> None:
            self.queue.put_message.side_effect = None
            footprint_tiles.process_tiles_request(
                FootprintTilesRequest.model_validate_json(message),
                config=self.config,
            )
            raise RuntimeError(SECRET_URL)

        self.queue.put_message.side_effect = consume_then_fail
        with self.assertRaises(RuntimeError):
            footprint_tiles.request_preparation(_layer(), config=self.config)
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
        )
        self.assertEqual(
            self.record["footprintTilesJob"]["taskId"], "ftl-task"
        )


class TestProcessTilesRequest(FootprintTestCase):
    def test_fresh_and_failed_requests_initialize_from_metadata(self) -> None:
        for status in (None, STATUSES.FAILED.value):
            with self.subTest(status=status):
                self.record = _layer(
                    footprintTilesStatus=status,
                    footprintTilesJob=_job(),
                ).model_dump()
                output = self.run_request()
                self.assertEqual(output.buildingFootprintsUrl, SECRET_URL)
                self.assertEqual(
                    output.footprintTilesStatus, STATUSES.IN_PROGRESS.value
                )
                self.assertEqual(output.footprintTilesRequestId, "request-1")
        self.assertEqual(self.runner.add_task.call_count, 2)

    def test_pending_and_in_progress_duplicates_only_submit_once(self) -> None:
        self.record["footprintTilesStatus"] = STATUSES.PENDING.value
        self.run_request()
        first_job = deepcopy(self.record["footprintTilesJob"])
        for force in (False, True):
            self.run_request(force=force)
            self.assertEqual(self.record["footprintTilesJob"], first_job)
        self.runner.add_task.assert_called_once()
        self.assertEqual(self.runner.get_task_status.call_count, 2)

    def test_ready_layer_is_a_no_op(self) -> None:
        self.record["footprintPmtilesUrl"] = "https://acct/ready.pmtiles"
        self.run_request()
        self.runner.add_task.assert_not_called()
        self.queue.put_message.assert_not_called()
        self.storage.save.assert_not_called()

    def test_force_recovers_a_failed_rebuild_with_an_old_archive(self) -> None:
        self.record = _layer(
            footprintPmtilesUrl="https://acct/old.pmtiles",
            footprintTilesStatus=STATUSES.FAILED.value,
            footprintTilesJob=_job(),
            footprintTilesRequestId="failed-request",
        ).model_dump()
        self.run_request(force=True)
        self.runner.add_task.assert_called_once()
        self.assertEqual(self.record["footprintTilesRequestId"], "request-1")
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
        )

    def test_force_rebuilds_once_even_after_completion_and_redelivery(
        self,
    ) -> None:
        self.record["footprintPmtilesUrl"] = "https://acct/old.pmtiles"
        self.record["footprintTilesStatus"] = STATUSES.COMPLETED.value
        self.run_request(force=True)
        self.complete_task()
        self.run_request(force=True)
        self.run_request(force=True)
        self.runner.add_task.assert_called_once()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        # Polls do not repeat force, even for a forced rebuild.
        message = json.loads(self.queue.put_message.call_args.args[0])
        self.assertEqual(
            set(message),
            {"projectId", "imageLayerId", "requestId", "taskId", "force"},
        )
        self.assertFalse(message["force"])
        self.assertEqual(message["taskId"], "ftl-task")
        self.assertNotIn("do-not-log", json.dumps(message))

    def test_polls_never_restart_terminal_or_superseded_jobs(self) -> None:
        for status in (STATUSES.COMPLETED.value, STATUSES.FAILED.value):
            self.record = _layer(
                footprintTilesStatus=status, footprintTilesJob=_job()
            ).model_dump()
            self.run_request(taskId="ftl-task")
        self.record["footprintTilesStatus"] = STATUSES.IN_PROGRESS.value
        self.run_request(taskId="older-task")
        self.runner.add_task.assert_not_called()
        self.runner.get_task_status.assert_not_called()
        self.queue.put_message.assert_not_called()
        self.storage.save.assert_not_called()

    def test_failed_request_redelivery_does_not_rebuild_forever(self) -> None:
        self.run_request()
        self.runner.get_task_status.return_value = STATUSES.FAILED.value
        self.run_request()
        self.run_request()
        self.runner.add_task.assert_called_once()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )

    def test_batch_pending_status_keeps_existing_task_in_progress(
        self,
    ) -> None:
        self.record = _layer(
            footprintTilesStatus=STATUSES.PENDING.value,
            footprintTilesJob=_job(),
        ).model_dump()
        self.runner.get_task_status.return_value = STATUSES.PENDING.value
        self.run_request()
        self.run_request()
        self.runner.add_task.assert_not_called()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
        )

    def test_missing_active_job_is_a_visible_failure(self) -> None:
        self.record["footprintTilesStatus"] = STATUSES.IN_PROGRESS.value
        self.run_request()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )
        self.assertIn("missing", self.record["footprintTilesStatusMessage"])
        self.queue.put_message.assert_not_called()

    def test_legacy_pending_force_is_idempotent_after_completion(self) -> None:
        self.record["footprintTilesStatus"] = STATUSES.PENDING.value
        self.run_request(force=True)
        self.complete_task()
        self.run_request(force=True)
        self.run_request(force=True)
        self.runner.add_task.assert_called_once()
        self.assertEqual(self.record["footprintTilesRequestId"], "request-1")

    def test_no_cached_footprints_is_an_invalid_request(self) -> None:
        self.record["buildingFootprintsUrl"] = None
        with self.assertRaises(ValueError):
            self.run_request()
        self.runner.add_task.assert_not_called()
        self.storage.save.assert_not_called()

    def test_deleted_layer_is_a_no_op(self) -> None:
        request = self.request()
        for missing in (None, FileNotFoundError()):
            self.storage.load.side_effect = missing
            self.storage.load.return_value = None
            self.assertIsNone(
                footprint_tiles.process_tiles_request(
                    request, config=self.config
                )
            )
        self.runner.add_task.assert_not_called()

    def test_fast_poll_cannot_have_completion_clobbered_by_submitter(
        self,
    ) -> None:
        def consume(message: str) -> None:
            self.assertEqual(
                self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
            )
            self.assertEqual(
                self.record["footprintTilesJob"]["taskId"], "ftl-task"
            )
            self.complete_task()
            footprint_tiles.process_tiles_request(
                FootprintTilesRequest.model_validate_json(message),
                config=self.config,
            )

        self.queue.put_message.side_effect = consume
        self.run_request()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.runner.add_task.assert_called_once()

    def test_poll_send_failure_retries_without_resubmitting_task(self) -> None:
        self.queue.put_message.side_effect = RuntimeError(SECRET_URL)
        with self.assertRaises(RuntimeError):
            self.run_request()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.IN_PROGRESS.value
        )
        self.queue.put_message.side_effect = None
        self.run_request()
        self.runner.add_task.assert_called_once()
        self.runner.get_task_status.assert_called_once()

    def test_unexpected_submission_failure_propagates(self) -> None:
        self.runner.add_task.side_effect = RuntimeError(SECRET_URL)
        with self.assertRaises(RuntimeError):
            self.run_request()
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.PENDING.value
        )
        self.queue.put_message.assert_not_called()

    def test_failed_metadata_save_does_not_publish_poll(self) -> None:
        self.record["footprintTilesStatus"] = STATUSES.PENDING.value
        self.record["footprintTilesRequestId"] = "request-1"
        self.storage.save.side_effect = RuntimeError(SECRET_URL)
        with self.assertRaises(RuntimeError):
            self.run_request()
        self.runner.add_task.assert_called_once()
        self.queue.put_message.assert_not_called()

    def test_job_inputs_use_authoritative_url_not_legacy_message(self) -> None:
        prefix = footprint_tiles.MetadataUtils.hash_string("proj-1")
        self.record[
            "buildingFootprintsUrl"
        ] = f"https://acct/{prefix}/cached.gpkg?sig=authoritative"
        self.artifacts.get_file_remote_path.return_value = (
            f"https://acct/{prefix}/config.json?sig=config"
        )
        request = parse_tiles_request(
            json.dumps(
                {
                    "projectId": self.record["projectId"],
                    "imageLayerId": self.record["imageLayerId"],
                    "sourceFootprintsUrl": SECRET_URL,
                }
            ).encode(),
            "message-1",
        )
        with patch.object(
            footprint_tiles.FootprintTilesPreprocessor,
            "_create_job_config",
            self.create_job_config,
        ):
            footprint_tiles.process_tiles_request(request, config=self.config)
        inputs = self.runner.add_task.call_args.kwargs[
            "resource_files_for_upload"
        ]
        self.assertEqual(
            inputs["footprints"]["http_url"],
            f"https://acct/{prefix}/cached.gpkg",
        )
        self.assertNotIn("do-not-log", str(inputs))

    def test_footprint_updates_do_not_overwrite_imagery_fields(self) -> None:
        def label_work(**kwargs: Any) -> tuple[str, str]:
            self.record["labelsUrl"] = "https://acct/new-labels"
            return "job-1", "ftl-task"

        self.runner.add_task.side_effect = label_work
        self.run_request()
        self.assertEqual(self.record["labelsUrl"], "https://acct/new-labels")


class TestTaskOutputFallback(FootprintTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.layer = _layer(
            footprintTilesStatus=STATUSES.IN_PROGRESS.value,
            footprintTilesJob=_job(),
        )
        self.processor = footprint_tiles.FootprintTilesPreprocessor(
            self.layer, config=self.config
        )

    def test_node_copy_is_preferred(self) -> None:
        self.runner.get_filecontent_from_task.return_value = "node-content"
        self.assertEqual(
            self.processor._read_task_output(
                footprint_tiles.MANIFEST_FILENAME
            ),
            "node-content",
        )
        self.fetch.assert_not_called()

    def test_blob_manifest_completes_job_after_node_deallocation(self) -> None:
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        self.fetch.side_effect = [
            json.dumps(
                {"pmtiles_filename": "tiles.pmtiles", "building_count": 42}
            ),
            None,
        ]
        output = self.processor.process()
        self.assertEqual(output.footprintTilesStatus, STATUSES.COMPLETED.value)
        self.assertIn("42 buildings", output.footprintTilesStatusMessage)
        self.artifacts.get_file_remote_path.assert_any_call(
            identifier=footprint_tiles.MANIFEST_FILENAME,
            extra_partition_keys="ftl-task",
            data_format="json",
        )
        self.runner.cleanup_task.assert_called_once()

    def test_missing_manifest_in_both_places_fails_visibly(self) -> None:
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        output = self.processor.process()
        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        self.assertIn("manifest", output.footprintTilesStatusMessage)

    def test_friendly_logs_also_use_blob_fallback(self) -> None:
        self.fetch.return_value = "2026-09-06T18:00:00|Prepared buildings\n"
        self.assertEqual(
            self.processor._get_friendly_logs(),
            [("2026-09-06T18:00:00", "Prepared buildings")],
        )

    def test_fallback_error_is_best_effort_and_sanitized(self) -> None:
        self.artifacts.get_file_remote_path.side_effect = RuntimeError(
            SECRET_URL
        )
        self.processor.logger = MagicMock()
        self.assertEqual(self.processor._get_friendly_logs(), [])
        self.processor.logger.warning.assert_called_once()
        self.assertNotIn("do-not-log", str(self.processor.logger.mock_calls))

    def test_unrelated_node_exception_propagates_for_retry(self) -> None:
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        self.runner.get_filecontent_from_task.side_effect = RuntimeError(
            SECRET_URL
        )
        with self.assertRaises(RuntimeError):
            self.processor.process()
        self.assertEqual(
            self.layer.footprintTilesJob.status, STATUSES.IN_PROGRESS.value
        )
        self.assertIsNone(self.layer.footprintTilesJob.completedDate)
        self.runner.cleanup_task.assert_not_called()


class TestRequiredManifestRetries(FootprintTestCase):
    """Exercise actual HTTP status handling, not a mocked text fetcher."""

    def setUp(self) -> None:
        super().setUp()
        self.active_layer = _layer(
            footprintTilesStatus=STATUSES.IN_PROGRESS.value,
            footprintTilesJob=_job(),
            footprintTilesRequestId="request-1",
        )
        self.record = self.active_layer.model_dump()
        self.runner.get_task_status.return_value = STATUSES.COMPLETED.value
        self.fetch.side_effect = fetch_url_text
        self.http = self.enterContext(patch("requests.get"))
        self.http.return_value = self.response(200)
        self.logger = self.enterContext(
            patch.object(footprint_tiles.Logger, "get_logger")
        ).return_value

    def response(self, status: int) -> requests.Response:
        response = requests.Response()
        response.status_code = status
        response.url = SECRET_URL
        response._content = json.dumps(
            {"pmtiles_url": "https://acct/tiles.pmtiles", "building_count": 42}
        ).encode()
        return response

    def assert_retryable_read_failure(self) -> None:
        before = deepcopy(self.record)
        with self.assertRaises(RuntimeError) as raised:
            self.run_request(taskId="ftl-task")
        self.assertNotIn("do-not-log", str(raised.exception))
        self.assertEqual(self.record, before)
        self.storage.save.assert_not_called()
        self.runner.cleanup_task.assert_not_called()
        self.queue.put_message.assert_not_called()
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    def assert_recovered(self) -> None:
        self.run_request(taskId="ftl-task")
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.COMPLETED.value
        )
        self.assertEqual(
            self.record["footprintTilesJob"]["status"],
            STATUSES.COMPLETED.value,
        )
        self.assertEqual(
            self.record["footprintPmtilesUrl"], "https://acct/tiles.pmtiles"
        )
        self.runner.add_task.assert_not_called()
        self.runner.cleanup_task.assert_called_once()
        self.assertNotIn("do-not-log", str(self.logger.mock_calls))

    def test_required_manifest_503_retries_then_recovers(self) -> None:
        self.http.return_value = self.response(503)
        self.assert_retryable_read_failure()
        self.http.return_value = self.response(200)
        self.assert_recovered()

    def test_required_manifest_timeout_retries_then_recovers(self) -> None:
        self.http.side_effect = requests.Timeout(SECRET_URL)
        self.assert_retryable_read_failure()
        self.http.side_effect = None
        self.assert_recovered()

    def test_required_manifest_resolution_failures_retry_then_recover(
        self,
    ) -> None:
        for error in (
            RuntimeError(SECRET_URL),
            ValueError(SECRET_URL),
            FileNotFoundError(SECRET_URL),
        ):
            with self.subTest(error=type(error).__name__):
                self.record = self.active_layer.model_dump()
                self.storage.save.reset_mock()
                self.runner.cleanup_task.reset_mock()
                self.artifacts.get_file_remote_path.side_effect = error
                self.assert_retryable_read_failure()
                self.artifacts.get_file_remote_path.side_effect = None
                self.assert_recovered()

    def test_required_manifest_404_is_a_visible_terminal_failure(self) -> None:
        self.http.return_value = self.response(404)
        self.run_request(taskId="ftl-task")
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )
        self.assertIn("manifest", self.record["footprintTilesStatusMessage"])
        self.runner.cleanup_task.assert_called_once()
        self.queue.put_message.assert_not_called()

    def test_archive_url_resolution_failure_retries_then_recovers(
        self,
    ) -> None:
        self.http.return_value._content = json.dumps(
            {"pmtiles_filename": "tiles.pmtiles", "building_count": 42}
        ).encode()
        self.artifacts.get_file_remote_path.side_effect = [
            SECRET_URL,
            ValueError(SECRET_URL),
        ]
        self.assert_retryable_read_failure()
        self.artifacts.get_file_remote_path.side_effect = None
        self.artifacts.get_file_remote_path.return_value = (
            "https://acct/tiles.pmtiles"
        )
        self.assert_recovered()

    def test_required_manifest_without_url_is_a_visible_failure(self) -> None:
        self.artifacts.get_file_remote_path.return_value = None
        self.run_request(taskId="ftl-task")
        self.assertEqual(
            self.record["footprintTilesStatus"], STATUSES.FAILED.value
        )
        self.http.assert_not_called()
        self.runner.cleanup_task.assert_called_once()

    def test_optional_friendly_http_failures_do_not_fail_completed_job(
        self,
    ) -> None:
        for error in (self.response(503), requests.Timeout(SECRET_URL)):
            self.record = self.active_layer.model_dump()
            self.runner.cleanup_task.reset_mock()
            self.http.side_effect = [self.response(200), error]
            self.assert_recovered()

    def test_optional_friendly_resolution_failure_is_best_effort(self) -> None:
        self.artifacts.get_file_remote_path.side_effect = [
            SECRET_URL,
            ValueError(SECRET_URL),
        ]
        self.assert_recovered()
        self.logger.warning.assert_called_once()

    def test_optional_friendly_node_failure_is_best_effort(self) -> None:
        self.runner.get_filecontent_from_task.side_effect = [
            None,
            RuntimeError(SECRET_URL),
        ]
        self.assert_recovered()
        self.logger.warning.assert_called_once()
