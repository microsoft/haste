import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from typing import Dict, Iterator, Tuple
from unittest.mock import Mock

from hastegeo.core.models.publishing import PublishedDataset, PublishStatus
from hastegeo.core.publishing.repository import (
    PublishedDatasetsExistError,
    PublishingConflictError,
    PublishingRepository,
    StaleRevisionError,
)


class FakeMetadataProcessor:
    records: Dict[Tuple[str, str], dict] = {}
    records_lock = threading.Lock()

    def __init__(
        self,
        data_type: str,
        partition_key: str = None,
        config=None,
    ) -> None:
        self.partition_key = partition_key or ""

    def save(
        self, key: str, metadata: dict, data_format: str = "json"
    ) -> None:
        with self.records_lock:
            self.records[(self.partition_key, key)] = deepcopy(metadata)

    def load(self, key: str, data_format: str = "json") -> dict:
        with self.records_lock:
            try:
                return deepcopy(self.records[(self.partition_key, key)])
            except KeyError as error:
                raise FileNotFoundError(key) from error

    def load_all(self, data_format: str = "json") -> list[dict]:
        with self.records_lock:
            return [deepcopy(record) for record in self.records.values()]

    def load_all_from_partition(self, data_format: str = "json") -> list[dict]:
        with self.records_lock:
            return [
                deepcopy(record)
                for (partition, _), record in self.records.items()
                if partition == self.partition_key
            ]

    def delete(self, key: str, data_format: str = "json") -> None:
        with self.records_lock:
            del self.records[(self.partition_key, key)]

    def load_page(
        self,
        page,
        page_size,
        target=None,
        status=None,
        **kwargs,
    ):
        records = (
            self.load_all_from_partition()
            if self.partition_key
            else self.load_all()
        )
        if target:
            records = [
                record for record in records if record["target"] == target
            ]
        if status:
            records = [
                record for record in records if record["status"] == status
            ]
        start = (page - 1) * page_size
        return records[start : start + page_size], len(records)

    def load_bounded(self, max_records, data_format="json"):
        records = self.load_all(data_format=data_format)
        if len(records) > max_records:
            raise ValueError("record limit")
        return records


class FakeLeaseCoordinator:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.locks: Dict[Tuple[str, str], threading.Lock] = {}

    @contextmanager
    def acquire(
        self,
        project_id: str,
        dataset_id: str,
        lease_duration: int = 60,
        **kwargs,
    ) -> Iterator[None]:
        key = (project_id, dataset_id)
        with self.guard:
            operation_lock = self.locks.setdefault(key, threading.Lock())
        with operation_lock:
            yield


class FakeConfig:
    publishing_config = {"publishing_enabled": True}

    @staticmethod
    def get_metadata_types():
        class Types:
            class PUBLISHED_DATASET:
                value = "published_dataset"

        return Types


class TestPublishingRepository(unittest.TestCase):
    def setUp(self) -> None:
        FakeMetadataProcessor.records = {}
        self.repository = PublishingRepository(
            config=FakeConfig(),
            processor_factory=FakeMetadataProcessor,
            lease_coordinator=FakeLeaseCoordinator(),
        )
        self.dataset = PublishedDataset(
            datasetId=uuid.uuid4(),
            requestId=uuid.uuid4(),
            requestFingerprint="a" * 64,
            name="Dataset",
            projectId=uuid.uuid4(),
            imageLayerId="layer",
            modelId="model",
            target="local",
            status="PENDING",
            publishedByUser="publisher",
            createdDate="2026-08-06T00:00:00Z",
            updatedDate="2026-08-06T00:00:00Z",
        )

    def test_concurrent_replays_create_one_record(self) -> None:
        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(
                executor.map(
                    lambda _: self.repository.create_or_replay(self.dataset),
                    range(50),
                )
            )

        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len(self.repository.list_all()), 1)

    def test_concurrent_distinct_creates_preserve_fifty_records(self) -> None:
        datasets = [
            self.dataset.model_copy(
                update={
                    "datasetId": uuid.uuid4(),
                    "requestId": uuid.uuid4(),
                    "requestFingerprint": f"{index:064x}",
                }
            )
            for index in range(50)
        ]

        with ThreadPoolExecutor(max_workers=20) as executor:
            results = list(
                executor.map(self.repository.create_or_replay, datasets)
            )

        self.assertTrue(all(created for _, created in results))
        self.assertEqual(len(self.repository.list_all()), 50)
        for dataset in datasets:
            loaded = self.repository.load(
                str(dataset.projectId), str(dataset.datasetId)
            )
            self.assertEqual(loaded.requestId, dataset.requestId)

    def test_reused_request_id_with_changed_payload_conflicts(self) -> None:
        self.repository.create_or_replay(self.dataset)
        conflicting = self.dataset.model_copy(
            update={"requestFingerprint": "b" * 64}
        )

        with self.assertRaises(PublishingConflictError):
            self.repository.create_or_replay(conflicting)

    def test_update_rejects_stale_revision(self) -> None:
        stored, _ = self.repository.create_or_replay(self.dataset)
        changed = stored.model_copy(
            update={"status": PublishStatus.IN_PROGRESS}
        )
        updated = self.repository.update(changed, expected_revision=1)

        self.assertEqual(updated.revision, 2)
        with self.assertRaises(StaleRevisionError):
            self.repository.update(changed, expected_revision=1)

    def test_project_delete_action_is_blocked_when_dataset_exists(
        self,
    ) -> None:
        self.repository.create_or_replay(self.dataset)
        deleted = []

        with self.assertRaises(PublishedDatasetsExistError):
            self.repository.delete_project_if_unpublished(
                str(self.dataset.projectId), lambda: deleted.append(True)
            )

        self.assertEqual(deleted, [])

    def test_project_delete_action_runs_under_empty_project_guard(
        self,
    ) -> None:
        deleted = []

        self.repository.delete_project_if_unpublished(
            str(self.dataset.projectId), lambda: deleted.append(True)
        )

        self.assertEqual(deleted, [True])

    def test_disabled_project_guard_does_not_require_lease_storage(
        self,
    ) -> None:
        config = FakeConfig()
        config.publishing_config = {"publishing_enabled": False}
        repository = PublishingRepository(
            config=config,
            processor_factory=FakeMetadataProcessor,
        )
        deleted = []

        repository.delete_project_if_unpublished(
            str(self.dataset.projectId), lambda: deleted.append(True)
        )

        self.assertEqual(deleted, [True])

    def test_list_orders_by_published_date_with_created_fallback(self) -> None:
        older = self.dataset.model_copy(
            update={
                "createdDate": "2026-08-06T02:00:00Z",
                "publishedDate": None,
            }
        )
        republished = self.dataset.model_copy(
            update={
                "datasetId": uuid.uuid4(),
                "requestId": uuid.uuid4(),
                "createdDate": "2026-08-06T01:00:00Z",
                "publishedDate": "2026-08-06T03:00:00Z",
            }
        )
        self.repository.create_or_replay(older)
        self.repository.create_or_replay(republished)

        records = self.repository.list_all()

        self.assertEqual(records[0].datasetId, republished.datasetId)

    def test_list_page_returns_total_and_exact_search_results(self) -> None:
        for index, name in enumerate(
            ("Alpha damage", "Bravo flood", "Charlie")
        ):
            dataset = self.dataset.model_copy(
                update={
                    "datasetId": uuid.uuid4(),
                    "requestId": uuid.uuid4(),
                    "requestFingerprint": f"{index + 10:064x}",
                    "name": name,
                }
            )
            self.repository.create_or_replay(dataset)

        records, total = self.repository.list_page(
            page=1,
            page_size=2,
            search="flood",
            sort_key="name",
            sort_direction="asc",
        )

        self.assertEqual(total, 1)
        self.assertEqual([record.name for record in records], ["Bravo flood"])

    def test_list_page_rejects_unbounded_page_size(self) -> None:
        with self.assertRaises(ValueError):
            self.repository.list_page(page=1, page_size=101)

    def test_blob_list_page_uses_indexed_storage_path(self) -> None:
        config = FakeConfig()
        config.storage_type = "blob"
        repository = PublishingRepository(
            config=config,
            processor_factory=FakeMetadataProcessor,
            lease_coordinator=FakeLeaseCoordinator(),
        )
        repository.create_or_replay(self.dataset)

        records, total = repository.list_page(
            page=1,
            page_size=20,
            target=self.dataset.target,
            status=self.dataset.status,
        )

        self.assertEqual(total, 1)
        self.assertEqual(records[0].datasetId, self.dataset.datasetId)

    def test_blob_search_rejects_catalog_above_scan_limit(self) -> None:
        config = FakeConfig()
        config.storage_type = "blob"
        processor = Mock()
        processor.load_page.return_value = ([], 1001)
        repository = PublishingRepository(
            config=config,
            processor_factory=Mock(return_value=processor),
            lease_coordinator=FakeLeaseCoordinator(),
        )

        with self.assertRaisesRegex(ValueError, "1,000"):
            repository.list_page(
                page=1,
                page_size=20,
                search="damage",
            )

        processor.load_page.assert_called_once()

    def test_blob_search_uses_bounded_unfiltered_page(self) -> None:
        config = FakeConfig()
        config.storage_type = "blob"
        processor = Mock()
        processor.load_page.return_value = (
            [self.dataset.model_dump(mode="json")],
            1,
        )
        repository = PublishingRepository(
            config=config,
            processor_factory=Mock(return_value=processor),
            lease_coordinator=FakeLeaseCoordinator(),
        )

        records, total = repository.list_page(
            page=1,
            page_size=20,
            target=self.dataset.target,
            search="dataset",
            sort_key="name",
        )

        self.assertEqual(total, 1)
        self.assertEqual(records[0].datasetId, self.dataset.datasetId)
        processor.load_page.assert_called_once_with(
            page=1,
            page_size=1000,
            project_id=None,
            max_records=1000,
        )
        processor.load_all.assert_not_called()

    def test_blob_reconciliation_uses_bounded_page(self) -> None:
        config = FakeConfig()
        config.storage_type = "blob"
        processor = Mock()
        processor.load_page.return_value = (
            [self.dataset.model_dump(mode="json")],
            1,
        )
        repository = PublishingRepository(
            config=config,
            processor_factory=Mock(return_value=processor),
            lease_coordinator=FakeLeaseCoordinator(),
        )

        records = repository.list_for_reconciliation()

        self.assertEqual(records[0].datasetId, self.dataset.datasetId)
        processor.load_page.assert_called_once_with(
            page=1,
            page_size=1000,
            max_records=1000,
        )
        processor.load_all.assert_not_called()

    def test_non_blob_reconciliation_uses_bounded_read(self) -> None:
        processor = Mock()
        processor.load_bounded.return_value = [
            self.dataset.model_dump(mode="json")
        ]
        repository = PublishingRepository(
            config=FakeConfig(),
            processor_factory=Mock(return_value=processor),
            lease_coordinator=FakeLeaseCoordinator(),
        )

        records = repository.list_for_reconciliation()

        self.assertEqual(records[0].datasetId, self.dataset.datasetId)
        processor.load_bounded.assert_called_once_with(max_records=1000)
        processor.load_all.assert_not_called()

    def test_delete_with_revision_guard(self) -> None:
        stored, _ = self.repository.create_or_replay(self.dataset)

        with self.assertRaises(StaleRevisionError):
            self.repository.delete(
                str(stored.projectId),
                str(stored.datasetId),
                expected_revision=2,
            )
        self.repository.delete(
            str(stored.projectId),
            str(stored.datasetId),
            expected_revision=1,
        )
        with self.assertRaises(FileNotFoundError):
            self.repository.load(str(stored.projectId), str(stored.datasetId))


if __name__ == "__main__":
    unittest.main()
