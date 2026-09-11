# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceExistsError
from hastegeo.core.artifact_storage.azure_blob_artifact_storage import (
    _INITIALIZED_CONTAINERS,
    AzureBlobArtifactStorage,
)


class TestAzureBlobArtifactStorageFetch(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = AzureBlobArtifactStorage.__new__(
            AzureBlobArtifactStorage
        )
        self.storage.partition_key = None
        self.storage.logger = Mock()
        self.storage.container_client = Mock()
        self.storage.container_client.url = "https://account.test/container"
        self.blob_client = (
            self.storage.container_client.get_blob_client.return_value
        )
        self.stream = self.blob_client.download_blob.return_value

    def _set_blob_names(self, *names: str) -> None:
        self.storage.container_client.list_blobs.return_value = [
            SimpleNamespace(name=name) for name in names
        ]

    def test_fetch_downloads_each_blob_atomically(self) -> None:
        self._set_blob_names("project/output.txt")
        self.stream.chunks.return_value = [b"hello", b" world"]

        with tempfile.TemporaryDirectory() as destination:
            result = self.storage.fetch_artifact(
                src_path="project", dst_path=destination
            )

            output_path = os.path.join(destination, "project", "output.txt")
            with open(output_path, "rb") as output:
                self.assertEqual(output.read(), b"hello world")
            self.assertEqual(result, destination)
            self.assertEqual(
                os.listdir(os.path.dirname(output_path)), ["output.txt"]
            )

    def test_fetch_rejects_parent_path_in_blob_name(self) -> None:
        self._set_blob_names("../outside.txt")

        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaisesRegex(ValueError, "Invalid artifact path"):
                self.storage.fetch_artifact(
                    src_path="project", dst_path=destination
                )
            self.assertFalse(
                os.path.exists(os.path.join(destination, "..", "outside.txt"))
            )

    def test_fetch_removes_partial_file_when_download_fails(self) -> None:
        self._set_blob_names("project/output.txt")

        def failing_chunks():
            yield b"partial"
            raise RuntimeError("download failed")

        self.stream.chunks.side_effect = failing_chunks
        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaisesRegex(RuntimeError, "download failed"):
                self.storage.fetch_artifact(
                    src_path="project", dst_path=destination
                )
            output_directory = os.path.join(destination, "project")
            self.assertEqual(os.listdir(output_directory), [])

    def test_fetch_requires_source_and_destination(self) -> None:
        with self.assertRaisesRegex(ValueError, "source"):
            self.storage.fetch_artifact(dst_path="destination")
        with self.assertRaisesRegex(ValueError, "destination"):
            self.storage.fetch_artifact(src_path="source")

    def test_fetch_rejects_invalid_worker_configuration(self) -> None:
        self._set_blob_names("project/output.txt")
        with patch.dict(os.environ, {"HASTE_ARTIFACT_DOWNLOAD_WORKERS": "0"}):
            with self.assertRaisesRegex(ValueError, "between 1 and 64"):
                self.storage.fetch_artifact(
                    src_path="project", dst_path="destination"
                )

    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.generate_container_sas",
        return_value="sas",
    )
    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.get_cached_user_delegation_key",
        return_value="delegation-key",
    )
    def test_download_url_fetches_delegation_key_lazily(
        self, delegation_key, _generate_sas
    ) -> None:
        self.storage.blob_service_client = Mock()
        self.storage.account_key = None
        self.storage.user_delegation_key = None
        self.storage.container_read_policy = "policy"
        self.storage.container_client.account_name = "account"
        self.storage.container_client.container_name = "artifacts"
        self.blob_client.url = "https://account.test/artifacts/file.txt"

        result = self.storage.get_download_url(identifier="file.txt")

        self.assertEqual(result, f"{self.blob_client.url}?sas")
        delegation_key.assert_called_once_with(
            self.storage.blob_service_client
        )

    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.generate_blob_sas",
        return_value="sas",
    )
    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.get_cached_user_delegation_key",
        return_value="delegation-key",
    )
    def test_scoped_url_reuses_delegation_key(
        self, delegation_key, _generate_sas
    ) -> None:
        self.storage.blob_service_client = Mock()
        self.storage.identity_blob_service_client = (
            self.storage.blob_service_client
        )
        self.storage.account_key = None
        self.storage.container_client.account_name = "account"
        self.storage.container_client.container_name = "artifacts"
        self.storage.container_client.url = "https://account.test/artifacts"
        self.blob_client.url = "https://account.test/artifacts/file.txt"
        self.blob_client.exists.return_value = True

        result = self.storage.get_scoped_download_url("file.txt")

        self.assertEqual(result, f"{self.blob_client.url}?sas")
        delegation_key.assert_called_once()

    def test_resolve_artifact_path_rejects_other_account(self) -> None:
        self.storage.container_client.url = "https://account.test/artifacts"

        with self.assertRaisesRegex(ValueError, "configured storage"):
            self.storage.resolve_artifact_path(
                "https://other.test/artifacts/file.txt"
            )

    def test_resolve_artifact_path_rejects_other_container(self) -> None:
        self.storage.container_client.url = "https://account.test/artifacts"

        with self.assertRaisesRegex(ValueError, "configured container"):
            self.storage.resolve_artifact_path(
                "https://account.test/other/file.txt"
            )


class TestAzureBlobArtifactStorageClientReuse(unittest.TestCase):
    def setUp(self) -> None:
        _INITIALIZED_CONTAINERS.clear()

    def tearDown(self) -> None:
        _INITIALIZED_CONTAINERS.clear()

    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.get_blob_service_client"
    )
    @patch.object(
        AzureBlobArtifactStorage,
        "_create_or_update_managed_access_policy",
    )
    def test_connection_string_uses_cached_client(
        self, create_policy, factory
    ):
        service = Mock(url="https://account.test")
        service.credential.account_key = "key"  # pragma: allowlist secret
        factory.return_value = service

        storage = AzureBlobArtifactStorage(
            account_url="",
            container="artifacts",
            connection_string="connection",
        )

        self.assertIs(storage.blob_service_client, service)
        factory.assert_called_once_with(connection_string="connection")
        create_policy.assert_called_once_with()

    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.get_blob_service_client"
    )
    def test_managed_identity_uses_cached_client(self, factory):
        service = Mock(url="https://account.test")
        factory.return_value = service

        storage = AzureBlobArtifactStorage(
            account_url="https://account.test",
            container="artifacts",
            connection_string=None,
            serves_read_sas=False,
        )

        self.assertIs(storage.blob_service_client, service)
        factory.assert_called_once_with(account_url="https://account.test")
        service.get_user_delegation_key.assert_not_called()

    @patch(
        "hastegeo.core.artifact_storage.azure_blob_artifact_storage.get_blob_service_client"
    )
    @patch.object(
        AzureBlobArtifactStorage,
        "_create_or_update_managed_access_policy",
    )
    def test_existing_container_is_reused(self, create_policy, factory):
        service = Mock(url="https://account.test")
        service.credential.account_key = "key"  # pragma: allowlist secret
        container = service.get_container_client.return_value
        container.create_container.side_effect = ResourceExistsError("exists")
        factory.return_value = service

        storage = AzureBlobArtifactStorage(
            account_url="",
            container="artifacts",
            connection_string="connection",
        )

        self.assertIs(storage.container_client, container)
        create_policy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
