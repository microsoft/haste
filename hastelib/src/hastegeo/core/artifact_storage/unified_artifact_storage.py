# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import importlib
import os

from ..utils.metadata import MetadataUtils


class UnifiedArtifactStorage:
    def __init__(self, storage_type, partition_key=None, **kwargs):
        if partition_key:
            self.partition_key = MetadataUtils.hash_string(partition_key)
        else:
            self.partition_key = None

        # Dictionary to map storage types to their respective modules and class names
        storage_class_map = {
            "local": (
                "local_file_system_artifact_storage",
                "LocalFileSystemArtifactStorage",
            ),
            "blob": (
                "azure_blob_artifact_storage",
                "AzureBlobArtifactStorage",
            ),
        }

        if storage_type in storage_class_map:
            module_name, class_name = storage_class_map[storage_type]
            module = importlib.import_module(f"{__package__}.{module_name}")
            artifact_storage_class = getattr(module, class_name)
            self.artifact_storage = artifact_storage_class(
                partition_key=self.partition_key, **kwargs
            )
        else:
            raise ValueError(f"Unsupported storage type: {storage_type}")

    def get_file_path(
        self, identifier: str, extra_partition_keys: list | str = None
    ) -> str:
        """
        Get the file path for the artifact.
        """
        return self.artifact_storage.get_file_path(
            identifier=identifier, extra_partition_keys=extra_partition_keys
        )

    def get_download_url(
        self,
        identifier=None,
        artifact_path=None,
        extra_partition_keys=None,
    ):
        """
        Get the download URL for the artifact.
        """
        if not identifier and not artifact_path:
            raise ValueError(
                f"{self.__class__.__name__}.get_file_remote_path: Either identifier or url must be provided."
            )
        if identifier and artifact_path:
            raise ValueError(
                f"{self.__class__.__name__}.get_file_remote_path: Either identifier or url must be provided, not both."
            )
        return self.artifact_storage.get_download_url(
            identifier=identifier,
            artifact_path=artifact_path,
            extra_partition_keys=extra_partition_keys,
        )

    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        """
        Download the artifact from the storage.
        """
        dst_path = dst_path or "."
        # Ensure the download path exists
        if not os.path.exists(dst_path):
            os.makedirs(dst_path)

        if not identifier and not src_path:
            raise ValueError(
                f"{self.__class__.__name__}.download: Either identifier or src_path must be provided."
            )
        if identifier and src_path:
            raise ValueError(
                f"{self.__class__.__name__}.download: Either identifier or src_path must be provided, not both."
            )

        return self.artifact_storage.fetch_artifact(
            identifier=identifier,
            extra_partition_keys=extra_partition_keys,
            src_path=src_path,
            dst_path=dst_path,
        )

    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        """
        Store the artifact in storage.

        Args:
            artifact_name (str): The name of the artifact in storage.
            data (str): Optional. The data to write as a string.
            src_path (str): Optional. The source path of the file to copy/upload.
                Either data or src_path must be provided.
            namespace (str | list): The namespace aka folder structure to use for the artifact.

        Returns:
            str: The path where the artifact was stored.

        Raises:
            ValueError: If neither src_path nor data is provided.
            FileNotFoundError: If src_path is provided but doesn't exist.
        """
        # Validate inputs early - delegate to the underlying storage implementation
        # which already has proper validation
        return self.artifact_storage.store_artifact(
            artifact_name=artifact_name,
            data=data,
            src_path=src_path,
            namespace=namespace,
        )

    def get_base_url(self):
        return self.artifact_storage.get_base_url()
