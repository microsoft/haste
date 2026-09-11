# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import PurePosixPath
from threading import Lock
from urllib.parse import unquote, urlparse

import yaml
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobClient  # type: ignore
from azure.storage.blob import (
    AccessPolicy,
    BlobSasPermissions,
    ContainerSasPermissions,
    generate_blob_sas,
    generate_container_sas,
)
from hastegeo.core.utils.blob import (
    get_blob_service_client,
    get_cached_user_delegation_key,
)
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.parallel import configured_worker_count, parallel_map

from .abstract_artifact_storage import AbstractArtifactStorage

_INITIALIZED_CONTAINERS = set()
_INITIALIZED_CONTAINERS_LOCK = Lock()


class AzureBlobArtifactStorage(AbstractArtifactStorage):
    def __init__(
        self,
        account_url,
        container,
        connection_string,
        container_read_policy_name="image-r-policy",
        blob_read_policy_name="imageblob-r-policy",
        partition_key=None,
        serves_read_sas=True,
    ):
        super().__init__(partition_key)
        self.logger = Logger.get_logger(__name__)
        # A write-only target (e.g. the PC publish container) doesn't mint read
        # SAS, so it skips the user-delegation key and the stored read policy —
        # which need Storage Blob Delegator / Owner. Write access alone suffices.
        self.serves_read_sas = serves_read_sas
        if connection_string:
            self.blob_service_client = get_blob_service_client(
                connection_string=connection_string
            )
            self.user_delegation_key = None
            self.account_key = self.blob_service_client.credential.account_key
            self.identity_blob_service_client = (
                get_blob_service_client(account_url=account_url)
                if account_url and urlparse(account_url).scheme == "https"
                else None
            )
        else:
            self.blob_service_client = get_blob_service_client(
                account_url=account_url
            )
            self.identity_blob_service_client = self.blob_service_client
            self.user_delegation_key = None
            self.account_key = None

        self.container_read_policy = container_read_policy_name
        self.blob_read_policy = blob_read_policy_name
        self.sas_expiration_days = 90
        self.container_client = self.blob_service_client.get_container_client(
            container
        )
        cache_key = (
            self.blob_service_client.url,
            container,
            self.container_read_policy,
        )
        with _INITIALIZED_CONTAINERS_LOCK:
            if cache_key not in _INITIALIZED_CONTAINERS:
                try:
                    self.container_client.create_container()
                    self.logger.info(
                        f"Container '{container}' created successfully."
                    )
                except ResourceExistsError:
                    self.logger.info(
                        f"Container '{container}' already exists."
                    )
                if self.serves_read_sas:
                    self._create_or_update_managed_access_policy()
                _INITIALIZED_CONTAINERS.add(cache_key)

    def _create_or_update_managed_access_policy(self):
        expiration_date = datetime.now(timezone.utc) + timedelta(
            days=self.sas_expiration_days
        )
        # Check if the policy already exists
        existing_policies = self.container_client.get_container_access_policy()
        if self.container_read_policy in existing_policies.get(
            "signed_identifiers", {}
        ):
            policy = existing_policies["signed_identifiers"][
                self.container_read_policy
            ]
            if policy["expiry"] < datetime.now(timezone.utc):
                # Policy exists but is expired, extend the expiration date
                policy["expiry"] = expiration_date
                self.container_client.set_container_access_policy(
                    signed_identifiers={self.container_read_policy: policy}
                )
        else:
            # Policy does not exist, create a new one
            self.logger.info("Policy does not exist, create a new one")
            read_policy = AccessPolicy(
                permission=ContainerSasPermissions(read=True),
                expiry=expiration_date,
            )
            identifiers = {self.container_read_policy: read_policy}
            self.container_client.set_container_access_policy(
                signed_identifiers=identifiers
            )
            self.logger.info("Policy set")

    def get_file_path(
        self, identifier: str, extra_partition_keys: list | str = None
    ) -> str:
        partition_keys = []
        if self.partition_key:
            partition_keys.append(self.partition_key)
        if extra_partition_keys and isinstance(extra_partition_keys, list):
            partition_keys += extra_partition_keys
        if extra_partition_keys and isinstance(extra_partition_keys, str):
            partition_keys.append(extra_partition_keys)

        return (
            f'{"/".join(partition_keys)}/{identifier}'
            if partition_keys
            else f"{identifier}"
        )

    def get_download_url(
        self,
        identifier=None,
        artifact_path=None,
        extra_partition_keys=None,
        include_sas=True,
    ):
        """Get the remote path for the file in Azure Blob Storage.
        Args:
            identifier (str): The identifier for the file. Mutually exclusive with url.
            artifact_path (str): The path to the artifact relative to storage
                root. Either artifact_path or identifier must be provided.
            extra_partition_keys (list): Extra partition keys to include in the path.
            include_sas (bool): Whether to include a SAS token in the URL.
        Returns:
            str: The full remote path for the file in Azure Blob Storage, optionally with SAS token.
        """

        if artifact_path:
            # Optionally, only store the blobname in the metadata
            # and use the container_client and blob name to get the blob client
            # It's a cleaner separation of metaphors
            blob_client = BlobClient.from_blob_url(artifact_path)
        else:
            blob_name = self.get_file_path(
                identifier, extra_partition_keys=extra_partition_keys
            )
            blob_client = self.container_client.get_blob_client(blob_name)

        if not include_sas:
            return str(blob_client.url)

        # Otherwise generate SAS token

        user_delegation_key = self.user_delegation_key
        if self.account_key is None:
            user_delegation_key = get_cached_user_delegation_key(
                self.blob_service_client
            )

        sas_token = generate_container_sas(
            account_name=self.container_client.account_name,
            container_name=self.container_client.container_name,
            policy_id=self.container_read_policy,
            account_key=self.account_key,
            user_delegation_key=user_delegation_key,
        )
        return str(f"{blob_client.url}?{sas_token}")

    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        """Download the artifact from Azure Blob Storage.
        Args:
            src_path (str): The source path of the file in Azure Blob Storage.
            dst_path (str): The destination path to save the downloaded file.
        """

        if identifier:
            src_path = self.get_file_path(
                identifier, extra_partition_keys=extra_partition_keys
            )
        if not src_path:
            raise ValueError("A source artifact path is required")
        if not dst_path:
            raise ValueError("A destination path is required")
        src_path = self.resolve_artifact_path(src_path)
        blob_names = [
            blob.name
            for blob in self.container_client.list_blobs(
                name_starts_with=src_path
            )
        ]

        def _download_one(blob_name):
            relative_path = self.resolve_artifact_path(blob_name)
            file_path = os.path.join(
                os.path.abspath(dst_path), *PurePosixPath(relative_path).parts
            )
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            blob_client = self.container_client.get_blob_client(blob_name)
            stream = blob_client.download_blob()
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=os.path.dirname(file_path), delete=False
                ) as temp_file:
                    temp_path = temp_file.name
                    for chunk in stream.chunks():
                        temp_file.write(chunk)
                os.replace(temp_path, file_path)
            except Exception:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        if blob_names:
            workers = configured_worker_count(
                "HASTE_ARTIFACT_DOWNLOAD_WORKERS", 8
            )
            parallel_map(_download_one, blob_names, max_workers=workers)

        self.logger.info(f"Downloaded {src_path} to {dst_path}")
        return dst_path

    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        """Upload the artifact to Azure Blob Storage.

        Args:
            artifact_name (str): The name of the artifact in Azure Blob Storage.
            data (str): Optional. The data to upload as a string.
            src_path (str): Optional. The source path of the file to upload.
                Either data or src_path must be provided.
            namespace (str | list): The namespace aka folder structure to use for the artifact.

        Returns:
            str: The blob path where the artifact was stored.

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
        blob_client = self.container_client.get_blob_client(dst_path)

        try:
            if src_path is not None:
                with open(src_path, "rb") as file_data:
                    blob_client.upload_blob(file_data, overwrite=True)
                self.logger.info(
                    f"Uploaded file '{src_path}' to blob '{dst_path}'"
                )
            else:
                # Handle string data upload
                if self.is_bytes(data):
                    blob_client.upload_blob(data, overwrite=True)
                elif self.is_json(data):
                    blob_client.upload_blob(json.dumps(data), overwrite=True)
                elif self.is_yaml(data):
                    self.logger.info("data is yaml, dumping to blob")
                    blob_client.upload_blob(
                        yaml.dump(data, default_flow_style=False),
                        overwrite=True,
                    )
                else:
                    raise ValueError(
                        f"{self.__class__.__name__}.save: Unsupported data format. Only json, yaml and bytes are supported."
                    )
                self.logger.info(f"Uploaded data to blob '{dst_path}'")

            return dst_path

        except Exception as e:
            self.logger.error(
                f"Failed to upload artifact to '{dst_path}': {e}"
            )
            raise

    def get_base_url(self):
        return f"https://{self.container_client.account_name}.blob.core.windows.net/{self.container_client.container_name}"

    def resolve_artifact_path(self, location: str) -> str:
        parsed = urlparse(location)
        if parsed.scheme:
            container_url = urlparse(self.container_client.url)
            if parsed.netloc.lower() != container_url.netloc.lower():
                raise ValueError(
                    "Artifact URL does not belong to configured storage"
                )
            container_path = container_url.path.rstrip("/") + "/"
            if not parsed.path.startswith(container_path):
                raise ValueError(
                    "Artifact URL does not belong to configured container"
                )
            location = unquote(parsed.path[len(container_path) :])

        normalized = str(PurePosixPath(location.lstrip("/")))
        if (
            not normalized
            or normalized == "."
            or ".." in PurePosixPath(normalized).parts
        ):
            raise ValueError("Invalid artifact path")
        return normalized

    def copy_artifact(
        self,
        source_path: str,
        destination_path: str,
        source_etag: str,
    ) -> str:
        source_relative = self.resolve_artifact_path(source_path)
        destination_relative = self.resolve_artifact_path(destination_path)
        source_client = self.container_client.get_blob_client(source_relative)
        destination_client = self.container_client.get_blob_client(
            destination_relative
        )
        if not source_client.exists():
            raise FileNotFoundError(source_path)

        current_source_etag = str(source_client.get_blob_properties().etag)
        if current_source_etag != source_etag:
            raise RuntimeError("Source artifact changed before copy")

        if destination_client.exists():
            destination_properties = destination_client.get_blob_properties()
            copy_status = getattr(destination_properties.copy, "status", None)
            if copy_status == "pending":
                self._wait_for_copy(destination_client, destination_relative)

        source_url = self.get_scoped_download_url(
            source_relative, expires_minutes=15
        )
        source_etag_digest = sha256(source_etag.encode("utf-8")).hexdigest()
        destination_client.start_copy_from_url(
            source_url,
            metadata={"hastesourceetag": source_etag_digest},
            source_etag=source_etag,
            source_match_condition=MatchConditions.IfNotModified,
        )
        return self._wait_for_copy(
            destination_client,
            destination_relative,
            expected_source_etag_digest=source_etag_digest,
        )

    def _wait_for_copy(
        self,
        blob_client,
        destination_path: str,
        timeout_seconds: int = 60,
        expected_source_etag_digest: str = None,
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            properties = blob_client.get_blob_properties()
            status = getattr(properties.copy, "status", None)
            if status == "success":
                if (
                    expected_source_etag_digest is not None
                    and (properties.metadata or {}).get("hastesourceetag")
                    != expected_source_etag_digest
                ):
                    raise RuntimeError(
                        "Published artifact source revision is unverified"
                    )
                return destination_path
            if status in {"failed", "aborted"}:
                description = getattr(
                    properties.copy, "status_description", "unknown error"
                )
                raise RuntimeError(f"Blob copy failed: {description}")
            time.sleep(0.25)
        raise TimeoutError(f"Blob copy did not finish: {destination_path}")

    def delete_prefix(self, prefix: str) -> int:
        relative_prefix = self.resolve_artifact_path(prefix).rstrip("/") + "/"
        blob_names = list(
            self.container_client.list_blob_names(
                name_starts_with=relative_prefix
            )
        )
        for blob_name in blob_names:
            self.container_client.delete_blob(blob_name)
        return len(blob_names)

    def artifact_exists(self, artifact_path: str) -> bool:
        relative_path = self.resolve_artifact_path(artifact_path)
        return self.container_client.get_blob_client(relative_path).exists()

    def get_artifact_size(self, artifact_path: str) -> int:
        relative_path = self.resolve_artifact_path(artifact_path)
        blob_client = self.container_client.get_blob_client(relative_path)
        if not blob_client.exists():
            raise FileNotFoundError(artifact_path)
        return blob_client.get_blob_properties().size

    def get_artifact_etag(self, artifact_path: str) -> str:
        relative_path = self.resolve_artifact_path(artifact_path)
        blob_client = self.container_client.get_blob_client(relative_path)
        if not blob_client.exists():
            raise FileNotFoundError(artifact_path)
        return str(blob_client.get_blob_properties().etag)

    def get_scoped_download_url(
        self, artifact_path: str, expires_minutes: int = 15
    ) -> str:
        if expires_minutes < 5 or expires_minutes > 60:
            raise ValueError("expires_minutes must be between 5 and 60")
        relative_path = self.resolve_artifact_path(artifact_path)
        blob_client = self.container_client.get_blob_client(relative_path)
        if not blob_client.exists():
            raise FileNotFoundError(artifact_path)

        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=expires_minutes)
        is_emulator = (
            self.container_client.account_name == "devstoreaccount1"
            or urlparse(self.container_client.url).hostname
            in {"127.0.0.1", "localhost", "azurite"}
        )
        user_delegation_key = None
        account_key = self.account_key
        delegation_client = self.blob_service_client
        if account_key and not is_emulator:
            delegation_client = self.identity_blob_service_client
            if delegation_client is None:
                raise RuntimeError(
                    "Managed identity is required for published downloads"
                )
            account_key = None
        if account_key is None:
            user_delegation_key = get_cached_user_delegation_key(
                delegation_client, now=now
            )

        sas_token = generate_blob_sas(
            account_name=self.container_client.account_name,
            container_name=self.container_client.container_name,
            blob_name=relative_path,
            permission=BlobSasPermissions(read=True),
            start=now - timedelta(minutes=5),
            expiry=expiry,
            account_key=account_key,
            user_delegation_key=user_delegation_key,
            protocol="https,http" if is_emulator else "https",
        )
        return f"{blob_client.url}?{sas_token}"
