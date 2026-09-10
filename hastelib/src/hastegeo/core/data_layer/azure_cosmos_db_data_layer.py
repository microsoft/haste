# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import re

from azure.core import MatchConditions
from azure.cosmos import CosmosClient, exceptions  # type: ignore
from azure.identity import DefaultAzureCredential  # type: ignore

from .abstract_data_layer import AbstractDataLayer
from .conditional import JsonDocument, RevisionConflictError


class AzureCosmosDBDataLayer(AbstractDataLayer):
    def __init__(self, endpoint, database, container, partition_key=None):
        super().__init__(partition_key)
        credential = DefaultAzureCredential()
        self.client = CosmosClient(endpoint, credential=credential)
        self.database = self.client.get_database_client(database)
        self.container = self.database.get_container_client(container)

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

        data["id"] = f"{data_type}_{identifier}"
        data["partition_key"] = (
            self.partition_key if self.partition_key else identifier
        )
        self.container.upsert_item(data)

    def load_json_versioned(
        self, identifier: str, data_type: str
    ) -> tuple[JsonDocument, str]:
        document = self.load(identifier, data_type)
        return document, document["_etag"]

    def save_json_if_version(
        self,
        identifier: str,
        data_type: str,
        data: JsonDocument,
        expected_version: str | None,
    ) -> None:
        if not isinstance(data, dict):
            raise ValueError("Cosmos metadata must be a JSON object")
        document = {
            key: value
            for key, value in data.items()
            if key not in {"_etag", "_rid", "_self", "_attachments", "_ts"}
        }
        document["id"] = f"{data_type}_{identifier}"
        document["partition_key"] = self.partition_key or identifier
        try:
            if expected_version is None:
                self.container.create_item(body=document)
            else:
                self.container.replace_item(
                    item=document["id"],
                    body=document,
                    etag=expected_version,
                    match_condition=MatchConditions.IfNotModified,
                )
        except exceptions.CosmosHttpResponseError as error:
            if error.status_code not in {404, 409, 412}:
                raise
            raise RevisionConflictError("Metadata revision changed") from error

    def update(self, data, identifier, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError(
                "Unsupported data format. Only json is supported."
            )
        self.save(data, identifier, data_type)

    def save_chunk(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="tif",
        chunk_id=None,
    ):
        raise NotImplementedError(
            "Method not implemented and supported for Azure Cosmos DB."
        )

    def finalize_save(
        self,
        identifier,
        data_type,
        data_format="tif",
        data_file_path=None,
        total_chunks=None,
    ):
        raise NotImplementedError(
            "Method not implemented and supported for Azure Cosmos DB."
        )

    def load(self, identifier, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError("Cosmos metadata supports only JSON")
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        try:
            item = self.container.read_item(
                item=f"{data_type}_{identifier}", partition_key=partition_key
            )
            return item
        except exceptions.CosmosResourceNotFoundError:
            raise FileNotFoundError(
                f"No data found for identifier: {identifier} and data_type: {data_type}"
            )

    def load_all(self, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError("Cosmos metadata supports only JSON")
        id_prefix = self._id_prefix(data_type)
        query = "SELECT * FROM c WHERE STARTSWITH(c.id, @id_prefix)"
        items = list(
            self.container.query_items(
                query=query,
                parameters=[{"name": "@id_prefix", "value": id_prefix}],
                enable_cross_partition_query=True,
            )
        )
        return items

    def load_all_from_partition(self, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError("Cosmos metadata supports only JSON")
        id_prefix = self._id_prefix(data_type)
        query = (
            "SELECT * FROM c WHERE c.partition_key = @partition_key "
            "AND STARTSWITH(c.id, @id_prefix)"
        )
        items = list(
            self.container.query_items(
                query=query,
                parameters=[
                    {
                        "name": "@partition_key",
                        "value": self.partition_key,
                    },
                    {"name": "@id_prefix", "value": id_prefix},
                ],
                enable_cross_partition_query=False,
                partition_key=self.partition_key,
            )
        )
        return items

    def load_bounded(self, data_type, max_records, data_format="json"):
        if (
            data_format != "json"
            or not isinstance(max_records, int)
            or not 1 <= max_records <= 10000
        ):
            raise ValueError("Invalid bounded Cosmos DB read")
        id_prefix = self._id_prefix(data_type)
        query = (
            f"SELECT TOP {max_records + 1} * FROM c "
            "WHERE STARTSWITH(c.id, @id_prefix)"
        )
        items = list(
            self.container.query_items(
                query=query,
                parameters=[
                    {"name": "@id_prefix", "value": id_prefix},
                ],
                enable_cross_partition_query=True,
                max_item_count=max_records + 1,
            )
        )
        if len(items) > max_records:
            raise ValueError(
                f"Metadata exceeds the {max_records:,}-record limit"
            )
        return items

    def delete(self, identifier, data_type, data_format="json"):
        partition_key = (
            self.partition_key if self.partition_key else identifier
        )
        self.container.delete_item(
            item=f"{data_type}_{identifier}", partition_key=partition_key
        )

    def delete_all_from_partition(self):
        query = "SELECT * FROM c WHERE c.partition_key = @partition_key"
        items = list(
            self.container.query_items(
                query=query,
                parameters=[
                    {"name": "@partition_key", "value": self.partition_key}
                ],
                enable_cross_partition_query=True,
            )
        )
        for item in items:
            self.container.delete_item(item, partition_key=self.partition_key)

    @staticmethod
    def _id_prefix(data_type):
        if not isinstance(data_type, str) or not data_type.strip():
            raise ValueError("data_type must be a non-empty string")

        if re.fullmatch(r"[A-Za-z0-9_-]+", data_type) is None:
            raise ValueError(
                "data_type contains unsupported characters. Use letters, numbers, underscore, or hyphen."
            )

        return f"{data_type}_"
