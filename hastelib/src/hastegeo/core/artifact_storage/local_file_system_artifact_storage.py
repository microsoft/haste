# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
import shutil

from .abstract_artifact_storage import AbstractArtifactStorage


class LocalFileSystemArtifactStorage(AbstractArtifactStorage):
    def __init__(self, partition_key=None, **kwargs):
        super().__init__(partition_key)
        if partition_key is None:
            partition_key = ""
        directory = os.path.join(kwargs.pop("directory"), partition_key)
        if directory and not os.path.isabs(directory):
            directory = os.path.abspath(directory)
        if not directory or not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        self.directory = directory

    def get_file_path(
        self, identifier: str, extra_partition_keys: list | str = None
    ) -> str:
        partition_keys = []
        if extra_partition_keys and isinstance(extra_partition_keys, list):
            partition_keys += extra_partition_keys
        if extra_partition_keys and isinstance(extra_partition_keys, str):
            partition_keys.append(extra_partition_keys)
        return os.path.join(self.directory, *partition_keys, identifier)

    def get_download_url(
        self,
        identifier=None,
        artifact_path=None,
        extra_partition_keys=None,
    ):
        if artifact_path:
            return f"file://{artifact_path}"
        else:
            return f"file://{self.get_file_path(identifier, extra_partition_keys)}"

    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        """
        Download the artifact from the source path to the destination path.
        """
        if identifier:
            src_path = self.get_file_path(
                identifier, extra_partition_keys=extra_partition_keys
            )
        if not os.path.exists(src_path):
            raise FileNotFoundError(f"Source path {src_path} does not exist.")
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)
        return dst_path

    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        """Store the artifact in the local file system.

        Args:
            artifact_name (str): The name of the artifact in the local file system.
            data (str): Optional. The data to write as a string.
            src_path (str): Optional. The source path of the file to copy.
                Either data or src_path must be provided.
            namespace (str | list): The namespace aka folder structure to use for the artifact.

        Returns:
            str: The local path where the artifact was stored.

        Raises:
            ValueError: If neither src_path nor data is provided.
            FileNotFoundError: If src_path is provided but doesn't exist.
        """
        # Validate inputs early
        if not src_path and not data:
            raise ValueError(
                "Either src_path or data must be provided to store the artifact."
            )

        if src_path and not os.path.exists(src_path):
            raise FileNotFoundError(f"Source path {src_path} does not exist.")

        # Get destination path
        dst_path = self.get_file_path(
            artifact_name, extra_partition_keys=namespace
        )

        # Ensure destination directory exists
        dst_dir = os.path.dirname(dst_path)
        if dst_dir:
            os.makedirs(dst_dir, exist_ok=True)

        try:
            if src_path:
                # Handle file/directory copying
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)  # Remove existing directory
                    shutil.copytree(src_path, dst_path)
                    print(f"Copied directory '{src_path}' to '{dst_path}'")
                else:
                    shutil.copy2(src_path, dst_path)
                    print(f"Copied file '{src_path}' to '{dst_path}'")
            else:
                # Handle string data writing
                with open(dst_path, "w", encoding="utf-8") as file:
                    file.write(data)
                print(f"Wrote data to file '{dst_path}'")

            return dst_path

        except Exception as e:
            print(f"Failed to store artifact at '{dst_path}': {e}")
            raise

    def get_base_url(self):
        return self.directory
