# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from hastegeo.core.data_layer.abstract_data_layer import AbstractDataLayer
from hastegeo.core.data_layer.azure_cosmos_db_data_layer import (
    AzureCosmosDBDataLayer,
)
from hastegeo.core.data_layer.azure_data_lake_data_layer import (
    AzureDataLakeDataLayer,
)
from hastegeo.core.data_layer.azure_postgresql_data_layer import (
    AzurePostgreSQLDataLayer,
)
from hastegeo.core.data_layer.local_file_system_data_layer import (
    LocalFileSystemDataLayer,
)
from hastegeo.core.data_layer.unified import UnifiedDataLayer
from psycopg2 import sql


class TestCosmosReadContract(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = AzureCosmosDBDataLayer.__new__(AzureCosmosDBDataLayer)
        self.layer.partition_key = "partition"
        self.layer.container = Mock()

    def test_load_accepts_unified_data_format_keyword(self) -> None:
        self.layer.container.read_item.return_value = {"value": 1}

        result = self.layer.load("record", "model", data_format="json")

        self.assertEqual(result, {"value": 1})

    def test_list_identifiers_uses_partition_query(self) -> None:
        self.layer.container.query_items.return_value = [
            "model_a",
            "model_b",
            "model_catalog_index",
        ]

        result = self.layer.list_identifiers("model")

        self.assertEqual(result, ["a", "b"])
        call = self.layer.container.query_items.call_args.kwargs
        self.assertEqual(call["partition_key"], "partition")
        self.assertFalse(call["enable_cross_partition_query"])

    def test_non_json_identifier_listing_is_empty(self) -> None:
        self.assertEqual(
            self.layer.list_identifiers("train_labels", "geojson"), []
        )
        self.layer.container.query_items.assert_not_called()

    def test_load_map_uses_one_partition_query_and_preserves_missing(
        self,
    ) -> None:
        self.layer.container.query_items.return_value = [
            {"id": "model_a", "value": 1}
        ]

        result = self.layer.load_map(
            ["a", "a", "missing"], "model", max_workers=4
        )

        self.assertEqual(
            result,
            {"a": {"id": "model_a", "value": 1}, "missing": None},
        )
        call = self.layer.container.query_items.call_args.kwargs
        self.assertEqual(call["partition_key"], "partition")
        self.assertEqual(
            call["parameters"][1],
            {"name": "@item_ids", "value": ["model_a", "model_missing"]},
        )

    def test_partition_load_excludes_longer_metadata_type(self) -> None:
        self.layer.container.query_items.return_value = [
            {"id": "model_a"},
            {"id": "model_catalog_index"},
        ]

        result = self.layer.load_all_from_partition("model")

        self.assertEqual(result, [{"id": "model_a"}])

    def test_global_load_excludes_longer_metadata_type(self) -> None:
        self.layer.container.query_items.return_value = [
            {"id": "model_a"},
            {"id": "model_catalog_index"},
        ]

        result = self.layer.load_all("model")

        self.assertEqual(result, [{"id": "model_a"}])

    def test_load_map_handles_empty_and_non_json_inputs(self) -> None:
        self.assertEqual(self.layer.load_map([], "model"), {})
        with self.assertRaisesRegex(ValueError, "only json"):
            self.layer.load_map(["a"], "model", data_format="geojson")

    def test_read_methods_reject_non_json_format(self) -> None:
        for method, args in (
            (self.layer.load, ("record", "model")),
            (self.layer.load_all, ("model",)),
            (self.layer.load_all_from_partition, ("model",)),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(ValueError, "only json"):
                    method(*args, data_format="yaml")


class TestDataLakeReadContract(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = AzureDataLakeDataLayer.__new__(AzureDataLakeDataLayer)
        self.layer.partition_key = "partition"
        self.layer.file_system_client = Mock()

    def test_remote_path_can_skip_exists_request(self) -> None:
        file_client = (
            self.layer.file_system_client.get_file_client.return_value
        )
        file_client.url = "https://account.test/file"

        result = self.layer.get_file_remote_path(
            "record", "model", check_exists=False
        )

        self.assertEqual(result, "https://account.test/file")
        file_client.exists.assert_not_called()

    def test_missing_remote_path_returns_none(self) -> None:
        file_client = (
            self.layer.file_system_client.get_file_client.return_value
        )
        file_client.exists.return_value = False

        result = self.layer.get_file_remote_path("record", "model")

        self.assertIsNone(result)

    def test_list_identifiers_strips_prefix_and_suffix(self) -> None:
        self.layer.file_system_client.get_paths.return_value = [
            SimpleNamespace(name="partition/model_a.json"),
            SimpleNamespace(name="partition/model_b.json"),
            SimpleNamespace(name="partition/model_catalog_index.json"),
            SimpleNamespace(name="partition/labels_c.json"),
        ]

        result = self.layer.list_identifiers("model")

        self.assertEqual(result, ["a", "b"])
        self.layer.file_system_client.get_paths.assert_called_once_with(
            path="partition"
        )

    def test_load_accepts_unified_data_format_keyword(self) -> None:
        file_client = (
            self.layer.file_system_client.get_file_client.return_value
        )
        file_client.download_file.return_value.readall.return_value = (
            b'{"value": 1}'
        )

        result = self.layer.load("record", "model", data_format="json")

        self.assertEqual(result, {"value": 1})

    def test_load_all_and_partition_forward_json_format(self) -> None:
        self.layer.file_system_client.get_paths.return_value = []
        self.assertEqual(self.layer.load_all("model", data_format="json"), [])
        with patch.object(self.layer, "load_all", return_value=[]) as load_all:
            self.assertEqual(
                self.layer.load_all_from_partition(
                    "model", data_format="json"
                ),
                [],
            )
        load_all.assert_called_once_with("model", data_format="json")

    def test_load_all_does_not_cross_configured_partition(self) -> None:
        self.layer.file_system_client.get_paths.return_value = [
            SimpleNamespace(name="partition/model_a.json"),
            SimpleNamespace(name="other/model_b.json"),
        ]
        file_client = (
            self.layer.file_system_client.get_file_client.return_value
        )
        file_client.download_file.return_value.readall.return_value = (
            b'{"id": "a"}'
        )

        result = self.layer.load_all("model")

        self.assertEqual(result, [{"id": "a"}])
        self.layer.file_system_client.get_file_client.assert_called_once_with(
            "partition/model_a.json"
        )

    def test_read_methods_reject_non_json_format(self) -> None:
        for method, args in (
            (self.layer.load, ("record", "model")),
            (self.layer.load_all, ("model",)),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(ValueError, "only json"):
                    method(*args, data_format="yaml")

    def test_bounded_load_skips_deep_and_other_type_paths(self) -> None:
        self.layer.file_system_client.get_paths.return_value = [
            SimpleNamespace(name="partition/nested/model_a.json"),
            SimpleNamespace(name="partition/labels_a.json"),
        ]

        self.assertEqual(self.layer.load_bounded("model", 2), [])


class TestPostgreSQLReadContract(unittest.TestCase):
    def setUp(self) -> None:
        self.layer = AzurePostgreSQLDataLayer.__new__(AzurePostgreSQLDataLayer)
        self.layer.partition_key = "partition"
        self.layer.server_name = "server"
        self.layer.database_name = "database"
        self.layer.postgres_user = "user"
        self.layer.token = "token"
        self.layer._qualified_table_identifier = sql.Identifier("metadata")

    @patch(
        "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
    )
    def test_load_accepts_jsonb_dictionary(self, connect) -> None:
        cursor = self._cursor(connect)
        cursor.fetchone.return_value = ({"value": 1},)

        result = self.layer.load("record", "model", data_format="json")

        self.assertEqual(result, {"value": 1})

    @patch(
        "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
    )
    def test_list_identifiers_is_partition_scoped(self, connect) -> None:
        cursor = self._cursor(connect)
        cursor.fetchall.return_value = [("a",), ("b",)]

        result = self.layer.list_identifiers("model")

        self.assertEqual(result, ["a", "b"])
        self.assertEqual(
            cursor.execute.call_args.args[1], ("model", "partition")
        )

    def test_non_json_identifier_listing_is_empty(self) -> None:
        self.assertEqual(
            self.layer.list_identifiers("train_labels", "geojson"), []
        )

    @patch(
        "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
    )
    def test_load_map_uses_one_query_and_preserves_missing(
        self, connect
    ) -> None:
        cursor = self._cursor(connect)
        cursor.fetchall.return_value = [("a", {"value": 1})]

        result = self.layer.load_map(
            ["a", "a", "missing"], "model", max_workers=4
        )

        self.assertEqual(result, {"a": {"value": 1}, "missing": None})
        self.assertEqual(
            cursor.execute.call_args.args[1],
            ("model", "partition", ["a", "missing"]),
        )

    def test_load_map_handles_empty_and_non_json_inputs(self) -> None:
        self.assertEqual(self.layer.load_map([], "model"), {})
        with self.assertRaisesRegex(ValueError, "only json"):
            self.layer.load_map(["a"], "model", data_format="geojson")

    @patch(
        "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
    )
    def test_load_all_accepts_jsonb_values(self, connect) -> None:
        cursor = self._cursor(connect)
        cursor.fetchall.return_value = [({"value": 1},)]

        self.assertEqual(
            self.layer.load_all("model", data_format="json"),
            [{"value": 1}],
        )

    @patch(
        "hastegeo.core.data_layer.azure_postgresql_data_layer.psycopg2.connect"
    )
    def test_load_partition_accepts_serialized_values(self, connect) -> None:
        cursor = self._cursor(connect)
        cursor.fetchall.return_value = [('{"value": 1}',)]

        self.assertEqual(
            self.layer.load_all_from_partition("model", data_format="json"),
            [{"value": 1}],
        )

    def test_read_methods_reject_non_json_format(self) -> None:
        for method, args in (
            (self.layer.load, ("record", "model")),
            (self.layer.load_all, ("model",)),
            (self.layer.load_all_from_partition, ("model",)),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(ValueError, "only json"):
                    method(*args, data_format="yaml")

    @staticmethod
    def _cursor(connect) -> MagicMock:
        connection = MagicMock()
        cursor = MagicMock()
        connect.return_value.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        return cursor


class TestOptionalRemotePathContract(unittest.TestCase):
    def test_default_remote_path_is_explicitly_unsupported(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "remote file paths"):
            AbstractDataLayer.get_file_remote_path(object())

    def test_default_batch_read_is_explicitly_unsupported(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "batch reads"):
            AbstractDataLayer.load_map(object(), [], "model")


class TestLocalReadContract(unittest.TestCase):
    def test_bounded_load_skips_nonmatching_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layer = LocalFileSystemDataLayer(directory)
            layer.save("index", "model_catalog", {"models": []})

            self.assertEqual(layer.load_bounded("model", 1), [])


class TestUnifiedReadContract(unittest.TestCase):
    def test_load_map_delegates_all_arguments(self) -> None:
        unified = UnifiedDataLayer.__new__(UnifiedDataLayer)
        unified.data_layer = Mock()
        unified.data_layer.load_map.return_value = {"a": {"value": 1}}

        result = unified.load_map(
            ["a"], "model", data_format="json", max_workers=4
        )

        self.assertEqual(result, {"a": {"value": 1}})
        unified.data_layer.load_map.assert_called_once_with(
            identifiers=["a"],
            data_type="model",
            data_format="json",
            max_workers=4,
        )


if __name__ == "__main__":
    unittest.main()
