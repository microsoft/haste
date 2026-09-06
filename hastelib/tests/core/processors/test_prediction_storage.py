# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Event
from typing import Any, TextIO
from unittest.mock import MagicMock, patch

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from hastegeo.core.artifact_storage.azure_blob_artifact_storage import (
    AzureBlobArtifactStorage,
)
from hastegeo.core.data_layer.azure_blob_storage_data_layer import (
    AzureBlobStorageDataLayer,
)
from hastegeo.core.data_layer.unified import UnifiedDataLayer
from hastegeo.core.processors.prediction_generations import (
    PredictionGenerationRepository,
)
from hastegeo.core.utils.prediction_readiness import raw_predictions_readiness

from .test_prediction_results import MODEL_ID, PROJECT_ID, ResultsTestCase


class TestBlobArtifactReads(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = object.__new__(AzureBlobArtifactStorage)
        self.storage.container_client = MagicMock()
        self.blob = self.storage.container_client.get_blob_client.return_value
        self.blob.get_blob_properties.return_value.size = 2
        self.blob.download_blob.return_value.chunks.return_value = [b"{}"]

    def test_reads_exact_uploaded_blob_without_prefix_listing(self) -> None:
        result = self.storage.read_artifact_bytes(
            "project/task/attrs.json", 10
        )
        self.assertEqual(result, b"{}")
        self.storage.container_client.get_blob_client.assert_called_once_with(
            "project/task/attrs.json"
        )
        self.storage.container_client.list_blobs.assert_not_called()

    def test_404_and_transient_errors_do_not_become_empty_success(
        self,
    ) -> None:
        for error in (
            ResourceNotFoundError("missing"),
            HttpResponseError("503"),
        ):
            self.blob.get_blob_properties.side_effect = error
            with self.assertRaises(type(error)):
                self.storage.read_artifact_bytes("project/task/attrs.json", 10)

    def test_size_limit_applies_before_and_during_download(self) -> None:
        self.blob.get_blob_properties.return_value.size = 11
        with self.assertRaises(ValueError):
            self.storage.read_artifact_bytes("attrs.json", 10)
        self.blob.download_blob.assert_not_called()
        self.blob.get_blob_properties.return_value.size = 2
        self.blob.download_blob.return_value.chunks.return_value = [
            b"12345",
            b"678901",
        ]
        with self.assertRaises(ValueError):
            self.storage.read_artifact_bytes("attrs.json", 10)


class TestStrictBlobMetadata(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = object.__new__(AzureBlobStorageDataLayer)
        self.layer.partition_key = "project"
        self.layer.container_client = MagicMock()
        self.blob = self.layer.container_client.get_blob_client.return_value
        self.unified = object.__new__(UnifiedDataLayer)
        self.unified.data_layer = self.layer

    def test_legacy_load_stays_best_effort_but_strict_load_retries_503(
        self,
    ) -> None:
        self.blob.download_blob.side_effect = HttpResponseError("503")
        with self.assertRaises(FileNotFoundError):
            self.unified.load("42", "model")
        with self.assertRaises(HttpResponseError):
            self.unified.load_strict("42", "prediction_results")

    def test_strict_404_is_confirmed_absence(self) -> None:
        self.blob.download_blob.side_effect = ResourceNotFoundError("missing")
        with self.assertRaises(FileNotFoundError):
            self.unified.load_strict("42", "prediction_results")


class TestGenerationCoordination(ResultsTestCase):
    def test_cloud_writers_reuse_renewable_blob_leases(self) -> None:
        self.config.storage_type = "blob"
        lease = MagicMock()
        coordinator = MagicMock()
        coordinator.acquire.return_value = nullcontext(lease)
        self.repository.coordinator = coordinator
        with self.repository.lock(PROJECT_ID, MODEL_ID) as held:
            self.assertIs(held, lease)
        coordinator.acquire.assert_called_once_with(
            PROJECT_ID,
            f"prediction-results-{MODEL_ID}",
            wait_timeout_seconds=2,
        )

    def test_lease_loss_fails_closed_before_either_metadata_write(
        self,
    ) -> None:
        lease = MagicMock()
        lease.renew.side_effect = RuntimeError("lease lost")
        with patch.object(self.repository, "metadata") as metadata:
            with self.assertRaises(RuntimeError):
                self.repository.save_locked(self.model, lease)
        metadata.assert_not_called()

    def test_local_writers_in_separate_repositories_are_serialized(
        self,
    ) -> None:
        other = PredictionGenerationRepository(self.config)
        attempted = Event()
        acquired = Event()

        def acquire() -> None:
            attempted.set()
            with other.lock(PROJECT_ID, MODEL_ID):
                acquired.set()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.repository.lock(PROJECT_ID, MODEL_ID):
                future = executor.submit(acquire)
                self.assertTrue(attempted.wait(2))
                self.assertFalse(acquired.wait(0.05))
            future.result(timeout=2)
        self.assertTrue(acquired.is_set())

    def test_metadata_transport_failure_never_falls_back_to_old_model(
        self,
    ) -> None:
        self.save_predictions()
        original = self.repository.metadata

        def metadata(project_id: str, generations: bool = False) -> Any:
            if generations:
                unavailable = MagicMock()
                unavailable.load_strict.side_effect = HttpResponseError("503")
                return unavailable
            return original(project_id)

        with patch.object(self.repository, "metadata", side_effect=metadata):
            with self.assertRaises(HttpResponseError):
                self.current()

    def test_missing_generation_document_does_not_trust_ready_mirror(
        self,
    ) -> None:
        self.save_predictions()
        self.repository.metadata(PROJECT_ID, generations=True).delete(MODEL_ID)
        self.assertFalse(raw_predictions_readiness(self.current())["ready"])

    def test_failed_json_write_preserves_complete_previous_metadata(
        self,
    ) -> None:
        before = self.current().model_dump()

        def fail_dump(data: Any, stream: TextIO) -> None:
            stream.write("{")
            raise RuntimeError("write interrupted")

        with patch(
            "hastegeo.core.data_layer.local_file_system_data_layer.json.dump",
            side_effect=fail_dump,
        ):
            with self.assertRaises(RuntimeError):
                self.save_record("model", MODEL_ID, {"name": "New name"})
        self.assertEqual(self.current().model_dump(), before)
