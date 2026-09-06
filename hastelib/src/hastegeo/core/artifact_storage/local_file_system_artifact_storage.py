# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from hastegeo.core.utils.logs import Logger

from .abstract_artifact_storage import AbstractArtifactStorage


class LocalFileSystemArtifactStorage(AbstractArtifactStorage):
    def __init__(self, partition_key=None, **kwargs):
        super().__init__(partition_key)
        self.logger = Logger.get_logger(__name__)
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
        if src_path is None and data is None:
            raise ValueError(
                "Either src_path or data must be provided to store the artifact."
            )

        if src_path is not None and not os.path.exists(src_path):
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
            if src_path is not None:
                # Handle file/directory copying
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)  # Remove existing directory
                    shutil.copytree(src_path, dst_path)
                    self.logger.info(
                        f"Copied directory '{src_path}' to '{dst_path}'"
                    )
                else:
                    shutil.copy2(src_path, dst_path)
                    self.logger.info(
                        f"Copied file '{src_path}' to '{dst_path}'"
                    )
            else:
                with open(dst_path, "w", encoding="utf-8") as file:
                    if isinstance(data, str):
                        file.write(data)
                    else:
                        json.dump(data, file)
                self.logger.info(f"Wrote data to file '{dst_path}'")

            return dst_path

        except Exception as e:
            self.logger.error(f"Failed to store artifact at '{dst_path}': {e}")
            raise

    def get_base_url(self):
        return self.directory

    def resolve_artifact_path(self, location: str) -> str:
        parsed = urlparse(location)
        raw_path = (
            unquote(parsed.path) if parsed.scheme == "file" else location
        )
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = Path(self.directory, candidate)
        resolved = candidate.resolve()
        root = Path(self.directory).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(
                "Artifact path escapes the configured storage root"
            )
        return str(resolved.relative_to(root))

    def copy_artifact(
        self,
        source_path: str,
        destination_path: str,
        source_etag: str,
    ) -> str:
        source_relative = self.resolve_artifact_path(source_path)
        destination_relative = self.resolve_artifact_path(destination_path)
        source = Path(self.directory, source_relative)
        destination = Path(self.directory, destination_relative)
        if not source.is_file():
            raise FileNotFoundError(source_path)
        if self.get_artifact_etag(source_relative) != source_etag:
            raise RuntimeError("Source artifact changed before copy")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        try:
            shutil.copy2(source, temporary_path)
            if self._hash_file(temporary_path) != source_etag:
                raise RuntimeError("Source artifact changed during copy")
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        return destination_relative

    def delete_prefix(self, prefix: str) -> int:
        relative_prefix = self.resolve_artifact_path(prefix)
        target = Path(self.directory, relative_prefix)
        if target.is_file():
            target.unlink()
            return 1
        if not target.exists():
            return 0
        deleted = sum(1 for path in target.rglob("*") if path.is_file())
        shutil.rmtree(target)
        return deleted

    def artifact_exists(self, artifact_path: str) -> bool:
        relative_path = self.resolve_artifact_path(artifact_path)
        return Path(self.directory, relative_path).is_file()

    def get_artifact_size(self, artifact_path: str) -> int:
        relative_path = self.resolve_artifact_path(artifact_path)
        path = Path(self.directory, relative_path)
        if not path.is_file():
            raise FileNotFoundError(artifact_path)
        return path.stat().st_size

    def read_artifact_bytes(self, artifact_path: str, max_bytes: int) -> bytes:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        relative_path = self.resolve_artifact_path(artifact_path)
        path = Path(self.directory, relative_path)
        with path.open("rb") as source:
            data = source.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Artifact exceeds the download limit")
        return data

    def get_artifact_etag(self, artifact_path: str) -> str:
        relative_path = self.resolve_artifact_path(artifact_path)
        path = Path(self.directory, relative_path)
        if not path.is_file():
            raise FileNotFoundError(artifact_path)
        return self._hash_file(path)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def get_scoped_download_url(
        self, artifact_path: str, expires_minutes: int = 15
    ) -> str:
        relative_path = self.resolve_artifact_path(artifact_path)
        if not self.artifact_exists(relative_path):
            raise FileNotFoundError(artifact_path)
        return Path(self.directory, relative_path).resolve().as_uri()
