# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from azure.identity import DefaultAzureCredential  # type: ignore
from azure.storage.filedatalake import DataLakeServiceClient  # type: ignore

from ..utils.metadata import matches_metadata_type
from .abstract_data_layer import AbstractDataLayer


class AzureDataLakeDataLayer(AbstractDataLayer):
    def __init__(self, account_url, file_system, partition_key=None):
        super().__init__(partition_key)
        credential = DefaultAzureCredential()
        self.service_client = DataLakeServiceClient(
            account_url=account_url, credential=credential
        )
        self.file_system_client = self.service_client.get_file_system_client(
            file_system
        )

    def get_file_path(
        self,
        identifier,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        partition_keys = []
        if self.partition_key:
            partition_keys.append(self.partition_key)
        if extra_partition_keys and isinstance(extra_partition_keys, list):
            partition_keys += extra_partition_keys
        if extra_partition_keys and isinstance(extra_partition_keys, str):
            partition_keys.append(extra_partition_keys)
        if identifier.endswith("." + data_format):
            filename = f"{data_type}_{identifier}"
        else:
            filename = f"{data_type}_{identifier}.{data_format}"
        return (
            f'{"/".join(partition_keys)}/{filename}'
            if partition_keys
            else f"{filename}"
        )

    def get_file_remote_path(
        self,
        identifier=None,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
        check_exists=True,
    ):
        file_name = self.get_file_path(
            identifier, data_type, data_format, extra_partition_keys
        )
        file_client = self.file_system_client.get_file_client(file_name)
        if check_exists and not file_client.exists():
            return None
        sas_url = file_client.url
        return str(sas_url)

    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.validate_data_input(data, data_file_path)

        if data_file_path:
            data = self.load_data_from_file(data_file_path)

        file_name = self.get_file_path(identifier, data_type, data_format)
        file_client = self.file_system_client.get_file_client(file_name)

        if isinstance(data, dict):
            file_contents = json.dumps(data)
            file_client.upload_data(file_contents, overwrite=True)
        elif isinstance(data, bytes):
            file_client.upload_data(data, overwrite=True)
        else:
            raise ValueError(
                "Unsupported data format. Only dict and bytes are supported."
            )

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
            "Method not implemented for Azure Data Lake Storage."
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
            "Method not implemented for Azure Data Lake Storage."
        )

    def update(self, data, identifier, data_type):
        self.save(data, identifier, data_type)

    def load(self, identifier, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError("Data Lake metadata reads support only json")
        file_name = self.get_file_path(identifier, data_type, data_format)
        file_client = self.file_system_client.get_file_client(file_name)
        download = file_client.download_file()
        file_contents = download.readall()
        return json.loads(file_contents)

    def load_all(self, data_type, data_format="json"):
        if data_format != "json":
            raise ValueError("Data Lake metadata reads support only json")
        data = []
        paths = self.file_system_client.get_paths()
        for path in paths:
            in_partition = not self.partition_key or path.name.startswith(
                f"{self.partition_key}/"
            )
            if in_partition and matches_metadata_type(path.name, data_type):
                file_client = self.file_system_client.get_file_client(
                    path.name
                )
                download = file_client.download_file()
                file_contents = download.readall()
                data.append(json.loads(file_contents))
        return data

    def load_all_from_partition(self, data_type, data_format="json"):
        data = self.load_all(data_type, data_format=data_format)
        return data

    def list_identifiers(self, data_type, data_format="json"):
        prefix = f"{self.partition_key}/{data_type}_"
        suffix = f".{data_format}"
        identifiers = []
        for path in self.file_system_client.get_paths(path=self.partition_key):
            if (
                path.name.startswith(prefix)
                and path.name.endswith(suffix)
                and matches_metadata_type(path.name, data_type)
            ):
                identifiers.append(path.name[len(prefix) : -len(suffix)])
        return identifiers

    def load_bounded(self, data_type, max_records, data_format="json"):
        if data_format != "json" or max_records < 1:
            raise ValueError("Invalid bounded Data Lake read")
        data = []
        scanned_paths = 0
        scan_limit = max_records * 10
        for path in self.file_system_client.get_paths():
            scanned_paths += 1
            if scanned_paths > scan_limit:
                raise ValueError("Metadata scan exceeds the bounded envelope")
            parts = path.name.split("/")
            if len(parts) > 2 or not matches_metadata_type(
                path.name, data_type
            ):
                continue
            file_contents = (
                self.file_system_client.get_file_client(path.name)
                .download_file()
                .readall()
            )
            data.append(json.loads(file_contents))
            if len(data) > max_records:
                raise ValueError(
                    f"Metadata exceeds the {max_records:,}-record limit"
                )
        return data

    def delete(self, identifier, data_type, data_format="json"):
        file_name = self.get_file_path(
            identifier, data_type, data_format=data_format
        )
        file_client = self.file_system_client.get_file_client(file_name)
        file_client.delete_file()

    def delete_all_from_partition(self):
        paths = self.file_system_client.get_paths()
        for path in paths:
            if path.name.startswith(self.partition_key):
                file_client = self.file_system_client.get_file_client(
                    path.name
                )
                file_client.delete_file()
