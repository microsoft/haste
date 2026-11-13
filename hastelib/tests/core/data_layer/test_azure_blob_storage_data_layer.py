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
    def test_unsigned_path_does_not_request_a_delegation_key(self) -> None:
        self.blob_client.url = "https://account.test/data/file.tif"
        self.assertEqual(
            self.layer.get_file_remote_path("file", include_sas=False),
            self.blob_client.url,
        )

    def test_stage_bytes_without_local_disk(self) -> None:
        self.blob_client.url = "https://account.test/data/file.tif"
        result = self.layer.save_chunk(
            "file", "raw", data=b"chunk", chunk_id=0
        )
        self.assertEqual(result, self.blob_client.url)
        self.blob_client.stage_block.assert_called_once_with(
            block_id=self.layer._block_id(0), data=b"chunk", length=5
        )

    def test_remote_state_reports_missing_blocks_and_total_size(self) -> None:
        self.blob_client.get_blob_properties.side_effect = (
            ResourceNotFoundError()
        )
        self.blob_client.get_block_list.return_value = (
            [],
            [SimpleNamespace(id=self.layer._block_id(1), size=7)],
        )
        state = self.layer.get_chunk_upload_state(
            "file", "raw", total_chunks=2
        )
        self.assertEqual(state["missing"], [0])
        self.assertEqual(state["total_size"], 7)
        self.assertFalse(state["complete"])

    def test_finalize_refuses_missing_blocks(self) -> None:
        self.layer.get_chunk_upload_state = Mock(
            return_value={"complete": False, "missing": [0], "unexpected": []}
        )
        with self.assertRaises(ValueError):
            self.layer.finalize_save("file", "raw", total_chunks=2)
        self.blob_client.commit_block_list.assert_not_called()

    def test_completed_retry_does_not_commit_again(self) -> None:
        self.layer.get_chunk_upload_state = Mock(
            return_value={
                "complete": True,
                "output_url": "https://account/file",
            }
        )
        self.assertEqual(
            self.layer.finalize_save("file", "raw", total_chunks=2),
            "https://account/file",
        )
        self.blob_client.commit_block_list.assert_not_called()

    def test_finalize_commits_all_blocks_in_index_order_with_durable_state(
        self,
    ) -> None:
        self.blob_client.url = "https://account.test/data/file.tif"
        self.blob_client.get_blob_properties.side_effect = (
            ResourceNotFoundError()
        )
        self.blob_client.get_block_list.return_value = (
            [],
            [
                SimpleNamespace(id=self.layer._block_id(index), size=7)
                for index in (1, 0)
            ],
        )
        self.assertEqual(
            self.layer.finalize_save("file", "raw", total_chunks=2),
            self.blob_client.url,
        )
        commit = self.blob_client.commit_block_list.call_args
        self.assertEqual(
            [block.id for block in commit.args[0]],
            [self.layer._block_id(index) for index in (0, 1)],
        )
        self.assertEqual(
            commit.kwargs["metadata"],
            {
                "haste_upload_complete": "true",
                "haste_upload_total_chunks": "2",
            },
        )

    def test_load_all_scopes_initial_listing_to_partition_and_type(
        self,
    ) -> None:
        self.layer.container_client.walk_blobs.return_value = []
        self.assertEqual(self.layer.load_all("model"), [])
        self.layer.container_client.walk_blobs.assert_called_once_with(
            name_starts_with="partition/model_"
        )

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
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_cached_user_delegation_key",
        return_value="delegation-key",
    )
    def test_remote_path_signs_one_blob_with_the_identity(
        self, delegation_key
    ) -> None:
        identity_client = Mock()
        self.layer.identity_blob_service_client = identity_client
        self.layer.account_key = None
        self.layer.user_delegation_key = None
        self.layer.container_client.account_name = "account"
        self.layer.container_client.container_name = "metadata"
        self.blob_client.url = "https://account.test/metadata/model_a.json"

        with patch(
            "hastegeo.core.data_layer.azure_blob_storage_data_layer.blob_read_sas",
            return_value="sas",
        ) as sas:
            result = self.layer.get_file_remote_path(
                "a", "model", check_exists=False
            )

        self.assertEqual(result, f"{self.blob_client.url}?sas")
        self.assertEqual(delegation_key.call_args.args, (identity_client,))
        kwargs = sas.call_args.kwargs
        self.assertEqual(kwargs["blob_name"], "partition/model_a.json")
        self.assertIsNone(kwargs["account_key"])
        self.assertEqual(kwargs["user_delegation_key"], "delegation-key")

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_cached_user_delegation_key"
    )
    def test_remote_path_on_the_emulator_uses_the_account_key(
        self, delegation_key
    ) -> None:
        self.layer.identity_blob_service_client = None
        self.layer.account_key = "account-key"  # pragma: allowlist secret
        self.layer.user_delegation_key = None
        self.layer.container_client.account_name = "account"
        self.layer.container_client.container_name = "metadata"
        self.blob_client.url = "http://azurite:10000/account/metadata/a.json"

        with patch(
            "hastegeo.core.data_layer.azure_blob_storage_data_layer.blob_read_sas",
            return_value="sas",
        ) as sas:
            self.layer.get_file_remote_path("a", "model", check_exists=False)

        delegation_key.assert_not_called()
        self.assertEqual(sas.call_args.kwargs["account_key"], "account-key")

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
    def test_connection_string_uses_cached_client(self, factory):
        service = Mock(url="https://account.test")
        service.credential.account_key = "key"  # pragma: allowlist secret
        factory.return_value = service

        layer = AzureBlobStorageDataLayer(
            account_url="",
            container="metadata",
            connection_string="connection",
        )

        self.assertIs(layer.blob_service_client, service)
        self.assertIsNone(layer.identity_blob_service_client)
        factory.assert_called_once_with(connection_string="connection")

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_blob_service_client"
    )
    def test_connection_string_with_https_url_signs_by_identity(self, factory):
        service = Mock(url="https://account.test")
        service.credential.account_key = "key"  # pragma: allowlist secret
        factory.return_value = service

        layer = AzureBlobStorageDataLayer(
            account_url="https://account.test",
            container="metadata",
            connection_string="connection",
        )

        self.assertIsNotNone(layer.identity_blob_service_client)
        factory.assert_any_call(account_url="https://account.test")

    @patch(
        "hastegeo.core.data_layer.azure_blob_storage_data_layer.get_blob_service_client"
    )
    def test_managed_identity_uses_cached_client(self, factory):
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


if __name__ == "__main__":
    unittest.main()
