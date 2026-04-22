# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from abc import ABC, abstractmethod

import yaml


class AbstractArtifactStorage(ABC):
    def __init__(self, partition_key=None):
        self.partition_key = partition_key

    @abstractmethod
    def get_file_path(
        self, identifier: str, extra_partition_keys: list | str = None
    ) -> str:
        pass

    @abstractmethod
    def get_download_url(
        self,
        identifier: str = None,
        artifact_path=None,
        extra_partition_keys=None,
    ):
        pass

    @abstractmethod
    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        pass

    @abstractmethod
    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        pass

    @abstractmethod
    def get_base_url(self):
        pass

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
