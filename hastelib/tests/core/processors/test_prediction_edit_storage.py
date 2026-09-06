# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceExistsError
from hastegeo.core.artifact_storage.azure_blob_artifact_storage import (
    AzureBlobArtifactStorage,
)
from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)


class TestCreateOnlyPredictionStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(TemporaryDirectory())
        self.storage = UnifiedArtifactStorage(
            "local", directory=self.directory, partition_key="project"
        )

    def test_default_upload_behavior_is_unchanged(self) -> None:
        path = self.storage.store_artifact("attrs.json", data={"value": 1})
        self.storage.store_artifact("attrs.json", data={"value": 2})
        self.assertIn(b"2", self.storage.read_artifact_bytes(path, 100))

    def test_create_only_never_overwrites_existing_artifact(self) -> None:
        path = self.storage.store_artifact(
            "attrs.json", data={"value": 1}, overwrite=False
        )
        before = Path(path).read_bytes()
        with self.assertRaises(FileExistsError):
            self.storage.store_artifact(
                "attrs.json", data={"value": 2}, overwrite=False
            )
        self.assertEqual(Path(path).read_bytes(), before)

    def test_concurrent_create_only_writes_have_one_winner(self) -> None:
        def store(value: int) -> bool:
            try:
                self.storage.store_artifact(
                    "attrs.json", data={"value": value}, overwrite=False
                )
                return True
            except FileExistsError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            winners = list(executor.map(store, (1, 2)))
        self.assertEqual(sum(winners), 1)

    def test_interrupted_local_copy_does_not_expose_partial_file(self) -> None:
        source = Path(self.directory, "source.gpkg")
        source.write_bytes(b"artifact transport fixture")
        with patch(
            "hastegeo.core.artifact_storage.local_file_system_artifact_storage.shutil.copyfileobj",
            side_effect=OSError("interrupted"),
        ):
            with self.assertRaises(OSError):
                self.storage.store_artifact(
                    "output.gpkg", src_path=str(source), overwrite=False
                )
        self.assertFalse(self.storage.artifact_exists("output.gpkg"))

    def test_blob_create_only_uses_service_precondition_not_exists_check(
        self,
    ) -> None:
        storage = object.__new__(AzureBlobArtifactStorage)
        storage.partition_key = "project"
        storage.logger = MagicMock()
        storage.container_client = MagicMock()
        blob = storage.container_client.get_blob_client.return_value
        blob.upload_blob.side_effect = ResourceExistsError("already exists")
        source = Path(self.directory, "source.gpkg")
        source.write_bytes(b"artifact transport fixture")
        with self.assertRaises(ResourceExistsError):
            storage.store_artifact(
                "v1.gpkg", src_path=str(source), overwrite=False
            )
        self.assertIs(blob.upload_blob.call_args.kwargs["overwrite"], False)
        blob.exists.assert_not_called()
