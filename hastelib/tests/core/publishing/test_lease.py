import threading
import unittest
from unittest.mock import patch

from azure.core.exceptions import HttpResponseError
from hastegeo.core.publishing.lease import (
    BlobLeaseCoordinator,
    LeaseRenewalError,
    LeaseUnavailableError,
)


class FakeLease:
    def __init__(self, fail_renewal: bool = False) -> None:
        self.fail_renewal = fail_renewal
        self.renewed = threading.Event()
        self.released = False

    def renew(self) -> None:
        self.renewed.set()
        if self.fail_renewal:
            raise RuntimeError("renewal failed")

    def release(self) -> None:
        self.released = True


class FakeBlobClient:
    def __init__(self, lease=None, acquire_error=None) -> None:
        self.lease = lease or FakeLease()
        self.acquire_error = acquire_error

    def upload_blob(self, data, overwrite=False) -> None:
        return None

    def acquire_lease(self, lease_duration: int):
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.lease


class RetryOnceBlobClient(FakeBlobClient):
    def __init__(self, lease: FakeLease) -> None:
        super().__init__(lease=lease)
        self.attempts = 0

    def acquire_lease(self, lease_duration: int):
        self.attempts += 1
        if self.attempts == 1:
            conflict = HttpResponseError("conflict")
            conflict.status_code = 409
            raise conflict
        return self.lease


class FakeContainerClient:
    def __init__(self, blob_client: FakeBlobClient) -> None:
        self.blob_client = blob_client

    def get_blob_client(self, name: str) -> FakeBlobClient:
        return self.blob_client


class FakeBlobServiceClient:
    def __init__(self, container_client: FakeContainerClient) -> None:
        self.container_client = container_client

    def create_container(self, name: str) -> FakeContainerClient:
        return self.container_client


class ExistingContainerService(FakeBlobServiceClient):
    def create_container(self, name: str) -> FakeContainerClient:
        from azure.core.exceptions import ResourceExistsError

        raise ResourceExistsError("exists")

    def get_container_client(self, name: str) -> FakeContainerClient:
        return self.container_client


def build_coordinator(blob_client: FakeBlobClient) -> BlobLeaseCoordinator:
    container = FakeContainerClient(blob_client)
    service = FakeBlobServiceClient(container)
    return BlobLeaseCoordinator(
        connection_string=None,
        account_url=None,
        blob_service_client=service,
        renewal_interval_seconds=0.01,
    )


class TestBlobLeaseCoordinator(unittest.TestCase):
    def test_constructor_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            BlobLeaseCoordinator(None, None, renewal_interval_seconds=0)
        with self.assertRaisesRegex(ValueError, "connection string"):
            BlobLeaseCoordinator(None, None)

    def test_constructor_uses_connection_string_and_existing_container(
        self,
    ) -> None:
        container = FakeContainerClient(FakeBlobClient())
        service = ExistingContainerService(container)
        with patch(
            "hastegeo.core.publishing.lease.BlobServiceClient.from_connection_string",
            return_value=service,
        ) as factory:
            coordinator = BlobLeaseCoordinator("connection", None)

        self.assertIs(coordinator.container_client, container)
        factory.assert_called_once_with("connection")

    def test_acquire_rejects_invalid_wait_and_duration(self) -> None:
        coordinator = build_coordinator(FakeBlobClient())

        with self.assertRaisesRegex(ValueError, "between 15 and 60"):
            with coordinator.acquire("project", "dataset", lease_duration=10):
                pass
        with self.assertRaisesRegex(ValueError, "wait values"):
            with coordinator.acquire(
                "project", "dataset", retry_interval_seconds=0
            ):
                pass

    def test_non_conflict_acquire_error_is_preserved(self) -> None:
        error = HttpResponseError("service unavailable")
        error.status_code = 500
        coordinator = build_coordinator(FakeBlobClient(acquire_error=error))

        with self.assertRaises(HttpResponseError):
            with coordinator.acquire("project", "dataset"):
                pass

    def test_held_lease_is_renewed_and_released(self) -> None:
        lease = FakeLease()
        coordinator = build_coordinator(FakeBlobClient(lease=lease))

        with coordinator.acquire("project", "dataset", lease_duration=15):
            self.assertTrue(lease.renewed.wait(timeout=1))

        self.assertTrue(lease.released)

    def test_renewal_failure_is_reported_after_operation(self) -> None:
        lease = FakeLease(fail_renewal=True)
        coordinator = build_coordinator(FakeBlobClient(lease=lease))

        with self.assertRaisesRegex(LeaseRenewalError, "dataset"):
            with coordinator.acquire("project", "dataset", lease_duration=15):
                self.assertTrue(lease.renewed.wait(timeout=1))

        self.assertTrue(lease.released)

    def test_conflicting_lease_maps_to_unavailable(self) -> None:
        conflict = HttpResponseError("conflict")
        conflict.status_code = 409
        coordinator = build_coordinator(FakeBlobClient(acquire_error=conflict))

        with self.assertRaises(LeaseUnavailableError):
            with coordinator.acquire("project", "dataset", lease_duration=15):
                self.fail("lease should not be acquired")

    def test_waiting_claim_retries_contention(self) -> None:
        lease = FakeLease()
        blob_client = RetryOnceBlobClient(lease)
        coordinator = build_coordinator(blob_client)

        with coordinator.acquire(
            "project",
            "dataset",
            lease_duration=15,
            wait_timeout_seconds=0.1,
            retry_interval_seconds=0.001,
        ):
            pass

        self.assertEqual(blob_client.attempts, 2)
        self.assertTrue(lease.released)


if __name__ == "__main__":
    unittest.main()
