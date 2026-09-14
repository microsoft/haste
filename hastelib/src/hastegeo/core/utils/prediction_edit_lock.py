# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Serialize cooperating prediction/edit publishers; no extra metadata store."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import Config
from ..publishing.lease import BlobLeaseCoordinator
from .metadata import MetadataUtils


@contextmanager
def prediction_edit_lock(
    config: Config, project_id: str, model_id: str
) -> Iterator[Any]:
    if config.storage_type == "local":
        import fcntl

        directory = Path(
            config.storage_config["directory"],
            MetadataUtils.hash_string(project_id),
            ".prediction-edit-locks",
        )
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"{MetadataUtils.hash_string(model_id)}.lock").open(
            "a"
        ) as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield None
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
    else:
        settings = config.publishing_config
        coordinator = BlobLeaseCoordinator(
            connection_string=settings["lease_connection_string"]
            or config.queue_config["queue_connection_string"],
            account_url=settings["lease_account_url"],
            container_name=settings["lease_container"],
        )
        with coordinator.acquire(
            project_id, f"prediction-edit-{model_id}", wait_timeout_seconds=2
        ) as lease:
            yield lease
