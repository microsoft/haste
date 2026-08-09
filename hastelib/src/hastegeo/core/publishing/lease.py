from contextlib import contextmanager
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any, Iterator, Optional

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from ..utils.metadata import MetadataUtils


class LeaseUnavailableError(RuntimeError):
    """Raised when another operation owns a dataset lease."""


class LeaseRenewalError(RuntimeError):
    """Raised when a held dataset lease cannot be renewed."""


class BlobLeaseCoordinator:
    """Serialize publishing operations with per-dataset Azure Blob leases."""

    def __init__(
        self,
        connection_string: Optional[str],
        account_url: Optional[str],
        container_name: str = "publishing-locks",
        blob_service_client: Any = None,
        renewal_interval_seconds: Optional[float] = None,
    ) -> None:
        if (
            renewal_interval_seconds is not None
            and renewal_interval_seconds <= 0
        ):
            raise ValueError("renewal_interval_seconds must be positive")
        self.renewal_interval_seconds = renewal_interval_seconds
        if blob_service_client is not None:
            self.blob_service_client = blob_service_client
        elif connection_string:
            self.blob_service_client = (
                BlobServiceClient.from_connection_string(connection_string)
            )
        elif account_url:
            self.blob_service_client = BlobServiceClient(
                account_url=account_url,
                credential=DefaultAzureCredential(),
            )
        else:
            raise ValueError(
                "A publishing lease connection string or account URL is required"
            )

        try:
            self.container_client = self.blob_service_client.create_container(
                container_name
            )
        except ResourceExistsError:
            self.container_client = (
                self.blob_service_client.get_container_client(container_name)
            )

    @contextmanager
    def acquire(
        self,
        project_id: str,
        dataset_id: str,
        lease_duration: int = 60,
        wait_timeout_seconds: float = 0,
        retry_interval_seconds: float = 0.05,
    ) -> Iterator[Any]:
        if lease_duration < 15 or lease_duration > 60:
            raise ValueError(
                "lease_duration must be between 15 and 60 seconds"
            )
        if wait_timeout_seconds < 0 or retry_interval_seconds <= 0:
            raise ValueError("Lease wait values must be positive")

        lock_name = (
            f"{MetadataUtils.hash_string(project_id)}/{dataset_id}.lock"
        )
        blob_client = self.container_client.get_blob_client(lock_name)
        try:
            blob_client.upload_blob(b"", overwrite=False)
        except ResourceExistsError:
            pass

        deadline = monotonic() + wait_timeout_seconds
        while True:
            try:
                lease = blob_client.acquire_lease(
                    lease_duration=lease_duration
                )
                break
            except HttpResponseError as error:
                if error.status_code != 409:
                    raise
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise LeaseUnavailableError(
                        f"Publishing operation already active for {dataset_id}"
                    ) from error
                sleep(min(retry_interval_seconds, remaining))

        renewal_stop = Event()
        renewal_errors: list[Exception] = []
        renewal_interval = (
            self.renewal_interval_seconds
            if self.renewal_interval_seconds is not None
            else max(5.0, lease_duration / 3)
        )

        def renew_lease() -> None:
            while not renewal_stop.wait(renewal_interval):
                try:
                    lease.renew()
                except Exception as error:
                    renewal_errors.append(error)
                    return

        renewal_thread = Thread(
            target=renew_lease,
            name=f"publishing-lease-{dataset_id}",
            daemon=True,
        )
        renewal_thread.start()
        try:
            yield lease
        finally:
            renewal_stop.set()
            renewal_thread.join(timeout=5)
            lease.release()
        if renewal_errors:
            raise LeaseRenewalError(
                f"Publishing lease renewal failed for {dataset_id}"
            ) from renewal_errors[0]
