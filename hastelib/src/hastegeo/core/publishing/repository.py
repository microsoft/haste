from contextlib import AbstractContextManager, nullcontext
from typing import Any, Callable, List, Optional, Tuple

from ..config import Config
from ..models.publishing import PublishedDataset, PublishStatus, PublishTarget
from ..processors.metadata import MetadataProcessor
from .lease import BlobLeaseCoordinator

MAX_CATALOG_SCAN_RECORDS = 1000


class PublishingConflictError(RuntimeError):
    """Raised when an idempotency key is reused with a different request."""


class PublishedDatasetsExistError(RuntimeError):
    """Raised when project deletion is blocked by published datasets."""


class StaleRevisionError(RuntimeError):
    """Raised when a caller tries to update an outdated dataset revision."""


class PublishingRepository:
    """Persist independently updateable published-dataset records."""

    def __init__(
        self,
        config: Optional[Config] = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
        lease_coordinator: Optional[BlobLeaseCoordinator] = None,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory
        self.lease_coordinator = lease_coordinator
        self.data_type = (
            self.config.get_metadata_types().PUBLISHED_DATASET.value
        )

    def _processor(self, project_id: str) -> MetadataProcessor:
        return self.processor_factory(
            data_type=self.data_type,
            partition_key=project_id,
            config=self.config,
        )

    def create_or_replay(
        self, dataset: PublishedDataset
    ) -> Tuple[PublishedDataset, bool]:
        project_id = str(dataset.projectId)
        dataset_id = str(dataset.datasetId)
        with self.operation_lock(project_id, dataset_id):
            return self.create_or_replay_locked(dataset)

    def create_or_replay_locked(
        self, dataset: PublishedDataset
    ) -> Tuple[PublishedDataset, bool]:
        project_id = str(dataset.projectId)
        dataset_id = str(dataset.datasetId)
        try:
            existing = self.load(project_id, dataset_id)
        except FileNotFoundError:
            self._processor(project_id).save(
                dataset_id, dataset.model_dump(mode="json")
            )
            return dataset, True

        if existing.requestFingerprint != dataset.requestFingerprint:
            raise PublishingConflictError(
                "requestId was already used with different publish values"
            )
        return existing, False

    def load(self, project_id: str, dataset_id: str) -> PublishedDataset:
        data = self._processor(project_id).load(dataset_id)
        return PublishedDataset(**data)

    def list_all(
        self,
        project_id: Optional[str] = None,
        target: Optional[PublishTarget] = None,
        status: Optional[PublishStatus] = None,
    ) -> List[PublishedDataset]:
        if project_id:
            raw_records = self._processor(project_id).load_all_from_partition()
        else:
            raw_records = self.processor_factory(
                data_type=self.data_type,
                config=self.config,
            ).load_all()

        records = [PublishedDataset(**record) for record in raw_records]
        if target is not None:
            records = [record for record in records if record.target == target]
        if status is not None:
            records = [record for record in records if record.status == status]
        return sorted(
            records,
            key=lambda record: record.publishedDate or record.createdDate,
            reverse=True,
        )

    def list_for_reconciliation(self) -> List[PublishedDataset]:
        if getattr(self.config, "storage_type", None) == "blob":
            raw_records, _ = self.processor_factory(
                data_type=self.data_type,
                config=self.config,
            ).load_page(
                page=1,
                page_size=MAX_CATALOG_SCAN_RECORDS,
                max_records=MAX_CATALOG_SCAN_RECORDS,
            )
        else:
            raw_records = self.processor_factory(
                data_type=self.data_type,
                config=self.config,
            ).load_bounded(max_records=MAX_CATALOG_SCAN_RECORDS)
        return [PublishedDataset(**record) for record in raw_records]

    def list_page(
        self,
        page: int,
        page_size: int,
        project_id: Optional[str] = None,
        target: Optional[PublishTarget] = None,
        status: Optional[PublishStatus] = None,
        search: str = "",
        sort_key: str = "publishedDate",
        sort_direction: str = "desc",
    ) -> Tuple[List[PublishedDataset], int]:
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("Invalid publishing page request")
        sortable_fields = {
            "name",
            "projectName",
            "target",
            "status",
            "publishedByUser",
            "publishedDate",
        }
        if sort_key not in sortable_fields or sort_direction not in {
            "asc",
            "desc",
        }:
            raise ValueError("Invalid publishing sort request")

        normalized_search = search.strip().lower()
        if (
            getattr(self.config, "storage_type", None) == "blob"
            and not normalized_search
            and sort_key == "publishedDate"
            and sort_direction == "desc"
        ):
            processor = self.processor_factory(
                data_type=self.data_type,
                config=self.config,
            )
            raw_records, total_count = processor.load_page(
                page=page,
                page_size=page_size,
                target=target.value if target else None,
                status=status.value if status else None,
                project_id=project_id,
                max_records=MAX_CATALOG_SCAN_RECORDS,
            )
            records = [PublishedDataset(**record) for record in raw_records]
            return records, total_count

        if getattr(self.config, "storage_type", None) == "blob":
            processor = self.processor_factory(
                data_type=self.data_type,
                config=self.config,
            )
            raw_records, scan_count = processor.load_page(
                page=1,
                page_size=MAX_CATALOG_SCAN_RECORDS,
                project_id=project_id,
                max_records=MAX_CATALOG_SCAN_RECORDS,
            )
            if scan_count > MAX_CATALOG_SCAN_RECORDS:
                raise ValueError(
                    "Search and custom sorting are limited to 1,000 records"
                )
            records = [PublishedDataset(**record) for record in raw_records]
            if project_id is not None:
                records = [
                    record
                    for record in records
                    if str(record.projectId) == project_id
                ]
            if target is not None:
                records = [
                    record for record in records if record.target == target
                ]
            if status is not None:
                records = [
                    record for record in records if record.status == status
                ]
        else:
            records = self.list_all(
                project_id=project_id,
                target=target,
                status=status,
            )
        if normalized_search:
            records = [
                record
                for record in records
                if normalized_search
                in " ".join(
                    [
                        record.name,
                        record.description,
                        record.projectName,
                        record.imageLayerName,
                        record.publishedByUser,
                        record.target.value,
                        record.status.value,
                    ]
                ).lower()
            ]

        def sort_value(record: PublishedDataset) -> str:
            value = getattr(record, sort_key)
            if hasattr(value, "value"):
                value = value.value
            if sort_key == "publishedDate":
                value = value or record.createdDate
            return str(value or "").lower()

        records.sort(
            key=sort_value,
            reverse=sort_direction == "desc",
        )
        total_count = len(records)
        start = (page - 1) * page_size
        return records[start : start + page_size], total_count

    def operation_lock(
        self, project_id: str, dataset_id: str
    ) -> AbstractContextManager[Any]:
        return self._get_lease_coordinator().acquire(project_id, dataset_id)

    def project_lock(self, project_id: str) -> AbstractContextManager[Any]:
        if not self.config.publishing_config.get("publishing_enabled", False):
            return nullcontext()
        return self._get_lease_coordinator().acquire(
            project_id,
            "project-publishing",
            wait_timeout_seconds=2,
            retry_interval_seconds=0.02,
        )

    def delete_project_if_unpublished(
        self, project_id: str, delete_action: Callable[[], None]
    ) -> None:
        with self.project_lock(project_id):
            if self.list_all(project_id=project_id):
                raise PublishedDatasetsExistError(
                    "Unpublish all project datasets before deleting the project"
                )
            delete_action()

    def _get_lease_coordinator(self) -> BlobLeaseCoordinator:
        if self.lease_coordinator is None:
            publishing = self.config.publishing_config
            self.lease_coordinator = BlobLeaseCoordinator(
                connection_string=publishing["lease_connection_string"],
                account_url=publishing["lease_account_url"],
                container_name=publishing["lease_container"],
            )
        return self.lease_coordinator

    def update(
        self,
        dataset: PublishedDataset,
        expected_revision: int,
    ) -> PublishedDataset:
        project_id = str(dataset.projectId)
        dataset_id = str(dataset.datasetId)
        with self.operation_lock(project_id, dataset_id):
            return self.update_locked(dataset, expected_revision)

    def update_locked(
        self,
        dataset: PublishedDataset,
        expected_revision: int,
    ) -> PublishedDataset:
        project_id = str(dataset.projectId)
        dataset_id = str(dataset.datasetId)
        current = self.load(project_id, dataset_id)
        if current.revision != expected_revision:
            raise StaleRevisionError(
                f"Expected revision {expected_revision}, found {current.revision}"
            )
        updated = dataset.model_copy(
            update={"revision": expected_revision + 1}
        )
        self._processor(project_id).save(
            dataset_id, updated.model_dump(mode="json")
        )
        return updated

    def delete(
        self,
        project_id: str,
        dataset_id: str,
        expected_revision: Optional[int] = None,
    ) -> None:
        with self.operation_lock(project_id, dataset_id):
            if expected_revision is not None:
                current = self.load(project_id, dataset_id)
                if current.revision != expected_revision:
                    raise StaleRevisionError(
                        f"Expected revision {expected_revision}, found {current.revision}"
                    )
            self.delete_locked(project_id, dataset_id)

    def delete_locked(self, project_id: str, dataset_id: str) -> None:
        self._processor(project_id).delete(dataset_id)
