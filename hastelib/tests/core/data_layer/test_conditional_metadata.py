# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.cosmos.exceptions import CosmosHttpResponseError
from hastegeo.core.config import Config
from hastegeo.core.data_layer.azure_blob_storage_data_layer import (
    AzureBlobStorageDataLayer,
)
from hastegeo.core.data_layer.azure_cosmos_db_data_layer import (
    AzureCosmosDBDataLayer,
)
from hastegeo.core.data_layer.azure_data_lake_data_layer import (
    AzureDataLakeDataLayer,
)
from hastegeo.core.data_layer.azure_postgresql_data_layer import (
    AzurePostgreSQLDataLayer,
)
from hastegeo.core.data_layer.conditional import RevisionConflictError
from hastegeo.core.data_layer.local_file_system_data_layer import (
    LocalFileSystemDataLayer,
)
from hastegeo.core.processors.metadata import MetadataProcessor
from psycopg2 import sql


@pytest.fixture(autouse=True)
def no_network(mocker) -> None:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )


@pytest.fixture(params=["blob", "datalake"])
def blob_store(request, mocker):
    client = mocker.Mock()
    download = client.download_blob.return_value
    download.properties = SimpleNamespace(etag="etag-1")
    download.readall.return_value = b'{"name": "current"}'
    if request.param == "blob":
        layer = AzureBlobStorageDataLayer.__new__(AzureBlobStorageDataLayer)
        layer.container_client = mocker.Mock()
        layer.container_client.get_blob_client.return_value = client
    else:
        layer = AzureDataLakeDataLayer.__new__(AzureDataLakeDataLayer)
        layer.metadata_blob_container = mocker.Mock()
        layer.metadata_blob_container.get_blob_client.return_value = client
    layer.partition_key = "partition"
    return layer, client


def test_blob_and_datalake_updates_use_the_read_etag(blob_store) -> None:
    layer, client = blob_store
    current, version = layer.load_json_versioned("key", "model")
    assert current == {"name": "current"}
    assert version == "etag-1"
    layer.save_json_if_version("key", "model", {"name": "updated"}, version)
    options = client.upload_blob.call_args.kwargs
    assert options["etag"] == version
    assert options["match_condition"] == MatchConditions.IfNotModified
    assert options["overwrite"] is True


def test_blob_and_datalake_creation_is_create_only(blob_store) -> None:
    layer, client = blob_store
    layer.save_json_if_version("key", "model", {"name": "new"}, None)
    assert client.upload_blob.call_args.kwargs["overwrite"] is False


@pytest.mark.parametrize(
    "error",
    [
        ResourceExistsError("exists"),
        ResourceModifiedError("changed"),
        ResourceNotFoundError("deleted"),
    ],
)
def test_blob_and_datalake_conflicts_are_explicit(
    blob_store, error: Exception
) -> None:
    layer, client = blob_store
    client.upload_blob.side_effect = error
    with pytest.raises(RevisionConflictError):
        layer.save_json_if_version("key", "model", {}, "old")


def test_blob_and_datalake_read_does_not_treat_auth_failure_as_absence(
    blob_store,
) -> None:
    layer, client = blob_store
    client.download_blob.side_effect = HttpResponseError(
        "forbidden", status_code=403
    )
    with pytest.raises(HttpResponseError):
        layer.load_json_versioned("key", "model")
    client.upload_blob.assert_not_called()


def test_blob_legacy_loader_propagates_authentication_errors(mocker) -> None:
    layer = AzureBlobStorageDataLayer.__new__(AzureBlobStorageDataLayer)
    layer.partition_key = "partition"
    layer.container_client = mocker.Mock()
    layer.container_client.get_blob_client.return_value.download_blob.side_effect = HttpResponseError(
        "forbidden", status_code=403
    )
    with pytest.raises(HttpResponseError):
        layer.load("key", "model")


def test_datalake_uses_the_same_account_and_filesystem_for_conditional_writes(
    mocker,
) -> None:
    credential = mocker.patch(
        "hastegeo.core.data_layer.azure_data_lake_data_layer.DefaultAzureCredential"
    )
    mocker.patch(
        "hastegeo.core.data_layer.azure_data_lake_data_layer.DataLakeServiceClient"
    )
    blob = mocker.patch(
        "hastegeo.core.data_layer.azure_data_lake_data_layer.BlobServiceClient"
    )
    AzureDataLakeDataLayer("https://account.dfs.core.windows.net", "metadata")
    blob.assert_called_once_with(
        account_url="https://account.blob.core.windows.net",
        credential=credential.return_value,
    )
    blob.return_value.get_container_client.assert_called_once_with("metadata")


@pytest.fixture
def cosmos(mocker):
    layer = AzureCosmosDBDataLayer.__new__(AzureCosmosDBDataLayer)
    layer.partition_key = "partition"
    layer.container = mocker.Mock()
    layer.container.read_item.return_value = {
        "id": "model_key",
        "partition_key": "partition",
        "name": "current",
        "_etag": "etag-1",
    }
    return layer


def test_cosmos_replaces_only_the_expected_partitioned_revision(
    cosmos,
) -> None:
    current, version = cosmos.load_json_versioned("key", "model")
    cosmos.save_json_if_version("key", "model", current, version)
    cosmos.container.read_item.assert_called_once_with(
        item="model_key", partition_key="partition"  # gitleaks:allow
    )
    options = cosmos.container.replace_item.call_args.kwargs
    assert options["etag"] == "etag-1"
    assert options["match_condition"] == MatchConditions.IfNotModified
    assert options["body"]["partition_key"] == "partition"
    assert "_etag" not in options["body"]


def test_cosmos_creation_does_not_upsert_existing_records(cosmos) -> None:
    cosmos.save_json_if_version("key", "model", {"name": "new"}, None)
    cosmos.container.create_item.assert_called_once()
    cosmos.container.upsert_item.assert_not_called()


@pytest.mark.parametrize("status", [404, 409, 412])
def test_cosmos_conflict_or_deletion_rejects_the_write(
    cosmos, status: int
) -> None:
    cosmos.container.replace_item.side_effect = CosmosHttpResponseError(
        status_code=status, message="conflict"
    )
    with pytest.raises(RevisionConflictError):
        cosmos.save_json_if_version("key", "model", {}, "old")


def test_cosmos_nonconflict_service_error_is_not_retried_as_create(
    cosmos,
) -> None:
    cosmos.container.replace_item.side_effect = CosmosHttpResponseError(
        status_code=503, message="unavailable"
    )
    with pytest.raises(CosmosHttpResponseError):
        cosmos.save_json_if_version("key", "model", {}, "old")
    cosmos.container.create_item.assert_not_called()


@pytest.fixture
def postgres(mocker):
    layer = AzurePostgreSQLDataLayer.__new__(AzurePostgreSQLDataLayer)
    layer.partition_key = "partition"
    layer._qualified_table_identifier = sql.Identifier("metadata")
    connection, cursor = mocker.MagicMock(), mocker.MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.rowcount = 1
    cursor.fetchone.return_value = ({"name": "current"}, "42")
    mocker.patch.object(layer, "_metadata_connection", return_value=connection)
    return layer, cursor


def test_postgres_read_uses_mvcc_revision_and_accepts_native_jsonb(
    postgres,
) -> None:
    layer, cursor = postgres
    assert layer.load_json_versioned("key", "model") == (
        {"name": "current"},
        "42",
    )
    query, parameters = cursor.execute.call_args.args
    assert "xmin::text" in str(query)
    assert parameters == ("key", "model", "partition")


def test_postgres_update_is_parameterized_and_revision_conditional(
    postgres,
) -> None:
    layer, cursor = postgres
    layer.save_json_if_version(
        "key'; DROP TABLE metadata", "model", {"counter": 1}, "42"
    )
    query, parameters = cursor.execute.call_args.args
    assert "xmin::text = %s" in str(query)
    assert "DROP TABLE" not in str(query)
    assert parameters == (
        json.dumps({"counter": 1}),
        "key'; DROP TABLE metadata",
        "model",
        "partition",
        "42",
    )


def test_postgres_creation_does_not_overwrite_an_existing_record(
    postgres,
) -> None:
    layer, cursor = postgres
    cursor.rowcount = 0
    with pytest.raises(RevisionConflictError):
        layer.save_json_if_version("key", "model", {}, None)
    assert "DO NOTHING" in str(cursor.execute.call_args.args[0])


def test_postgres_update_detects_stale_or_deleted_row(postgres) -> None:
    layer, cursor = postgres
    cursor.rowcount = 0
    with pytest.raises(RevisionConflictError):
        layer.save_json_if_version("key", "model", {}, "old")


def test_local_competing_writers_cannot_both_replace_one_revision(
    tmp_path: Path,
) -> None:
    layer = LocalFileSystemDataLayer(str(tmp_path))
    layer.save_json_if_version("key", "model", {"counter": 0}, None)
    _, revision = layer.load_json_versioned("key", "model")

    def replace(value: int) -> str:
        try:
            layer.save_json_if_version(
                "key", "model", {"counter": value}, revision
            )
            return "saved"
        except RevisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(replace, [1, 2]))
    assert sorted(results) == ["conflict", "saved"]
    assert layer.load_json_versioned("key", "model")[0]["counter"] in {1, 2}


def test_local_delete_invalidates_an_inflight_revision(tmp_path: Path) -> None:
    layer = LocalFileSystemDataLayer(str(tmp_path))
    layer.save_json_if_version("key", "model", {}, None)
    _, revision = layer.load_json_versioned("key", "model")
    layer.delete("key", "model")
    with pytest.raises(RevisionConflictError):
        layer.save_json_if_version(
            "key", "model", {"name": "resurrected"}, revision
        )


def test_metadata_merge_retries_conflicts_against_fresh_data(
    tmp_path: Path, mocker
) -> None:
    mocker.patch.dict(
        "os.environ",
        {
            "METADATA_STORAGE_TYPE": "local",
            "DATA_PATH": str(tmp_path),
        },
    )
    processor = MetadataProcessor("model", config=Config())
    processor.save("key", {"name": "old", "counter": 0})
    original = processor.storage.save_json_if_version
    calls = 0

    def conflict_once(identifier, data_type, data, expected_version) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            original(
                identifier,
                data_type,
                {"name": "user edit", "counter": 0},
                expected_version,
            )
        original(identifier, data_type, data, expected_version)

    mocker.patch.object(
        processor.storage, "save_json_if_version", side_effect=conflict_once
    )
    processor.mutate(
        "key", lambda current: {**current, "counter": current["counter"] + 1}
    )
    assert processor.load("key") == {"name": "user edit", "counter": 1}
    assert calls == 2


def test_local_all_records_scan_stays_within_metadata_layout(
    tmp_path: Path,
) -> None:
    LocalFileSystemDataLayer(str(tmp_path), "partition").save_json_if_version(
        "key", "model", {"name": "included"}, None
    )
    nested = tmp_path / "partition" / "task" / "model_output.json"
    nested.parent.mkdir()
    nested.write_text('{"name": "not metadata"}')
    assert LocalFileSystemDataLayer(str(tmp_path)).load_all("model") == [
        {"name": "included"}
    ]
