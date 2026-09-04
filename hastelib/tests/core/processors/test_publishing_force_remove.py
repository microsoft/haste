import unittest
import uuid
from contextlib import nullcontext
from unittest.mock import Mock

from hastegeo.core.models.publishing import (
    PublishedDataset,
    PublishOperation,
    PublishQueueMessage,
    PublishStatus,
    PublishTarget,
)
from hastegeo.core.processors.publishing import (
    PublishingPermissionError,
    PublishingProcessor,
    PublishingStateConflictError,
)

OWNER = "owner@example.com"
PROJECT_ID = uuid.UUID("123e4567-e89b-12d3-a456-426614174000")
DATASET_ID = uuid.UUID("3e8d5e90-f2fc-5412-9f97-a52c07815f0b")


def _dataset(status: PublishStatus) -> PublishedDataset:
    return PublishedDataset(
        datasetId=DATASET_ID,
        requestId=uuid.uuid4(),
        requestFingerprint="a" * 64,
        name="Stuck dataset",
        projectId=PROJECT_ID,
        imageLayerId="layer",
        modelId="7",
        target=PublishTarget.PLANETARY_COMPUTER,
        status=status,
        publishedByUser=OWNER,
        createdDate="2026-08-27T00:00:00Z",
        updatedDate="2026-08-27T00:00:00Z",
    )


class FakeRepository:
    """Minimal repository: serves a single dataset and records deletion."""

    def __init__(self, dataset: PublishedDataset) -> None:
        self._dataset = dataset
        self.deleted: list[tuple[str, str]] = []

    def load(self, project_id: str, dataset_id: str) -> PublishedDataset:
        if self._dataset is None:
            raise FileNotFoundError(dataset_id)
        return self._dataset

    def operation_lock(self, project_id: str, dataset_id: str):
        return nullcontext()

    def delete_locked(self, project_id: str, dataset_id: str) -> None:
        self.deleted.append((project_id, dataset_id))
        self._dataset = None


def _processor(dataset: PublishedDataset, enabled: bool = True):
    repository = FakeRepository(dataset)
    provider = Mock()
    registry = Mock()
    registry.resolve.return_value = provider
    config = Mock()
    config.publishing_config = {"publishing_enabled": enabled}
    queue_handler = Mock()
    processor = PublishingProcessor(
        config=config,
        repository=repository,
        source_resolver=Mock(),
        registry=registry,
        queue_handler=queue_handler,
    )
    processor._test_queue_handler = queue_handler
    return processor, repository, provider


class TestForceRemove(unittest.TestCase):
    def test_force_remove_cleans_up_and_drops_record(self) -> None:
        processor, repository, provider = _processor(
            _dataset(PublishStatus.UNPUBLISH_FAILED)
        )
        removed = processor.force_remove(
            str(PROJECT_ID), str(DATASET_ID), OWNER
        )
        provider.start_unpublish.assert_called_once()
        self.assertEqual(
            repository.deleted, [(str(PROJECT_ID), str(DATASET_ID))]
        )
        self.assertEqual(removed.datasetId, DATASET_ID)

    def test_force_remove_drops_record_even_when_cleanup_fails(self) -> None:
        processor, repository, provider = _processor(
            _dataset(PublishStatus.FAILED)
        )
        provider.start_unpublish.side_effect = RuntimeError("cleanup boom")
        processor.force_remove(str(PROJECT_ID), str(DATASET_ID), OWNER)
        # Best-effort cleanup raised, but the record is still dropped.
        self.assertEqual(
            repository.deleted, [(str(PROJECT_ID), str(DATASET_ID))]
        )

    def test_force_remove_rejects_non_terminal_status(self) -> None:
        processor, repository, provider = _processor(
            _dataset(PublishStatus.PUBLISHED)
        )
        with self.assertRaises(PublishingStateConflictError):
            processor.force_remove(str(PROJECT_ID), str(DATASET_ID), OWNER)
        provider.start_unpublish.assert_not_called()
        self.assertEqual(repository.deleted, [])

    def test_force_remove_rejects_non_owner_non_admin(self) -> None:
        processor, repository, _ = _processor(
            _dataset(PublishStatus.UNPUBLISH_FAILED)
        )
        with self.assertRaises(PublishingPermissionError):
            processor.force_remove(
                str(PROJECT_ID), str(DATASET_ID), "someone-else@example.com"
            )
        self.assertEqual(repository.deleted, [])

    def test_force_remove_allows_admin_non_owner(self) -> None:
        processor, repository, _ = _processor(
            _dataset(PublishStatus.UNPUBLISH_FAILED)
        )
        processor.force_remove(
            str(PROJECT_ID),
            str(DATASET_ID),
            "admin@example.com",
            is_admin=True,
        )
        self.assertEqual(
            repository.deleted, [(str(PROJECT_ID), str(DATASET_ID))]
        )


class TestRunStepKillSwitch(unittest.TestCase):
    def test_run_step_defers_when_publishing_disabled(self) -> None:
        processor, repository, provider = _processor(
            _dataset(PublishStatus.PENDING), enabled=False
        )
        message = PublishQueueMessage(
            datasetId=DATASET_ID,
            projectId=PROJECT_ID,
            operation=PublishOperation.PUBLISH,
            attempt=1,
        )
        result = processor.run_step(message)
        # Parked, not processed: no provider resolution, no record change.
        self.assertIsNone(result)
        provider.start_unpublish.assert_not_called()
        self.assertEqual(repository.deleted, [])
        # The message is re-posted with a delay so it resumes when re-enabled.
        processor._test_queue_handler.put_message.assert_called_once()
        _, kwargs = processor._test_queue_handler.put_message.call_args
        self.assertGreater(kwargs["visibility_timeout"], 0)


class TestUpdateMetadataStateGuard(unittest.TestCase):
    def test_update_metadata_rejects_in_progress(self) -> None:
        processor, repository, _ = _processor(
            _dataset(PublishStatus.IN_PROGRESS)
        )
        with self.assertRaises(PublishingStateConflictError):
            processor.update_metadata(
                str(PROJECT_ID),
                str(DATASET_ID),
                OWNER,
                False,
                {"name": "new name"},
            )

    def test_update_metadata_allows_published(self) -> None:
        processor, repository, provider = _processor(
            _dataset(PublishStatus.PUBLISHED)
        )
        # repository.update returns the edited record for the PUBLISHED push.
        repository.update = Mock(side_effect=lambda d, expected_revision: d)
        saved = processor.update_metadata(
            str(PROJECT_ID),
            str(DATASET_ID),
            OWNER,
            False,
            {"name": "new name"},
        )
        self.assertEqual(saved.name, "new name")
        provider.update_published_metadata.assert_called_once()


if __name__ == "__main__":
    unittest.main()
