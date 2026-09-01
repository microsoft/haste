# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from threading import Lock

import yaml
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import AccessPolicy  # type: ignore
from azure.storage.blob import BlobBlock  # type: ignore
from azure.storage.blob import ContainerSasPermissions, generate_container_sas

from ..utils.blob import (
    get_blob_service_client,
    get_cached_user_delegation_key,
)
from ..utils.metadata import matches_metadata_type
from ..utils.parallel import parallel_map
from .abstract_data_layer import AbstractDataLayer

_INITIALIZED_CONTAINERS = set()
_INITIALIZED_CONTAINERS_LOCK = Lock()


class AzureBlobStorageDataLayer(AbstractDataLayer):
    def __init__(
        self,
        account_url,
        container,
        connection_string,
        container_read_policy_name="image-r-policy",
        partition_key=None,
    ):
        super().__init__(partition_key)
        if connection_string:
            self.blob_service_client = get_blob_service_client(
                connection_string=connection_string
            )
            self.user_delegation_key = None
            self.account_key = self.blob_service_client.credential.account_key
        else:
            self.blob_service_client = get_blob_service_client(
                account_url=account_url
            )
            self.user_delegation_key = None
            self.account_key = None

        self.container_read_policy = container_read_policy_name
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
                    logging.info(
                        f"Container '{container}' created successfully."
                    )
                except ResourceExistsError:
                    logging.info(f"Container '{container}' already exists.")
                self._create_or_update_managed_access_policy()
                _INITIALIZED_CONTAINERS.add(cache_key)

    def _create_or_update_managed_access_policy(self):
        expiration_days = 90
        expiration_date = datetime.now(timezone.utc) + timedelta(
            days=expiration_days
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
            logging.info("Policy does not exist, create a new one")
            read_policy = AccessPolicy(
                permission=ContainerSasPermissions(read=True),
                expiry=expiration_date,
            )
            identifiers = {self.container_read_policy: read_policy}
            self.container_client.set_container_access_policy(
                signed_identifiers=identifiers
            )
            logging.info("Policy set")

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

        data_type = data_type + "_" if data_type else ""

        if identifier.endswith("." + data_format):
            filename = f"{data_type}{identifier}"
        else:
            filename = f"{data_type}{identifier}.{data_format}"
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
        blob_name = self.get_file_path(
            identifier,
            data_type,
            data_format=data_format,
            extra_partition_keys=extra_partition_keys,
        )
        blob_client = self.container_client.get_blob_client(blob_name)

        # ``check_exists=False`` skips the per-blob existence HEAD request. Use
        # it when the caller has already confirmed presence in bulk (e.g. via
        # ``list_identifiers``) — the container read SAS is identical for every
        # blob, so building the URL is a purely local operation.
        if not check_exists or blob_client.exists():
            user_delegation_key = self.user_delegation_key
            if self.account_key is None:
                user_delegation_key = get_cached_user_delegation_key(
                    self.blob_service_client
                )
            # Generate SAS token with the policy
            sas_token = generate_container_sas(
                account_name=self.container_client.account_name,
                container_name=self.container_client.container_name,
                policy_id=self.container_read_policy,
                user_delegation_key=user_delegation_key,
                account_key=self.account_key,
            )

            sas_url = f"{blob_client.url}?{sas_token}"
            return str(sas_url)
        else:
            return None

    def save(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
        extra_partition_keys=None,
    ):
        self.validate_data_input(data, data_file_path)

        if data_file_path:
            data = self.load_data_from_file(data_file_path)

        blob_name = self.get_file_path(
            identifier=identifier,
            data_type=data_type,
            data_format=data_format,
            extra_partition_keys=extra_partition_keys,
        )
        blob_client = self.container_client.get_blob_client(blob_name)
        if self.is_bytes(data):
            blob_client.upload_blob(data, overwrite=True)
        elif self.is_json(data):
            blob_client.upload_blob(
                json.dumps(data),
                overwrite=True,
                metadata=self._index_metadata(data_type, data),
            )
        elif self.is_yaml(data):
            logging.info("data is yaml, dumping to blob")
            blob_client.upload_blob(
                yaml.dump(data, default_flow_style=False), overwrite=True
            )
        else:
            raise ValueError(
                f"{self.__class__.__name__}.save: Unsupported data format. Only json, yaml and bytes are supported."
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
        blob_name = self.get_file_path(
            identifier=identifier, data_type=data_type, data_format=data_format
        )
        blob_client = self.container_client.get_blob_client(blob_name)

        block_id = hashlib.sha256(str(chunk_id).encode()).hexdigest()
        with open(data_file_path, "rb") as data:
            blob_client.stage_block(
                block_id=block_id,
                data=data,
                length=os.path.getsize(data_file_path),
            )

        return self.get_file_remote_path(
            identifier=identifier, data_type=data_type, data_format=data_format
        )

    def finalize_save(
        self,
        identifier,
        data_type,
        data_format="tif",
        data_file_path=None,
        total_chunks=None,
    ):
        blob_name = self.get_file_path(
            identifier=identifier, data_type=data_type, data_format=data_format
        )
        blob_client = self.container_client.get_blob_client(blob_name)

        block_id_list = []
        for i in range(total_chunks):
            block_id = hashlib.sha256(str(i).encode()).hexdigest()
            block_id_list.append(BlobBlock(block_id=block_id))
        blob_client.commit_block_list(block_id_list)
        return self.get_file_remote_path(
            identifier=identifier, data_type=data_type, data_format=data_format
        )

    def update(
        self,
        identifier,
        data_type,
        data=None,
        data_file_path=None,
        data_format="json",
    ):
        self.save(data, identifier, data_type, data_file_path, data_format)

    def load(self, identifier, data_type, data_format="json"):
        blob_name = self.get_file_path(identifier, data_type, data_format)
        blob_client = self.container_client.get_blob_client(blob_name)
        try:
            downloader = blob_client.download_blob()
            if data_format == "json":
                contents = json.loads(downloader.readall())
                if isinstance(contents, str):
                    # Need to do this conversion again. TODO: Investigate why projects nd image_layers needs this converted twice
                    # but models does not
                    contents = json.loads(contents)
                return contents
            elif data_format == "yaml":
                return yaml.safe_load(downloader.readall())
            raise ValueError(f"Unsupported data_format: {data_format}")
        except ResourceNotFoundError as error:
            raise FileNotFoundError(
                f"{self.__class__.__name__}.load: No data found for identifier: {identifier} and data_type: {data_type}"
            ) from error

    def load_all(self, data_type, data_format="json"):
        # Collect the matching blobs first (a cheap listing pass), then download
        # + deserialize them concurrently.
        matched = []

        def matches(blob_name):
            in_partition = not self.partition_key or blob_name.startswith(
                f"{self.partition_key}/"
            )
            return in_partition and matches_metadata_type(blob_name, data_type)

        blobs = self.container_client.walk_blobs()
        for blob in blobs:
            # Ignore stats file
            if "stats" in blob.name:
                continue
            # Check if the blob is a directory
            if blob.name.endswith("/"):
                sub_blobs = self.container_client.walk_blobs(
                    name_starts_with=blob.name
                )
                for sub_blob in sub_blobs:
                    if matches(sub_blob.name):
                        matched.append(sub_blob)
            else:
                if matches(blob.name):
                    matched.append(blob)
        return self._read_blobs_parallel(matched, data_format)

    def _read_blob_content(self, blob, data_format):
        """Download and deserialize a single blob's content.

        Tolerates records that were double-serialized on save (parse again when
        the first parse yields a string) so both legacy and current blobs read
        correctly.
        """
        blob_client = self.container_client.get_blob_client(blob)
        raw = blob_client.download_blob().readall()
        if data_format == "json":
            contents = json.loads(raw)
            if isinstance(contents, str):
                contents = json.loads(contents)
            return contents
        elif data_format == "yaml":
            return yaml.safe_load(raw)
        raise ValueError(f"Unsupported data_format: {data_format}")

    def _read_blobs_parallel(self, blobs, data_format):
        """Download+parse a list of blobs concurrently, preserving order."""
        return parallel_map(
            lambda blob: self._read_blob_content(blob, data_format), blobs
        )

    def load_all_from_partition(self, data_type, data_format="json"):
        if not self.partition_key:
            raise ValueError(
                f"{self.__class__.__name__}.load_all_from_partition: Partition key is not set."
            )

        blobs = self.container_client.walk_blobs(
            name_starts_with=f"{self.partition_key}/{data_type}_"
        )
        matching_blobs = (
            blob
            for blob in blobs
            if matches_metadata_type(blob.name, data_type)
        )
        return self._read_blobs_parallel(matching_blobs, data_format)

    def load_map(
        self,
        identifiers,
        data_type,
        data_format="json",
        max_workers=None,
    ):
        identifiers = list(dict.fromkeys(identifiers))

        def load_one(identifier):
            try:
                return identifier, self.load(
                    identifier, data_type, data_format=data_format
                )
            except FileNotFoundError:
                return identifier, None

        return dict(
            parallel_map(load_one, identifiers, max_workers=max_workers)
        )

    def load_bounded(self, data_type, max_records, data_format="json"):
        records, _ = self.load_page(
            data_type=data_type,
            page=1,
            page_size=max_records,
            data_format=data_format,
            max_records=max_records,
        )
        return records

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
        if page < 1 or page_size < 1:
            raise ValueError("page and page_size must be positive")
        if max_records is not None and max_records < 1:
            raise ValueError("max_records must be positive")

        prefix = (
            f"{self.partition_key}/{data_type}_"
            if self.partition_key
            else None
        )
        matching_blobs = []
        catalog_record_count = 0
        scanned_blob_count = 0
        scan_limit = max_records * 10 if max_records is not None else None
        list_options = {
            "name_starts_with": prefix,
            "include": ["metadata"],
        }
        if max_records is not None:
            list_options["results_per_page"] = max_records + 1
        blobs = self.container_client.list_blobs(**list_options)
        pages = blobs.by_page()
        for blob_page in pages:
            for blob in blob_page:
                scanned_blob_count += 1
                if scan_limit is not None and scanned_blob_count > scan_limit:
                    raise ValueError(
                        "Catalog storage scan exceeds the bounded envelope"
                    )
                parts = blob.name.split("/")
                if "stats" in blob.name or len(parts) > 2:
                    continue
                matches = matches_metadata_type(blob.name, data_type)
                if not matches or not blob.name.endswith(f".{data_format}"):
                    continue
                catalog_record_count += 1
                if (
                    max_records is not None
                    and catalog_record_count > max_records
                ):
                    raise ValueError(
                        f"Catalog exceeds the {max_records:,}-record limit"
                    )
                metadata = blob.metadata or {}
                if target and metadata.get("hastetarget") != target:
                    continue
                if status and metadata.get("hastestatus") != status:
                    continue
                if project_id and metadata.get("hasteproject") != project_id:
                    continue
                matching_blobs.append(blob)

        matching_blobs.sort(
            key=lambda blob: (
                (blob.metadata or {}).get("hastesort")
                or blob.last_modified.isoformat(),
                blob.name,
            ),
            reverse=True,
        )
        total_count = len(matching_blobs)
        start = (page - 1) * page_size
        page_names = [
            blob.name for blob in matching_blobs[start : start + page_size]
        ]
        records = self._load_blob_names(page_names, data_format)
        total_count -= len(page_names) - len(records)
        return records, total_count

    @staticmethod
    def _index_metadata(data_type, data):
        if data_type != "published_dataset" or not isinstance(data, dict):
            return None
        return {
            "hastesort": str(
                data.get("publishedDate") or data.get("createdDate") or ""
            ),
            "hastetarget": str(data.get("target") or ""),
            "hastestatus": str(data.get("status") or ""),
            "hasteproject": str(data.get("projectId") or ""),
        }

    def _load_blob_names(self, blob_names, data_format):
        """Like :meth:`_read_blobs_parallel`, but tolerates blobs deleted
        between listing and download (they are dropped from the result)."""
        if not blob_names:
            return []

        missing_blob = object()

        def load_blob(blob_name):
            try:
                return self._read_blob_content(blob_name, data_format)
            except ResourceNotFoundError:
                return missing_blob

        records = parallel_map(load_blob, blob_names)
        return [record for record in records if record is not missing_blob]

    def list_identifiers(self, data_type, data_format="json"):
        if not self.partition_key:
            raise ValueError(
                f"{self.__class__.__name__}.list_identifiers: Partition key is not set."
            )
        prefix = f"{self.partition_key}/{data_type}_"
        suffix = f".{data_format}"
        identifiers = []
        for name in self.container_client.list_blob_names(
            name_starts_with=prefix
        ):
            if name.endswith(suffix) and matches_metadata_type(
                name, data_type
            ):
                identifiers.append(name[len(prefix) : -len(suffix)])
        return identifiers

    def delete(self, identifier, data_type, data_format="json"):
        blob_name = self.get_file_path(identifier, data_type, data_format)
        blob_client = self.container_client.get_blob_client(blob_name)
        blob_client.delete_blob()

    def delete_all_from_partition(self):
        if not self.partition_key:
            raise ValueError(
                f"{self.__class__.__name__}.delete_all_from_partition: Partition key is not set."
            )

        blobs = self.container_client.list_blob_names(
            name_starts_with=f"{self.partition_key}/"
        )
        for blob in blobs:
            blob_client = self.container_client.get_blob_client(blob)
            blob_client.delete_blob()
        return True

    def get_base_url(self):
        # Use the actual service URL so this works with both Azure Blob
        # Storage and local emulators like Azurite.
        return f"{self.blob_service_client.url.rstrip('/')}/{self.container_client.container_name}"
