# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config

from ..data_layer.unified import UnifiedDataLayer
from ..utils.perf import timed


class MetadataProcessor:
    """Processor for managing metadata storage and retrieval operations.

    The MetadataProcessor provides a high-level interface for working with
    metadata in various storage backends. It handles data serialization,
    storage operations, and provides convenient methods for common metadata
    operations like saving, loading, and listing records.

    Args:
        data_type (str): Type of metadata being processed (e.g., 'project',
            'model', 'labels').
        partition_key (str, optional): Partition key for data organization.
            Defaults to None.
        config (Config, optional): Configuration instance. If None, creates
            a new Config instance. Defaults to None.

    Attributes:
        storage (UnifiedDataLayer): Underlying storage layer instance.
        data_type (str): The metadata type this processor handles.

    Example:
        >>> processor = MetadataProcessor('project', 'user_123')
        >>> processor.save('project_1', {'name': 'My Project'})
        >>> project = processor.load('project_1')
    """

    def __init__(
        self, data_type: str, partition_key: str = None, config: Config = None
    ):
        """Initialize the metadata processor.

        Args:
            data_type (str): Type of metadata being processed.
            partition_key (str, optional): Partition key for data organization.
                Defaults to None.
            config (Config, optional): Configuration instance. Defaults to None.
        """
        if config is None:
            config = Config()
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=partition_key,
            **config.storage_config,
        )
        self.data_type = data_type

    def save(self, key, metadata, data_format="json"):
        """Save or upsert metadata to the backend storage.

        This method performs an upsert operation - if metadata with the given
        key already exists, it will be updated; otherwise, new metadata will
        be created.

        Args:
            key (str): Unique identifier for the metadata record.
            metadata (dict): Metadata object to save.
            data_format (str, optional): Format for data serialization.
                Defaults to "json".

        Example:
            >>> processor.save('project_1', {'name': 'My Project', 'status': 'active'})
        """
        try:
            existing_metadata = self.load(key, data_format=data_format)
        except FileNotFoundError:
            existing_metadata = None

        if existing_metadata:
            combined_metadata = self._combine_metadata(
                existing_metadata, metadata
            )
            self.storage.save(
                identifier=key,
                data=combined_metadata,
                data_type=self.data_type,
                data_format=data_format,
            )
        else:
            self.storage.save(
                identifier=key,
                data=metadata,
                data_type=self.data_type,
                data_format=data_format,
            )

    def load(self, key, data_format="json"):
        """
        Load metadata from the backend storage.
        """
        with timed("load"):
            metadata = self.storage.load(
                identifier=key,
                data_type=self.data_type,
                data_format=data_format,
            )
        return metadata

    def load_all(self, data_format="json"):
        """
        Load all metadata from the backend storage.
        """
        metadata = []
        with timed("load_all"):
            metadata_list = self.storage.load_all(
                data_type=self.data_type, data_format=data_format
            )
        for each_metadata in metadata_list:
            metadata.append(each_metadata)
        return metadata

    def load_all_from_partition(self, data_format="json"):
        """
        Load all metadata from the backend storage.
        """
        metadata = []
        with timed("load_all_from_partition"):
            metadata_list = self.storage.load_all_from_partition(
                data_type=self.data_type, data_format=data_format
            )
        for each_metadata in metadata_list:
            metadata.append(each_metadata)
        return metadata

    def load_bounded(
        self, max_records: int, data_format: str = "json"
    ) -> list[dict]:
        return self.storage.load_bounded(
            data_type=self.data_type,
            max_records=max_records,
            data_format=data_format,
        )

    def load_page(
        self,
        page: int,
        page_size: int,
        data_format: str = "json",
        target: str = None,
        status: str = None,
        project_id: str = None,
        max_records: int = None,
    ) -> tuple[list[dict], int]:
        return self.storage.load_page(
            data_type=self.data_type,
            page=page,
            page_size=page_size,
            data_format=data_format,
            target=target,
            status=status,
            project_id=project_id,
            max_records=max_records,
        )

    def load_and_combine_sub_data_types(self, key, data_types):
        """
        Load and combine metadata from multiple data types.
        """
        combined_metadata = self.load(key) or {}
        data_types = list(set(data_types) - {self.data_type})

        for data_type in data_types:
            try:
                metadata = self.storage.load_all(data_type=data_type)

            except FileNotFoundError:
                metadata = None
            if metadata:
                combined_metadata[data_type] = [
                    json.loads(item) for item in metadata
                ]
                combined_metadata[f"{data_type}Count"] = len(
                    combined_metadata[data_type]
                )

        return combined_metadata

    def delete(self, key, data_format="json"):
        """
        Delete metadata from the backend storage.
        """
        self.storage.delete(
            identifier=key, data_type=self.data_type, data_format=data_format
        )

    def delete_all_from_partition(self):
        """
        Delete all metadata from the backend storage.
        """
        self.storage.delete_all_from_partition()

    def _combine_metadata(self, existing_metadata, new_metadata):
        """
        Combine existing metadata with new metadata.
        """
        if isinstance(existing_metadata, dict) and isinstance(
            new_metadata, dict
        ):
            combined_metadata = existing_metadata.copy()
            combined_metadata.update(new_metadata)
            return combined_metadata
        elif isinstance(existing_metadata, list) and isinstance(
            new_metadata, list
        ):
            return new_metadata  # Do not update if both are lists
        else:
            raise ValueError(
                "Both existing metadata and new metadata should be dictionaries."
            )

    def export(self, key, data_format="json"):
        """
        Export metadata to a file in the specified format.

        Args:
            key (str): Unique identifier for the metadata record.
            data_format (str, optional): Format for data serialization.
                Defaults to "json".

        Returns:
            str: File path where the metadata is exported.
        """
        # NOTE: This is a quick method to make the export work for Azure blob storage layer.
        # Rework needed to handle different storage types and formats properly.
        with timed("export"):
            return self.storage.get_file_remote_path(
                identifier=key,
                data_type=self.data_type,
                data_format=data_format,
            )
