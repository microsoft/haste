# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
from abc import ABC, abstractmethod

import yaml


class AbstractDataLayer(ABC):
    """Abstract base class for data layer implementations.

    The AbstractDataLayer defines the interface for data storage and retrieval
    operations across different storage backends (local filesystem, Azure Blob,
    Azure Cosmos DB, etc.). All concrete data layer implementations must
    inherit from this class and implement its abstract methods.

    Args:
        partition_key (str, optional): Key used for data partitioning.
            Defaults to None.

    Attributes:
        partition_key (str): The partition key for organizing data.
    """

    def __init__(self, partition_key=None):
        """Initialize the abstract data layer.

        Args:
            partition_key (str, optional): Key used for data partitioning.
                Defaults to None.
        """
        self.partition_key = partition_key

    @abstractmethod
    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        """Save data to the storage backend.

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str): Type/category of the data being saved.
            data (Any, optional): Data object to save. Defaults to None.
            data_file_path (str, optional): Path to file containing data.
                Defaults to None.
            data_format (str, optional): Format of the data (json, tif, etc.).
                Defaults to "json".

        Note:
            Either `data` or `data_file_path` must be provided, but not both.
        """
        pass

    @abstractmethod
    def save_chunk(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="tif",
        chunk_id=None,
    ):
        """Save a chunk of data as part of a chunked upload operation.

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str): Type/category of the data being saved.
            data (Any, optional): Data chunk to save. Defaults to None.
            data_file_path (str, optional): Path to file containing data chunk.
                Defaults to None.
            data_format (str, optional): Format of the data (tif, etc.).
                Defaults to "tif".
            chunk_id (str, optional): Unique identifier for this chunk.
                Defaults to None.

        Note:
            This method is used for uploading large files in smaller chunks.
            Must be followed by finalize_save() to complete the operation.
        """
        pass

    @abstractmethod
    def finalize_save(
        self,
        identifier,
        data_type,
        data_format="tif",
        data_file_path=None,
        total_chunks=None,
    ):
        """Finalize a chunked upload operation by combining all chunks.

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str): Type/category of the data being saved.
            data_format (str, optional): Format of the data (tif, etc.).
                Defaults to "tif".
            data_file_path (str, optional): Final path for the combined file.
                Defaults to None.
            total_chunks (int, optional): Expected total number of chunks.
                Defaults to None.

        Note:
            This method completes a chunked upload operation started with
            save_chunk() calls.
        """
        pass

    @abstractmethod
    def update(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        """Update existing data in the storage backend.

        Args:
            identifier (str): Unique identifier for the data record to update.
            data_type (str): Type/category of the data being updated.
            data (Any, optional): New data object. Defaults to None.
            data_file_path (str, optional): Path to file containing new data.
                Defaults to None.
            data_format (str, optional): Format of the data (json, tif, etc.).
                Defaults to "json".

        Note:
            Either `data` or `data_file_path` must be provided, but not both.
        """
        pass

    @abstractmethod
    def load(self, identifier, data_type, data_format="json"):
        """Load data from the storage backend.

        Args:
            identifier (str): Unique identifier for the data record to load.
            data_type (str): Type/category of the data being loaded.
            data_format (str, optional): Expected format of the data.
                Defaults to "json".

        Returns:
            Any: The loaded data object or bytes depending on format.

        Raises:
            FileNotFoundError: If the specified data record doesn't exist.
        """
        pass

    @abstractmethod
    def load_all(self, data_type, data_format="json"):
        """Load all data records of a specific type.

        Args:
            data_type (str): Type/category of the data to load.
            data_format (str, optional): Expected format of the data.
                Defaults to "json".

        Returns:
            List[Any]: List of all data records of the specified type.
        """
        pass

    @abstractmethod
    def load_all_from_partition(self, data_type, data_format="json"):
        """Load all data records of a specific type from the current partition.

        Args:
            data_type (str): Type/category of the data to load.
            data_format (str, optional): Expected format of the data.
                Defaults to "json".

        Returns:
            List[Any]: List of all data records of the specified type
                from the current partition.
        """
        pass

    def load_bounded(self, data_type, max_records, data_format="json"):
        """Load no more than ``max_records`` or fail before full materialization."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support bounded reads"
        )

    def load_map(
        self,
        identifiers,
        data_type,
        data_format="json",
        max_workers=None,
    ):
        """Load keyed records in one backend-native operation when supported."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement batch reads"
        )

    def list_identifiers(self, data_type, data_format="json"):
        """List the identifiers of records of a type in the current partition.

        Unlike :meth:`load_all_from_partition`, this returns only the keys and
        does not download record contents — a cheap way to test existence in
        bulk. Not abstract so existing backends keep working; concrete backends
        that support cheap listing (blob, local filesystem) override it.

        Args:
            data_type (str): Type/category of the data to list.
            data_format (str, optional): File format of the records. Defaults
                to "json".

        Returns:
            List[str]: Identifiers present in the current partition.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement list_identifiers"
        )

    def get_file_remote_path(
        self,
        identifier=None,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
        check_exists=True,
    ):
        """Build a remotely accessible path when the backend supports one."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not expose remote file paths"
        )

    @abstractmethod
    def delete(self, identifier, data_type, data_format="json"):
        """Delete a specific data record from the storage backend.

        Args:
            identifier (str): Unique identifier for the data record to delete.
            data_type (str): Type/category of the data being deleted.
            data_format (str, optional): Format of the data.
                Defaults to "json".

        Raises:
            FileNotFoundError: If the specified data record doesn't exist.
        """
        pass

    @abstractmethod
    def delete_all_from_partition(self):
        """Delete all data records from the current partition.

        Warning:
            This operation is irreversible and will remove all data
            from the current partition.
        """
        pass

    def load_data_from_file(self, data_file_path):
        """Load data from a file based on its extension.

        Args:
            data_file_path (str): Path to the file containing data to load.

        Returns:
            Any: Parsed data object for JSON files, or raw bytes for
                image/binary files.

        Raises:
            ValueError: If the file format is not supported.

        Supported formats:
            - .json: Returns parsed JSON object
            - .tif/.tiff: Returns raw bytes
            - .jpeg/.jpg: Returns raw bytes
            - .png: Returns raw bytes
        """
        if data_file_path.endswith(".json"):
            with open(data_file_path, "r") as file:
                return json.load(file)
        elif (
            data_file_path.endswith(".tif")
            or data_file_path.endswith(".tiff")
            or data_file_path.endswith(".jpeg")
            or data_file_path.endswith(".png")
        ):
            with open(data_file_path, "rb") as f:
                return f.read()
        else:
            raise ValueError(
                "Unsupported file format. Only .json, .tif, .png and .jpeg are supported."
            )

    def validate_data_input(self, data, data_file_path):
        """Validate that exactly one data input method is provided.

        Args:
            data (Any): Data object to validate.
            data_file_path (str): File path to validate.

        Returns:
            bool: True if validation passes.

        Raises:
            ValueError: If neither or both data inputs are provided.
        """
        if data is None and data_file_path is None:
            raise ValueError(
                "Either 'data' or 'data_file_path' must be provided."
            )
        if data is not None and data_file_path is not None:
            raise ValueError(
                "Only one of 'data' or 'data_file_path' should be provided."
            )
        return True

    def is_json(self, data):
        """Check if data can be serialized as JSON.

        Args:
            data (Any): Data to check for JSON compatibility.

        Returns:
            bool: True if data is JSON-serializable, False otherwise.
        """
        try:
            json.dumps(data)
            return True
        except (TypeError, ValueError):
            return False

    def is_bytes(self, data):
        """Check if data is a bytes object.

        Args:
            data (Any): Data to check.

        Returns:
            bool: True if data is bytes, False otherwise.
        """
        return isinstance(data, bytes)

    def is_yaml(self, data):
        """Check if data can be serialized as YAML.

        Args:
            data (Any): Data to check for YAML compatibility.

        Returns:
            bool: True if data is YAML-serializable, False otherwise.
        """
        try:
            yaml.dump(data)
            return True
        except (TypeError, ValueError):
            return False
