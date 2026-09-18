# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from types import SimpleNamespace

import pytest
from hastegeo.core.config import Config, StorageType
from hastegeo.core.data_layer import azure_postgresql_data_layer as postgres
from hastegeo.core.data_layer.conditional import RevisionConflictError
from psycopg2 import OperationalError


@pytest.fixture
def connection_setup(mocker) -> SimpleNamespace:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )
    mocker.patch.dict(
        "os.environ",
        {
            "POSTGRES_HOST": "postgres.example.invalid",
            "POSTGRES_DATABASE": "haste",
            "POSTGRES_TABLE": "public.metadata",
            "POSTGRES_USER": "test-user",
            "POSTGRES_PORT": "6432",
            "POSTGRES_PASSWORD": "",
        },
    )
    credential = mocker.patch.object(postgres, "DefaultAzureCredential")
    credential.return_value.get_token.return_value.token = "test-token"
    connect = mocker.patch.object(postgres.psycopg2, "connect")
    connection = connect.return_value
    connection.__enter__.return_value = connection
    cursor_context = connection.cursor.return_value
    cursor = cursor_context.__enter__.return_value
    cursor.rowcount = 1
    cursor.fetchone.return_value = (json.dumps({"name": "current"}), "42")
    cursor.fetchall.return_value = [(json.dumps({"name": "current"}),)]
    memory_file = mocker.patch.object(postgres, "MemoryFile")
    dataset = (
        memory_file.return_value.__enter__.return_value.open.return_value.__enter__.return_value
    )
    dataset.bounds = SimpleNamespace(left=0, bottom=0, right=1, top=1)
    dataset.transform = (1, 0, 0, 0, -1, 1)
    dataset.crs.to_string.return_value = "EPSG:4326"
    dataset.read.return_value.tolist.return_value = [[1]]

    layer = postgres.AzurePostgreSQLDataLayer(
        partition_key="partition",
        **Config().STORAGE_CONFIGS[StorageType.POSTGRES],
    )
    return SimpleNamespace(
        layer=layer,
        connect=connect,
        connection=connection,
        cursor_context=cursor_context,
        cursor=cursor,
        credential=credential.return_value,
        options={
            "host": "postgres.example.invalid",
            "dbname": "haste",
            "user": "test-user",
            "password": "test-token",  # pragma: allowlist secret
            "port": "6432",
            "sslmode": "require",
        },
    )


def test_construction_uses_configured_port_and_ssl(connection_setup) -> None:
    setup = connection_setup
    setup.connect.assert_called_once_with(**setup.options)
    setup.credential.get_token.assert_called_once_with(
        "https://ossrdbms-aad.database.windows.net/.default"
    )
    setup.connection.__enter__.assert_called_once_with()
    setup.connection.__exit__.assert_called_once_with(None, None, None)
    setup.connection.commit.assert_called_once_with()
    setup.connection.close.assert_not_called()
    assert "CREATE TABLE IF NOT EXISTS" in str(
        setup.cursor.execute.call_args.args[0]
    )


@pytest.mark.parametrize(
    "method,args,kwargs,commits",
    [
        ("save", ("key", "model"), {"data": {"name": "updated"}}, 1),
        ("load", ("key", "model"), {}, 0),
        ("load_all", ("model",), {}, 0),
        ("load_all_from_partition", ("model",), {}, 0),
        ("load_bounded", ("model", 2), {}, 0),
        ("load_json_versioned", ("key", "model"), {}, 0),
        ("save_json_if_version", ("key", "model", {}, None), {}, 0),
        ("save_json_if_version", ("key", "model", {}, "42"), {}, 0),
        ("delete", ("key", "model"), {}, 1),
        ("delete_all_from_partition", (), {}, 1),
        ("get_bounds", ("key", "model"), {}, 0),
        ("get_transform", ("key", "model"), {}, 0),
        ("get_crs", ("key", "model"), {}, 0),
        ("finalize_save", ("key", "imagery"), {"data": b"mock raster"}, 1),
    ],
)
def test_all_connection_paths_reuse_configured_port_and_lifecycle(
    connection_setup, method: str, args: tuple, kwargs: dict, commits: int
) -> None:
    setup = connection_setup
    setup.connect.reset_mock()

    getattr(setup.layer, method)(*args, **kwargs)

    setup.connect.assert_called_once_with(**setup.options)
    setup.connection.__enter__.assert_called_once_with()
    setup.connection.cursor.assert_called_once_with()
    setup.cursor_context.__enter__.assert_called_once_with()
    setup.cursor.execute.assert_called_once()
    setup.cursor_context.__exit__.assert_called_once_with(None, None, None)
    setup.connection.__exit__.assert_called_once_with(None, None, None)
    assert setup.connection.commit.call_count == commits
    setup.connection.close.assert_not_called()


def test_default_port_and_password_authentication_are_preserved(
    connection_setup,
) -> None:
    setup = connection_setup
    setup.connect.reset_mock()
    setup.credential.get_token.reset_mock()

    postgres.AzurePostgreSQLDataLayer(
        "postgres.example.invalid",
        "haste",
        "public.metadata",
        user="test-user",
        password="unit test value",  # pragma: allowlist secret
    )

    setup.connect.assert_called_once_with(
        **{
            **setup.options,
            "port": 5432,
            "password": "unit test value",  # pragma: allowlist secret
        }
    )
    setup.credential.get_token.assert_not_called()


def test_conditional_conflict_exits_the_same_transaction_with_error(
    connection_setup,
) -> None:
    setup = connection_setup
    setup.connect.reset_mock()
    setup.cursor.rowcount = 0

    with pytest.raises(RevisionConflictError) as caught:
        setup.layer.save_json_if_version("key", "model", {}, "stale")

    setup.connect.assert_called_once_with(**setup.options)
    assert setup.connection.__exit__.call_args.args[:2] == (
        RevisionConflictError,
        caught.value,
    )
    setup.connection.commit.assert_not_called()
    setup.connection.close.assert_not_called()


def test_connection_failure_propagates_without_retrying_the_default_port(
    connection_setup,
) -> None:
    setup = connection_setup
    setup.connect.reset_mock()
    error = OperationalError("configured endpoint is unavailable")
    setup.connect.side_effect = error

    with pytest.raises(OperationalError) as caught:
        setup.layer.load("key", "model")

    assert caught.value is error
    setup.connect.assert_called_once_with(**setup.options)
