# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Serialize catalog index updates and inference-only run transitions."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

from ..config import Config
from ..publishing.lease import BlobLeaseCoordinator
from .file_lock import file_lock
from .metadata import MetadataUtils


def catalog_task_id(
    project_id: str, request_id: str, prefix: Literal["inf", "zip"] = "inf"
) -> str:
    identity = MetadataUtils.hash_string(f"{project_id}/{request_id}")[:48]
    return f"{prefix}-catalog-{identity}"


@contextmanager
def catalog_lock(
    config: Config, project_id: str = "catalog", key: str = "index"
) -> Iterator[Any]:
    if config.storage_type == "local":
        directory = Path(config.storage_config["directory"], ".catalog-locks")
        name = MetadataUtils.hash_string(f"{project_id}/{key}")
        with file_lock(directory / f"{name}.lock"):
            yield None
    else:
        settings = config.publishing_config
        coordinator = BlobLeaseCoordinator(
            connection_string=settings["lease_connection_string"]
            or config.queue_config["queue_connection_string"],
            account_url=settings["lease_account_url"],
            container_name=settings["lease_container"],
        )
        with coordinator.acquire(
            project_id, f"catalog-{key}", wait_timeout_seconds=2
        ) as lease:
            yield lease
