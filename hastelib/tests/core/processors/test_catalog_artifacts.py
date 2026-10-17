# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model
from hastegeo.core.processors.catalog_artifacts import CatalogArtifactProcessor
from hastegeo.core.utils.catalog_lock import catalog_task_id
from hastegeo.core.utils.metadata import MetadataUtils


class TestCatalogArtifacts(unittest.TestCase):
    def setUp(self) -> None:
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.config = Config()
        self.config.storage_type = self.config.artifact_storage_type = "local"
        self.config.storage_config = {"directory": str(directory / "metadata")}
        self.config.artifact_storage_config = {
            "directory": str(directory / "artifacts")
        }
        self.processor = CatalogArtifactProcessor(self.config)
        self.model = Model(
            projectId="project",
            modelId="1234",
            imageLayerId="layer",
            name="run-1234",
            inferenceRequestId="request",
            inferenceOutputPath="hash/inf-catalog-request",
            inferenceStatus="Processed",
            modelType="pretrained",
        )
        self.runner = self.enterContext(
            patch("hastegeo.core.processors.catalog_artifacts.UnifiedRunner")
        ).return_value
        self.runner.get_task_status.return_value = "InProgress"
        self.poll = Mock()

    def test_inference_only_archive_recovers_without_training_resources(
        self,
    ) -> None:
        queued = self.processor.process(self.model, self.poll)
        submitted = self.runner.add_task.call_args.kwargs
        self.assertTrue(submitted["idempotent"])
        self.assertEqual(
            set(submitted["resource_files_for_upload"]), {"inference"}
        )
        self.assertIsNone(queued.trainingZipUrl)
        self.assertEqual(queued.zipStatus, "InProgress")
        prefix = f"{MetadataUtils.hash_string(self.model.projectId)}/{catalog_task_id(self.model.projectId, self.model.inferenceRequestId, 'zip')}"
        self.processor.storage.store_artifact(
            "inference_artifacts_run-1234.zip",
            data="zip-fixture",
            namespace=prefix,
        )
        self.runner.get_task_status.return_value = "Processed"
        complete = self.processor.process(self.model, self.poll)
        self.assertEqual(complete.zipStatus, "Processed")
        self.assertTrue(complete.inferenceZipUrl)
        self.assertIsNone(complete.trainingZipUrl)
        self.assertEqual(
            self.runner.add_task.call_args.kwargs["task_id"],
            submitted["task_id"],
        )
        self.processor.process(self.model, self.poll)
        self.assertEqual(self.runner.add_task.call_count, 2)
        self.runner.cleanup_task.assert_called_once()

    def test_missing_archive_fails_without_changing_inference_success(
        self,
    ) -> None:
        self.runner.get_task_status.return_value = "Processed"
        failed = self.processor.process(self.model, self.poll)
        self.assertEqual(failed.zipStatus, "Failed")
        self.assertIsNone(failed.inferenceZipUrl)
        self.assertEqual(self.model.inferenceStatus, "Processed")

    def test_accepted_archive_submission_recovers_after_transport_failure(
        self,
    ) -> None:
        self.runner.add_task.side_effect = TimeoutError("offline")
        first = self.processor.process(self.model, self.poll)
        self.assertEqual(first.zipFailures, 1)
        self.runner.add_task.side_effect = None
        retry = self.processor.process(self.model, self.poll)
        self.assertEqual(first.currentZipJobUid, retry.currentZipJobUid)
        self.assertEqual(retry.zipFailures, 0)

    def test_wrapped_archive_read_failure_does_not_create_fresh_work(
        self,
    ) -> None:
        first = self.processor.process(self.model, self.poll)
        error = FileNotFoundError("wrapped timeout")
        error.__cause__ = TimeoutError("offline")
        with patch(
            "hastegeo.core.processors.metadata.MetadataProcessor.load",
            side_effect=error,
        ):
            with self.assertRaises(RuntimeError):
                self.processor.process(self.model, self.poll)
        self.assertEqual(self.runner.add_task.call_count, 1)
        self.assertEqual(first.zipStatus, "InProgress")
