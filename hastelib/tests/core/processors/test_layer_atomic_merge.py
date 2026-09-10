# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
from hastegeo.core.data_layer.json_merge import merge_blob_json
from hastegeo.core.data_layer.local_file_system_data_layer import (
    LocalFileSystemDataLayer,
)


class TestLayerAtomicMerge(unittest.TestCase):
    def test_blob_conflict_reloads_and_preserves_advanced_footprint_state(
        self,
    ) -> None:
        blob = MagicMock()
        snapshots = [
            {"name": "old", "footprintTilesStatus": "InProgress"},
            {
                "name": "old",
                "footprintTilesStatus": "Processed",
                "footprintPmtilesUrl": "new",
            },
        ]
        downloads = [
            SimpleNamespace(
                readall=lambda row=row: json.dumps(row),
                properties=SimpleNamespace(etag=f"etag-{index}"),
            )
            for index, row in enumerate(snapshots)
        ]
        blob.download_blob.side_effect = downloads
        blob.upload_blob.side_effect = [
            ResourceModifiedError("conflict"),
            None,
        ]
        merged = merge_blob_json(blob, {"name": "new"})
        self.assertEqual(merged["footprintTilesStatus"], "Processed")
        self.assertEqual(merged["footprintPmtilesUrl"], "new")
        self.assertEqual(merged["name"], "new")
        self.assertEqual(blob.upload_blob.call_args.kwargs["etag"], "etag-1")
        self.assertEqual(
            blob.upload_blob.call_args.kwargs["match_condition"],
            MatchConditions.IfNotModified,
        )

    def test_create_is_conditional_and_contention_is_bounded(self) -> None:
        blob = MagicMock()
        blob.download_blob.side_effect = ResourceNotFoundError("missing")
        merge_blob_json(blob, {"name": "new"})
        self.assertFalse(blob.upload_blob.call_args.kwargs["overwrite"])
        blob.download_blob.side_effect = None
        blob.download_blob.return_value.readall.return_value = "{}"
        blob.upload_blob.side_effect = ResourceModifiedError("conflict")
        with self.assertRaises(ResourceModifiedError):
            merge_blob_json(blob, {"name": "new"})
        self.assertEqual(blob.upload_blob.call_count, 6)

    def test_local_merge_keeps_disjoint_fields_and_writes_valid_json(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            layer = LocalFileSystemDataLayer(directory)
            layer.merge_json("layer", "imagelayer", {"name": "old"})
            layer.merge_json(
                "layer", "imagelayer", {"footprintTilesStatus": "Processed"}
            )
            layer.merge_json("layer", "imagelayer", {"name": "new"})
            self.assertEqual(
                json.loads(
                    Path(
                        layer.get_file_path("layer", "imagelayer")
                    ).read_text()
                ),
                {"name": "new", "footprintTilesStatus": "Processed"},
            )

    def test_cosmos_conflict_reloads_before_conditional_replace(self) -> None:
        from azure.cosmos.exceptions import CosmosHttpResponseError
        from hastegeo.core.data_layer.azure_cosmos_db_data_layer import (
            AzureCosmosDBDataLayer,
        )

        layer = AzureCosmosDBDataLayer.__new__(AzureCosmosDBDataLayer)
        layer.partition_key = "project"
        layer.container = MagicMock()
        layer.container.read_item.side_effect = [
            {"_etag": "old", "name": "old"},
            {"_etag": "new", "name": "old", "footprintPmtilesUrl": "ready"},
        ]
        layer.container.replace_item.side_effect = [
            CosmosHttpResponseError(status_code=412, message="conflict"),
            {"name": "new", "footprintPmtilesUrl": "ready"},
        ]
        output = layer.merge_json("layer", "imagelayer", {"name": "new"})
        self.assertEqual(output["footprintPmtilesUrl"], "ready")
        self.assertEqual(
            layer.container.replace_item.call_args.kwargs["etag"], "new"
        )
        self.assertEqual(
            layer.container.replace_item.call_args.args[1][
                "footprintPmtilesUrl"
            ],
            "ready",
        )

    def test_postgres_merges_fields_in_a_single_statement(self) -> None:
        from hastegeo.core.data_layer.azure_postgresql_data_layer import (
            AzurePostgreSQLDataLayer,
        )

        layer = AzurePostgreSQLDataLayer.__new__(AzurePostgreSQLDataLayer)
        layer.server_name = "host"
        layer.database_name = "database"
        layer.postgres_user = "user"
        layer.token = "test-token"
        layer.partition_key = "project"
        layer._qualified_table_identifier = layer._build_table_identifier(
            "metadata"
        )
        with patch(
            "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
        ) as connect:
            cursor = (
                connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            )
            cursor.fetchone.return_value = (
                {"name": "new", "footprintPmtilesUrl": "ready"},
            )
            output = layer.merge_json("layer", "imagelayer", {"name": "new"})
        self.assertEqual(output["footprintPmtilesUrl"], "ready")
        self.assertIn(
            "|| EXCLUDED.data", str(cursor.execute.call_args.args[0])
        )
        self.assertEqual(
            cursor.execute.call_args.args[1][-1], '{"name": "new"}'
        )

    def test_datalake_uses_the_same_atomic_blob_merge(self) -> None:
        from hastegeo.core.data_layer.azure_data_lake_data_layer import (
            AzureDataLakeDataLayer,
        )

        layer = AzureDataLakeDataLayer.__new__(AzureDataLakeDataLayer)
        layer.account_url = "https://account.dfs.core.windows.net"
        layer.credential = object()
        layer.partition_key = "project"
        layer.file_system_client = SimpleNamespace(file_system_name="metadata")
        with patch("azure.storage.blob.BlobServiceClient") as service, patch(
            "hastegeo.core.data_layer.json_merge.merge_blob_json",
            return_value={"name": "new"},
        ) as merge:
            layer.merge_json("layer", "imagelayer", {"name": "new"})
        self.assertEqual(
            service.call_args.args[0], "https://account.blob.core.windows.net"
        )
        merge.assert_called_once()
        service.return_value.__enter__.return_value.get_blob_client.assert_called_once_with(
            "metadata", "project/imagelayer_layer.json"
        )
