# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
import re

import psycopg2  # type: ignore
from azure.identity import DefaultAzureCredential  # type: ignore
from psycopg2 import sql  # type: ignore
from rasterio.io import MemoryFile

from .abstract_data_layer import AbstractDataLayer


class AzurePostgreSQLDataLayer(AbstractDataLayer):
    def __init__(self, host, database, table, partition_key=None, user=None):
        super().__init__(partition_key)
        self.server_name = host
        self.database_name = database
        self.table_name = table
        self.postgres_user = user or os.getenv("POSTGRES_USER", "postgres")
        self._qualified_table_identifier = self._build_table_identifier(table)
        self.credential = DefaultAzureCredential()
        self.token = self.credential.get_token(
            "https://ossrdbms-aad.database.windows.net/.default"
        ).token
        self._create_table_if_not_exists()

    @staticmethod
    def _build_table_identifier(table_name):
        if not isinstance(table_name, str) or not table_name.strip():
            raise ValueError(
                "PostgreSQL table name must be a non-empty string"
            )

        parts = table_name.split(".")
        if len(parts) > 2:
            raise ValueError(
                f"Invalid PostgreSQL table name '{table_name}'. Use 'table' or 'schema.table'."
            )

        for part in parts:
            if len(part) > 63:
                raise ValueError(
                    f"Invalid PostgreSQL identifier '{part}' in table name '{table_name}'. "
                    "Identifiers must be 63 characters or fewer."
                )
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) is None:
                raise ValueError(
                    f"Invalid PostgreSQL identifier '{part}' in table name '{table_name}'"
                )

        return sql.SQL(".").join([sql.Identifier(part) for part in parts])

    def _table_identifier(self):
        return self._qualified_table_identifier

    def _create_table_if_not_exists(self):
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                    CREATE TABLE IF NOT EXISTS {} (
                        identifier TEXT,
                        data_type TEXT,
                        partition_key TEXT,
                        data JSONB,
                        bounds GEOMETRY,
                        transform JSONB,
                        crs TEXT,
                        PRIMARY KEY (identifier, data_type)
                    )
                """
                    ).format(self._table_identifier())
                )
                connection.commit()

    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.validate_data_input(data, data_file_path)
        if data_format != "json":
            raise ValueError(
                "Unsupported data format. Only json is supported."
            )
        if data_file_path:
            data = self.load_data_from_file(data_file_path)
        if self.is_json(data) is False:
            raise ValueError(
                "Unsupported data format. Only json is supported."
            )
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                    INSERT INTO {} (identifier, data_type, partition_key, data)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (identifier, data_type)
                    DO UPDATE SET data = EXCLUDED.data
                """
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key, json.dumps(data)),
                )
                connection.commit()

    def save_chunk(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="tif",
        chunk_id=None,
    ):
        # TODO: Figure out how to save chunks if this data layer class will be supported
        pass

    def finalize_save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="tif",
    ):
        # This method not tested on PostgreSQL
        self.validate_data_input(data, data_file_path)
        if data_format != "tif":
            raise ValueError("Unsupported data format. Only tif is supported.")
        if data_file_path:
            data = self.load_data_from_file(data_file_path)

        with MemoryFile(data) as memfile:
            with memfile.open() as dataset:
                bounds = dataset.bounds
                transform = dataset.transform
                crs = dataset.crs.to_string()
                data = dataset.read(1).tolist()

        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                    INSERT INTO {} (identifier, data_type, partition_key, data, bounds, transform, crs)
                    VALUES (%s, %s, %s, %s, ST_MakeEnvelope(%s, %s, %s, %s, %s), %s, %s)
                    ON CONFLICT (identifier, data_type)
                    DO UPDATE SET data = EXCLUDED.data, bounds = EXCLUDED.bounds, transform = EXCLUDED.transform, crs = EXCLUDED.crs
                """
                    ).format(self._table_identifier()),
                    (
                        identifier,
                        data_type,
                        partition_key,
                        json.dumps(data),
                        bounds.left,
                        bounds.bottom,
                        bounds.right,
                        bounds.top,
                        crs,
                        json.dumps(transform),
                        crs,
                    ),
                )
                connection.commit()

    def update(self, data, identifier, data_type):
        self.save(data, identifier, data_type)

    def load(self, identifier, data_type):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT data FROM {} WHERE identifier = %s AND data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key),
                )
                result = cursor.fetchone()
                if result is None:
                    raise FileNotFoundError(
                        f"No data found for identifier: {identifier} and data_type: {data_type}"
                    )
                return json.loads(result[0])

    def load_all(self, data_type):
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT data FROM {} WHERE data_type = %s").format(
                        self._table_identifier()
                    ),
                    (data_type,),
                )
                results = cursor.fetchall()
                return [json.loads(result[0]) for result in results]

    def load_all_from_partition(self, data_type):
        partition_key = self.partition_key
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT data FROM {} WHERE data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (data_type, partition_key),
                )
                results = cursor.fetchall()
                return [json.loads(result[0]) for result in results]

    def load_bounded(self, data_type, max_records, data_format="json"):
        if data_format != "json" or max_records < 1:
            raise ValueError("Invalid bounded PostgreSQL read")
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT data FROM {} WHERE data_type = %s LIMIT %s"
                    ).format(self._table_identifier()),
                    (data_type, max_records + 1),
                )
                results = cursor.fetchall()
        if len(results) > max_records:
            raise ValueError(
                f"Metadata exceeds the {max_records:,}-record limit"
            )
        return [json.loads(result[0]) for result in results]

    def delete(self, identifier, data_type):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "DELETE FROM {} WHERE identifier = %s AND data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key),
                )
                connection.commit()

    def delete_all_from_partition(self):
        partition_key = self.partition_key
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DELETE FROM {} WHERE partition_key = %s").format(
                        self._table_identifier()
                    ),
                    (partition_key,),
                )
                connection.commit()

    def get_bounds(self, identifier, data_type):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT bounds FROM {} WHERE identifier = %s AND data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key),
                )
                result = cursor.fetchone()
                if result is None:
                    raise FileNotFoundError(
                        f"No data found for identifier: {identifier} and data_type: {data_type}"
                    )
                return result[0]

    def get_transform(self, identifier, data_type):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT transform FROM {} WHERE identifier = %s AND data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key),
                )
                result = cursor.fetchone()
                if result is None:
                    raise FileNotFoundError(
                        f"No data found for identifier: {identifier} and data_type: {data_type}"
                    )
                return result[0]

    def get_crs(self, identifier, data_type):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        connection_string = f"host={self.server_name} dbname={self.database_name} user={self.postgres_user} password={self.token} sslmode=require"
        with psycopg2.connect(connection_string) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT crs FROM {} WHERE identifier = %s AND data_type = %s AND partition_key = %s"
                    ).format(self._table_identifier()),
                    (identifier, data_type, partition_key),
                )
                result = cursor.fetchone()
                if result is None:
                    raise FileNotFoundError(
                        f"No data found for identifier: {identifier} and data_type: {data_type}"
                    )
                return result[0]
