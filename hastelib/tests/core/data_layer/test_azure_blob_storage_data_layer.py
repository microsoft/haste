# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceNotFoundError
from hastegeo.core.data_layer.azure_blob_storage_data_layer import (
    _INITIALIZED_CONTAINERS,
    AzureBlobStorageDataLayer,
)


class TestAzureBlobStorageDataLayerLoad(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = AzureBlobStorageDataLayer.__new__(
            AzureBlobStorageDataLayer
        )
        self.layer.partition_key = "partition"
        self.layer.container_client = Mock()
        self.blob_client = (
            self.layer.container_client.get_blob_client.return_value
        )
        self.downloader = self.blob_client.download_blob.return_value

    def test_load_deserializes_json(self) -> None:
        self.downloader.readall.return_value = b'{"value": 1}'

        result = self.layer.load("record", "model")

        self.assertEqual(result, {"value": 1})

    def test_load_tolerates_legacy_double_serialized_json(self) -> None:
        self.downloader.readall.return_value = json.dumps(
            json.dumps({"value": 1})
        ).encode()

        result = self.layer.load("record", "model")

        self.assertEqual(result, {"value": 1})

    def test_load_maps_only_resource_not_found_to_file_not_found(self) -> None:
        self.blob_client.download_blob.side_effect = ResourceNotFoundError(
            "missing"
        )

        with self.assertRaises(FileNotFoundError):
            self.layer.load("record", "model")

    def test_load_preserves_transport_errors(self) -> None:
        self.blob_client.download_blob.side_effect = RuntimeError(
            "transport unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "transport unavailable"):
            self.layer.load("record", "model")

    def test_load_preserves_json_errors(self) -> None:
        self.downloader.readall.return_value = b"{"

        with self.assertRaises(json.JSONDecodeError):
            self.layer.load("record", "model")

    def test_load_rejects_unsupported_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported data_format"):
            self.layer.load("record", "model", data_format="xml")

    def test_parallel_read_preserves_blob_order(self) -> None:
        self.layer._read_blob_content = Mock(
            side_effect=lambda blob, data_format: f"{blob}:{data_format}"
        )

        result = self.layer._read_blobs_parallel(["b", "a"], "json")

        self.assertEqual(result, ["b:json", "a:json"])

    def test_parallel_read_handles_empty_listing(self) -> None:
        self.layer._read_blob_content = Mock()

        result = self.layer._read_blobs_parallel([], "json")

        self.assertEqual(result, [])
        self.layer._read_blob_content.assert_not_called()

    def test_load_blob_names_drops_blobs_deleted_after_listing(self) -> None:
        self.layer._read_blob_content = Mock(
            side_effect=[{"value": 1}, ResourceNotFoundError("missing")]
        )

        result = self.layer._load_blob_names(["first", "missing"], "json")

        self.assertEqual(result, [{"value": 1}])

    def test_partition_scan_excludes_longer_type(self) -> None:
        self.layer.container_client.walk_blobs.return_value = [
            SimpleNamespace(name="partition/model_a.json"),
            SimpleNamespace(name="partition/model_catalog_index.json"),
        ]
        self.layer._read_blob_content = Mock(
            side_effect=lambda blob, _: blob.name
        )

        result = self.layer.load_all_from_partition("model")

        self.assertEqual(result, ["partition/model_a.json"])

    def test_load_all_does_not_cross_configured_partition(self) -> None:
        self.layer.container_client.walk_blobs.return_value = [
            SimpleNamespace(name="partition/model_a.json"),
            SimpleNamespace(name="other/model_b.json"),
        ]
        self.layer._read_blob_content = Mock(
            side_effect=lambda blob, _: blob.name
        )

        result = self.layer.load_all("model")

        self.assertEqual(result, ["partition/model_a.json"])

    def test_load_all_reads_matching_blobs_under_directory_markers(
        self,
    ) -> None:
        directory = SimpleNamespace(name="partition/")
        nested = SimpleNamespace(name="partition/model_a.json")
        self.layer.container_client.walk_blobs.side_effect = [
            [directory],
            [nested],
        ]
        self.layer._read_blob_content = Mock(
            side_effect=lambda blob, _: blob.name
        )

        result = self.layer.load_all("model")

        self.assertEqual(result, ["partition/model_a.json"])

    def test_load_page_skips_stats_and_deep_paths(self) -> None:
        blobs = [
            SimpleNamespace(
                name="partition/model_stats.json",
                metadata={},
                last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                name="partition/nested/model_a.json",
                metadata={},
                last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                name="partition/model_a.json",
                metadata={},
                last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ]
        pages = Mock()
        pages.by_page.return_value = [blobs]
        self.layer.container_client.list_blobs.return_value = pages
        self.layer._load_blob_names = Mock(return_value=[{"modelId": "a"}])

        records, count = self.layer.load_page("model", page=1, page_size=10)

        self.assertEqual(records, [{"modelId": "a"}])
        self.assertEqual(count, 1)
        self.layer._load_blob_names.assert_called_once_with(
            ["partition/model_a.json"], "json"
        )

    def test_identifier_listing_excludes_longer_type(self) -> None:
        self.layer.container_client.list_blob_names.return_value = [
            "partition/model_a.json",
            "partition/model_catalog_index.json",
        ]

        result = self.layer.list_identifiers("model")

        self.assertEqual(result, ["a"])

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.generate_container_sas",
        return_value="sas",
    )
    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_cached_user_delegation_key",
        return_value="delegation-key",
    )
    def test_remote_path_fetches_delegation_key_lazily(
        self, delegation_key, _generate_sas
    ) -> None:
        self.layer.blob_service_client = Mock()
        self.layer.account_key = None
        self.layer.user_delegation_key = None
        self.layer.container_read_policy = "policy"
        self.layer.container_client.account_name = "account"
        self.layer.container_client.container_name = "metadata"
        self.blob_client.url = "https://account.test/metadata/model_a.json"

        result = self.layer.get_file_remote_path(
            "a", "model", check_exists=False
        )

        self.assertEqual(result, f"{self.blob_client.url}?sas")
        delegation_key.assert_called_once_with(self.layer.blob_service_client)

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.generate_container_sas",
        return_value="sas",
    )
    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_cached_user_delegation_key"
    )
    def test_remote_path_with_account_key_skips_delegation_key(
        self, delegation_key, _generate_sas
    ) -> None:
        self.layer.blob_service_client = Mock()
        self.layer.account_key = "account-key"  # pragma: allowlist secret
        self.layer.user_delegation_key = None
        self.layer.container_read_policy = "policy"
        self.layer.container_client.account_name = "account"
        self.layer.container_client.container_name = "metadata"
        self.blob_client.url = "https://account.test/metadata/model_a.json"

        self.layer.get_file_remote_path("a", "model", check_exists=False)

        delegation_key.assert_not_called()

    def test_load_map_preserves_keys_and_missing_records(self) -> None:
        self.layer.load = Mock(
            side_effect=[{"modelId": "a"}, FileNotFoundError()]
        )

        result = self.layer.load_map(
            ["a", "a", "missing"], "model", max_workers=2
        )

        self.assertEqual(result, {"a": {"modelId": "a"}, "missing": None})
        self.assertEqual(self.layer.load.call_count, 2)


class TestAzureBlobStorageDataLayerClientReuse(unittest.TestCase):
    def setUp(self) -> None:
        _INITIALIZED_CONTAINERS.clear()

    def tearDown(self) -> None:
        _INITIALIZED_CONTAINERS.clear()

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_blob_service_client"
    )
    @patch.object(
        AzureBlobStorageDataLayer,
        "_create_or_update_managed_access_policy",
    )
    def test_connection_string_uses_cached_client(
        self, create_policy, factory
    ):
        service = Mock(url="https://account.test")
        service.credential.account_key = "key"  # pragma: allowlist secret
        factory.return_value = service

        layer = AzureBlobStorageDataLayer(
            account_url="",
            container="metadata",
            connection_string="connection",
        )

        self.assertIs(layer.blob_service_client, service)
        factory.assert_called_once_with(connection_string="connection")
        create_policy.assert_called_once_with()

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_blob_service_client"
    )
    @patch.object(
        AzureBlobStorageDataLayer,
        "_create_or_update_managed_access_policy",
    )
    def test_managed_identity_uses_cached_client(self, create_policy, factory):
        service = Mock(url="https://account.test")
        service.get_user_delegation_key.return_value = "delegation-key"
        factory.return_value = service

        layer = AzureBlobStorageDataLayer(
            account_url="https://account.test",
            container="metadata",
            connection_string=None,
        )

        self.assertIs(layer.blob_service_client, service)
        self.assertIsNone(layer.user_delegation_key)
        service.get_user_delegation_key.assert_not_called()
        factory.assert_called_once_with(account_url="https://account.test")
        create_policy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
