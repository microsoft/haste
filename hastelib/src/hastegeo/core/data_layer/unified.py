# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import importlib
from typing import Any

from ..utils.metadata import MetadataUtils


class UnifiedDataLayer:
    def __init__(self, storage_type, partition_key=None, **kwargs):
        if partition_key:
            self.partition_key = MetadataUtils.hash_string(partition_key)
        else:
            self.partition_key = None

        # Dictionary to map storage types to their respective modules and class names
        storage_class_map = {
            "local": (
                "local_file_system_data_layer",
                "LocalFileSystemDataLayer",
            ),
            "blob": (
                "azure_blob_storage_data_layer",
                "AzureBlobStorageDataLayer",
            ),
            "cosmos": ("azure_cosmos_db_data_layer", "AzureCosmosDBDataLayer"),
            "datalake": (
                "azure_data_lake_data_layer",
                "AzureDataLakeDataLayer",
            ),
            "postgres": (
                "azure_postgresql_data_layer",
                "AzurePostgreSQLDataLayer",
            ),
        }

        if storage_type in storage_class_map:
            module_name, class_name = storage_class_map[storage_type]
            module = importlib.import_module(f"{__package__}.{module_name}")
            data_layer_class = getattr(module, class_name)
            self.data_layer = data_layer_class(
                partition_key=self.partition_key, **kwargs
            )
        else:
            raise ValueError(f"Unsupported storage type: {storage_type}")

    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.data_layer.save(
            identifier=identifier,
            data_type=data_type,
            data=data,
            data_file_path=data_file_path,
            data_format=data_format,
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
        path = self.data_layer.save_chunk(
            identifier=identifier,
            data_type=data_type,
            data=data,
            data_file_path=data_file_path,
            data_format=data_format,
            chunk_id=chunk_id,
        )
        return str(path)

    def finalize_save(
        self,
        identifier,
        data_type,
        data_format="tif",
        data_file_path=None,
        total_chunks=None,
    ):
        return self.data_layer.finalize_save(
            identifier=identifier,
            data_type=data_type,
            data_format=data_format,
            data_file_path=data_file_path,
            total_chunks=total_chunks,
        )

    def update(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.data_layer.update(
            identifier=identifier,
            data_type=data_type,
            data=data,
            data_file_path=data_file_path,
            data_format=data_format,
        )

    def load(self, identifier, data_type, data_format="json"):
        return self.data_layer.load(
            identifier, data_type, data_format=data_format
        )

    def load_strict(
        self, identifier: str, data_type: str, data_format: str = "json"
    ) -> Any:
        from .azure_blob_storage_data_layer import AzureBlobStorageDataLayer

        if isinstance(self.data_layer, AzureBlobStorageDataLayer):
            return self.data_layer.load(
                identifier, data_type, data_format=data_format, strict=True
            )
        return self.data_layer.load(
            identifier, data_type, data_format=data_format
        )

    def load_all(self, data_type, data_format="json"):
        return self.data_layer.load_all(data_type, data_format=data_format)

    def load_all_from_partition(self, data_type, data_format="json"):
        return self.data_layer.load_all_from_partition(
            data_type, data_format=data_format
        )

    def load_bounded(self, data_type, max_records, data_format="json"):
        return self.data_layer.load_bounded(
            data_type=data_type,
            max_records=max_records,
            data_format=data_format,
        )

    def load_page(
        self,
        data_type,
        page,
        page_size,
        data_format="json",
        target=None,
        status=None,
        project_id=None,
        max_records=None,
    ):
        return self.data_layer.load_page(
            data_type=data_type,
            page=page,
            page_size=page_size,
            data_format=data_format,
            target=target,
            status=status,
            project_id=project_id,
            max_records=max_records,
        )

    def delete(self, identifier, data_type, data_format="json"):
        self.data_layer.delete(identifier, data_type, data_format=data_format)

    def delete_all_from_partition(self):
        self.data_layer.delete_all_from_partition()

    # These two methods will not work for all storage types
    # NOTE: Figure out how to handle special cases where some training/inference config
    # needs to be passed as a file
    def get_file_path(
        self,
        identifier,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        return self.data_layer.get_file_path(
            identifier,
            data_type,
            data_format=data_format,
            extra_partition_keys=extra_partition_keys,
        )

    def get_file_remote_path(
        self,
        identifier=None,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        return self.data_layer.get_file_remote_path(
            identifier,
            data_type,
            data_format=data_format,
            extra_partition_keys=extra_partition_keys,
        )

    def get_base_url(self):
        return self.data_layer.get_base_url()
