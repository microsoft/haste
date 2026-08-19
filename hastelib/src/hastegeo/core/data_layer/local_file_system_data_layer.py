# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
import shutil

import yaml

from .abstract_data_layer import AbstractDataLayer


class LocalFileSystemDataLayer(AbstractDataLayer):
    """Local filesystem implementation of the AbstractDataLayer.

    This class provides data storage and retrieval operations using the local
    filesystem. Data is organized in directories based on partition keys and
    data types, with files named according to their identifiers and formats.

    Args:
        directory (str): Base directory for data storage.
        partition_key (str, optional): Key for data partitioning.
            Defaults to None.

    Attributes:
        directory (str): The resolved absolute path to the storage directory.

    Example:
        >>> data_layer = LocalFileSystemDataLayer("/data", "project_123")
        >>> data_layer.save("model_1", "models", {"accuracy": 0.95})
        >>> model_data = data_layer.load("model_1", "models")
    """

    def __init__(self, directory, partition_key=None):
        """Initialize the local filesystem data layer.

        Args:
            directory (str): Base directory for data storage.
            partition_key (str, optional): Key for data partitioning.
                Creates a subdirectory for organization. Defaults to None.
        """
        super().__init__(partition_key)
        if partition_key is None:
            partition_key = ""
        directory = os.path.join(directory, partition_key)
        if directory and not os.path.isabs(directory):
            directory = os.path.abspath(directory)
        if not directory or not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        self.directory = directory

    def get_file_path(
        self,
        identifier,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        """Generate the full file path for a data record.

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str, optional): Type/category of the data.
                Defaults to None.
            data_format (str, optional): File format extension.
                Defaults to "json".
            extra_partition_keys (Union[str, List[str]], optional): Additional
                partition keys for nested directory structure. Defaults to None.

        Returns:
            str: Complete file path for the data record.

        Example:
            >>> layer.get_file_path("model_1", "models", "json", ["v1", "test"])
            "/data/project_123/v1/test/models_model_1.json"
        """
        partition_keys = []
        if extra_partition_keys and isinstance(extra_partition_keys, list):
            partition_keys += extra_partition_keys
        if extra_partition_keys and isinstance(extra_partition_keys, str):
            partition_keys.append(extra_partition_keys)
        if identifier.endswith("." + data_format):
            filename = f"{data_type}_{identifier}"
        else:
            filename = f"{data_type}_{identifier}.{data_format}"
        return os.path.join(self.directory, *partition_keys, filename)

    def get_file_remote_path(
        self,
        identifier=None,
        data_type=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        """Get the remote path for a file (same as local path for filesystem layer).

        This method provides compatibility with cloud storage implementations
        where remote and local paths may differ. For local filesystem storage,
        it returns the same result as get_file_path().

        Args:
            identifier (str, optional): Unique identifier for the data record.
                Defaults to None.
            data_type (str, optional): Type/category of the data.
                Defaults to None.
            data_format (str, optional): File format extension.
                Defaults to "json".
            extra_partition_keys (Union[str, List[str]], optional): Additional
                partition keys. Defaults to None.

        Returns:
            str: Complete file path (same as local path for filesystem storage).
        """
        return self.get_file_path(
            identifier, data_type, data_format, extra_partition_keys
        )

    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        """Save data to the local filesystem.

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str): Type/category of the data being saved.
            data (Any, optional): Data object to save. Defaults to None.
            data_file_path (str, optional): Path to source file to copy.
                Defaults to None.
            data_format (str, optional): Format of the data (json, tif, etc.).
                Defaults to "json".

        Raises:
            ValueError: If data format is unsupported or if data input validation fails.

        Note:
            If data_file_path is provided, the source file will be copied to the
            destination and the original file will be removed. For data objects,
            JSON data is serialized and bytes data is written directly.
        """
        self.validate_data_input(data, data_file_path)

        dst_file_path = self.get_file_path(
            identifier=identifier, data_type=data_type, data_format=data_format
        )

        dir_path = os.path.dirname(dst_file_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

        if data_file_path:
            shutil.copy(data_file_path, dst_file_path)
            try:
                os.remove(data_file_path)
            except (OSError, FileNotFoundError):
                pass
        else:
            if self.is_bytes(data):
                with open(dst_file_path, "wb") as file:
                    file.write(data)
            elif self.is_json(data):
                with open(dst_file_path, "w") as file:
                    json.dump(data, file)
            else:
                raise ValueError(
                    f"{self.__class__.__name__}.save: Unsupported data format. Only json and bytes are supported."
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
        """Save a chunk of data (not implemented for local filesystem).

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

        Raises:
            NotImplementedError: This method is not implemented for local
                filesystem storage as chunked uploads are not necessary
                for local operations.

        Note:
            For local filesystem operations, use the regular save() method
            instead as chunked uploads are not required.
        """
        # NOTE: Implement for OSS
        raise NotImplementedError(
            "Method not implemented for local file system data layer."
        )

    def finalize_save(
        self,
        identifier,
        data_type,
        data_format="tif",
        data_file_path=None,
        total_chunks=None,
    ):
        """Finalize a chunked upload (not implemented for local filesystem).

        Args:
            identifier (str): Unique identifier for the data record.
            data_type (str): Type/category of the data being saved.
            data_format (str, optional): Format of the data (tif, etc.).
                Defaults to "tif".
            data_file_path (str, optional): Final path for the combined file.
                Defaults to None.
            total_chunks (int, optional): Expected total number of chunks.
                Defaults to None.

        Raises:
            NotImplementedError: This method is not implemented for local
                filesystem storage as chunked uploads are not necessary
                for local operations.
        """
        # NOTE: Implement for OSS
        raise NotImplementedError(
            "Method not implemented for local file system data layer."
        )

    def update(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.save(
            identifier=identifier,
            data_type=data_type,
            data=data,
            data_file_path=data_file_path,
            data_format=data_format,
        )

    def load(self, identifier, data_type, data_format="json"):
        file_path = self.get_file_path(
            identifier, data_type, data_format=data_format
        )
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"{self.__class__.__name__}.load: No data found for identifier: {identifier} and data_type: {data_type}"
            )
        with open(file_path, "r") as file:
            content = file.read()
            if data_format == "json":
                return json.loads(content)
            elif data_format == "yaml":
                return yaml.safe_load(content)
            else:
                raise ValueError(f"Unsupported data_format: {data_format}")

    def load_all(self, data_type, data_format="json"):
        data = []
        for file_name in os.listdir(self.directory):
            if file_name.startswith(f"{data_type}_") and file_name.endswith(
                f".{data_format}"
            ):
                with open(
                    os.path.join(self.directory, file_name), "r"
                ) as file:
                    if data_format == "json":
                        data.append(json.load(file))
                    elif data_format == "yaml":
                        data.append(yaml.safe_load(file))
                    else:
                        raise ValueError(
                            f"Unsupported data_format: {data_format}"
                        )
        return data

    def load_all_from_partition(self, data_type, data_format="json"):
        data = self.load_all(data_type=data_type, data_format=data_format)
        return data

    def load_bounded(self, data_type, max_records, data_format="json"):
        if max_records < 1 or data_format not in {"json", "yaml"}:
            raise ValueError("Invalid bounded local metadata read")
        records = []
        scanned_paths = 0
        scan_limit = max_records * 10
        directories = [self.directory]
        with os.scandir(self.directory) as root_entries:
            for entry in root_entries:
                scanned_paths += 1
                if scanned_paths > scan_limit:
                    raise ValueError(
                        "Metadata scan exceeds the bounded envelope"
                    )
                if entry.is_dir(follow_symlinks=False):
                    directories.append(entry.path)

        for directory in directories:
            with os.scandir(directory) as entries:
                for entry in entries:
                    scanned_paths += 1
                    if scanned_paths > scan_limit:
                        raise ValueError(
                            "Metadata scan exceeds the bounded envelope"
                        )
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if not entry.name.startswith(f"{data_type}_") or not entry.name.endswith(
                        f".{data_format}"
                    ):
                        continue
                    with open(entry.path, "r") as file:
                        records.append(
                            json.load(file)
                            if data_format == "json"
                            else yaml.safe_load(file)
                        )
                    if len(records) > max_records:
                        raise ValueError(
                            f"Metadata exceeds the {max_records:,}-record limit"
                        )
        return records

    def delete(self, identifier, data_type, data_format="json"):
        file_path = self.get_file_path(identifier, data_type, data_format)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"{self.__class__.__name__}.delete: No data found for identifier: {identifier} and data_type: {data_type}"
            )
        os.remove(file_path)

    def delete_all_from_partition(self):
        if os.path.exists(self.directory):
            shutil.rmtree(self.directory)
        else:
            raise FileNotFoundError(
                f"{self.__class__.__name__}.delete_all_from_partition: No data found for partition_key: {self.partition_key}"
            )
