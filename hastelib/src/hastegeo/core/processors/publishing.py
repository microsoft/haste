import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from ..config import Config
from ..models.publishing import (
    ArtifactBundle,
    PublishDatasetOptions,
    PublishedDataset,
    PublishOperation,
    PublishQueueMessage,
    PublishRequest,
    PublishStatus,
    compute_request_fingerprint,
    derive_dataset_id,
)
from ..publishing.lease import LeaseUnavailableError
from ..publishing.registry import PublishingProviderRegistry
from ..publishing.repository import (
    PublishingConflictError,
    PublishingRepository,
)
from ..publishing.source import PublishingSourceResolver
from ..utils.logs import Logger


class PublishingDisabledError(RuntimeError):
    pass


class PublishingPermissionError(PermissionError):
    pass


class PublishingStateConflictError(RuntimeError):
    pass


class PublishingSizeLimitError(ValueError):
    pass


class PublishingDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedPublish:
    request: PublishRequest
    publisher_id: str
    dataset_id: Any
    request_fingerprint: str
    publisher_name: Optional[str] = None
    existing: Optional[PublishedDataset] = None
    options: Optional[PublishDatasetOptions] = None
    bundle: Optional[ArtifactBundle] = None


def _utc_timestamp(now: Optional[datetime] = None) -> str:
    timestamp = now or datetime.now(timezone.utc)
    return (
        timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )


def _sanitize_status_message(error: Exception) -> str:
    message = re.sub(r"https?://\S+", "[url redacted]", str(error))
    message = re.sub(
        r"(?i)(authorization\s*:\s*bearer)\s+[^\s,;]+",
        r"\1 [redacted]",
        message,
    )
    message = re.sub(
        r"""(?ix)
        (["']?(?:access_token|refresh_token|client_secret)["']?
        \s*[:=]\s*["']?)[^"'\s,}]+
        """,
        r"\1[redacted]",
        message,
    )
    message = re.sub(
        r"(?i)(sig|token|secret|key)=[^&\s]+",
        r"\1=[redacted]",
        message,
    )
    return message[:500] or type(error).__name__


class PublishingProcessor:
    """Orchestrate the generic publishing lifecycle in bounded queue steps."""

    def __init__(
        self,
        config: Optional[Config] = None,
        repository: Optional[PublishingRepository] = None,
        source_resolver: Optional[PublishingSourceResolver] = None,
        registry: Optional[PublishingProviderRegistry] = None,
        queue_handler: Any = None,
    ) -> None:
        self.config = config or Config()
        self.repository = repository or PublishingRepository(self.config)
        self.source_resolver = source_resolver or PublishingSourceResolver(
            self.config
        )
        if registry is None:
            from ..publishing.local_provider import LocalPublishingProvider

            def planetary_computer_factory():
                from ..publishing.planetary_computer_provider import (
                    PlanetaryComputerPublishingProvider,
                )

                return PlanetaryComputerPublishingProvider(
                    config=self.config,
                    artifact_storage=self.source_resolver.artifact_storage,
                )

            registry = PublishingProviderRegistry(
                self.config,
                factories={
                    "local": lambda: LocalPublishingProvider(
                        config=self.config,
                        artifact_storage=self.source_resolver.artifact_storage,
                    ),
                    "planetary_computer": planetary_computer_factory,
                },
            )
        self.registry = registry
        self.queue_handler = queue_handler
        self.logger = Logger.get_logger(__name__)

    def create(
        self,
        request: PublishRequest,
        publisher_id: str,
        assessment_summary: Optional[Dict[str, Any]] = None,
        publisher_name: Optional[str] = None,
    ) -> PublishedDataset:
        prepared = self.prepare_create(
            request, publisher_id, publisher_name
        )
        return self.create_prepared(prepared, assessment_summary)

    def prepare_create(
        self,
        request: PublishRequest,
        publisher_id: str,
        publisher_name: Optional[str] = None,
    ) -> PreparedPublish:
        self._require_enabled()
        dataset_id = derive_dataset_id(request.projectId, request.requestId)
        request_fingerprint = compute_request_fingerprint(
            request, publisher_id
        )
        try:
            existing = self.repository.load(
                str(request.projectId), str(dataset_id)
            )
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.requestFingerprint != request_fingerprint:
                raise PublishingConflictError(
                    "requestId was already used with different publish values"
                )
            self._audit(existing, "publish_replayed", publisher_id)
            return PreparedPublish(
                request=request,
                publisher_id=publisher_id,
                dataset_id=dataset_id,
                request_fingerprint=request_fingerprint,
                publisher_name=publisher_name,
                existing=existing,
            )

        provider_info = self.registry.get_info(request.target.value)
        if not provider_info.isEnabled or not provider_info.isConfigured:
            raise PublishingDisabledError(
                provider_info.disabledReason or "Provider is unavailable"
            )
        unsupported = set(request.artifacts) - set(
            provider_info.supportedArtifactKinds
        )
        if unsupported:
            kinds = ", ".join(sorted(kind.value for kind in unsupported))
            raise ValueError(
                f"Provider {request.target.value} does not support: {kinds}"
            )

        options = self.source_resolver.resolve_options(
            str(request.projectId), request.imageLayerId, request.modelId
        )
        bundle = self.source_resolver.resolve_bundle(
            request,
            supporting_kinds=provider_info.requiredSupportingArtifactKinds,
            options=options,
        )
        total_bytes = sum(
            artifact.sizeBytes or 0 for artifact in bundle.selectedArtifacts
        )
        if total_bytes > self.config.publishing_config["max_total_bytes"]:
            raise PublishingSizeLimitError(
                "Selected artifacts exceed PUBLISH_MAX_TOTAL_BYTES"
            )

        provider = self.registry.resolve(request.target.value)
        provider.validate(request, bundle)
        return PreparedPublish(
            request=request,
            publisher_id=publisher_id,
            dataset_id=dataset_id,
            request_fingerprint=request_fingerprint,
            publisher_name=publisher_name,
            options=options,
            bundle=bundle,
        )

    def create_prepared(
        self,
        prepared: PreparedPublish,
        assessment_summary: Optional[Dict[str, Any]] = None,
    ) -> PublishedDataset:
        self._require_enabled()
        if prepared.existing is not None:
            return prepared.existing
        if prepared.options is None or prepared.bundle is None:
            raise ValueError("Prepared publish is incomplete")

        request = prepared.request
        options = prepared.options
        bundle = prepared.bundle
        dataset_id = prepared.dataset_id
        request_fingerprint = prepared.request_fingerprint
        now = _utc_timestamp()
        dataset = PublishedDataset(
            datasetId=dataset_id,
            requestId=request.requestId,
            requestFingerprint=request_fingerprint,
            name=request.name,
            description=request.description or "",
            interactiveViewerUrl=request.interactiveViewerUrl,
            projectId=request.projectId,
            projectName=options.projectName,
            imageLayerId=request.imageLayerId,
            imageLayerName=options.imageLayerName,
            modelId=request.modelId,
            modelName=options.modelName,
            imagerySources=options.imagerySources,
            sourceImageryReferences=options.sourceImageryReferences,
            sourceImageryCitation=request.sourceImageryCitation,
            target=request.target,
            status=PublishStatus.PENDING,
            publishedByUser=prepared.publisher_id.strip().lower(),
            publishedByName=prepared.publisher_name,
            createdDate=now,
            updatedDate=now,
            queueDispatchedAt=now,
            selectedArtifactKinds=request.artifacts,
            sourceArtifacts=(
                bundle.selectedArtifacts + bundle.supportingArtifacts
            ),
            assessmentSummary=assessment_summary or {},
        )
        try:
            with self.repository.project_lock(str(request.projectId)):
                self.source_resolver.ensure_project_exists(
                    str(request.projectId)
                )
                stored, created = self.repository.create_or_replay_locked(
                    dataset
                )
        except LeaseUnavailableError as error:
            try:
                existing = self.repository.load(
                    str(request.projectId), str(dataset_id)
                )
            except FileNotFoundError:
                raise PublishingStateConflictError(
                    "Project publishing state is changing; retry the request"
                ) from error
            if existing.requestFingerprint != request_fingerprint:
                raise PublishingConflictError(
                    "requestId was already used with different publish values"
                ) from error
            return existing
        if not created:
            return stored
        try:
            self._enqueue(stored, visibility_timeout=5)
            self._audit(stored, "publish_queued", prepared.publisher_id)
            return stored
        except Exception as error:
            failed = stored.model_copy(
                update={
                    "status": PublishStatus.FAILED,
                    "statusMessage": _sanitize_status_message(error),
                    "updatedDate": _utc_timestamp(),
                }
            )
            try:
                self.repository.update(
                    failed, expected_revision=stored.revision
                )
            except Exception as persistence_error:
                self.logger.error(
                    "Failed to persist publish dispatch failure for %s: %s",
                    stored.datasetId,
                    type(persistence_error).__name__,
                )
            raise PublishingDependencyError(
                "Unable to enqueue publishing operation"
            ) from error

    def retry(
        self,
        project_id: str,
        dataset_id: str,
        caller_id: str,
        is_admin: bool = False,
    ) -> PublishedDataset:
        self._require_enabled()
        dataset = self.repository.load(project_id, dataset_id)
        self._require_owner(dataset, caller_id, is_admin)
        if dataset.status == PublishStatus.FAILED:
            status = PublishStatus.PENDING
            operation = PublishOperation.PUBLISH
        elif dataset.status == PublishStatus.UNPUBLISH_FAILED:
            status = PublishStatus.UNPUBLISH_PENDING
            operation = PublishOperation.UNPUBLISH
        else:
            raise PublishingStateConflictError(
                f"Cannot retry dataset in status {dataset.status.value}"
            )
        provider = self.registry.resolve(dataset.target.value)
        prepare_retry = getattr(provider, "prepare_retry", None)
        provider_metadata = (
            prepare_retry(dataset, operation)
            if callable(prepare_retry)
            else dict(dataset.providerMetadata)
        )
        pending = dataset.model_copy(
            update={
                "status": status,
                "lastOperation": operation,
                "attempt": dataset.attempt + 1,
                "statusMessage": "",
                "queueDispatchedAt": _utc_timestamp(),
                "reconciledAttempt": None,
                "updatedDate": _utc_timestamp(),
                "providerMetadata": dict(provider_metadata),
            }
        )
        updated = self.repository.update(
            pending, expected_revision=dataset.revision
        )
        try:
            self._enqueue(updated, visibility_timeout=5)
            self._audit(updated, "publish_retry_queued", caller_id)
        except Exception as error:
            failed_status = (
                PublishStatus.FAILED
                if operation == PublishOperation.PUBLISH
                else PublishStatus.UNPUBLISH_FAILED
            )
            self._persist_dispatch_failure(updated, failed_status)
            raise PublishingDependencyError(
                "Unable to enqueue publishing retry"
            ) from error
        return updated

    def update_metadata(
        self,
        project_id: str,
        dataset_id: str,
        caller_id: str,
        is_admin: bool,
        fields: dict,
    ) -> PublishedDataset:
        """Edit user-authored metadata; push to the live target if published.

        ``fields`` carries only the keys the caller supplied (name /
        description / interactiveViewerUrl), already validated/normalized.
        """
        self._require_enabled()
        dataset = self.repository.load(project_id, dataset_id)
        self._require_owner(dataset, caller_id, is_admin)
        editable = {
            "name",
            "description",
            "interactiveViewerUrl",
            "sourceImageryCitation",
        }
        updates = {k: v for k, v in fields.items() if k in editable}
        if updates.get("description") is None and "description" in updates:
            updates["description"] = ""
        if (
            not updates.get("sourceImageryCitation")
            and "sourceImageryCitation" in updates
        ):
            updates["sourceImageryCitation"] = None
        if not updates:
            return dataset
        updates["updatedDate"] = _utc_timestamp()
        edited = dataset.model_copy(update=updates)
        saved = self.repository.update(
            edited, expected_revision=dataset.revision
        )
        if saved.status == PublishStatus.PUBLISHED:
            provider = self.registry.resolve(saved.target.value)
            provider.update_published_metadata(saved)
        self._audit(saved, "metadata_updated", caller_id)
        return saved

    def request_unpublish(
        self,
        project_id: str,
        dataset_id: str,
        caller_id: str,
        is_admin: bool = False,
    ) -> PublishedDataset:
        self._require_enabled()
        dataset = self.repository.load(project_id, dataset_id)
        self._require_owner(dataset, caller_id, is_admin)
        if dataset.status in {
            PublishStatus.PENDING,
            PublishStatus.IN_PROGRESS,
            PublishStatus.UNPUBLISH_PENDING,
            PublishStatus.UNPUBLISHING,
        }:
            raise PublishingStateConflictError(
                f"Cannot unpublish dataset in status {dataset.status.value}"
            )
        pending = dataset.model_copy(
            update={
                "status": PublishStatus.UNPUBLISH_PENDING,
                "lastOperation": PublishOperation.UNPUBLISH,
                "attempt": dataset.attempt + 1,
                "statusMessage": "",
                "queueDispatchedAt": _utc_timestamp(),
                "reconciledAttempt": None,
                "updatedDate": _utc_timestamp(),
            }
        )
        updated = self.repository.update(
            pending, expected_revision=dataset.revision
        )
        try:
            self._enqueue(updated, visibility_timeout=5)
            self._audit(updated, "unpublish_queued", caller_id)
        except Exception as error:
            self._persist_dispatch_failure(
                updated, PublishStatus.UNPUBLISH_FAILED
            )
            raise PublishingDependencyError(
                "Unable to enqueue unpublish operation"
            ) from error
        return updated

    def run_step(
        self, message: PublishQueueMessage
    ) -> Optional[PublishedDataset]:
        project_id = str(message.projectId)
        dataset_id = str(message.datasetId)
        try:
            with self.repository.operation_lock(
                project_id, dataset_id
            ) as lease:
                dataset = self.repository.load(project_id, dataset_id)
                if (
                    dataset.attempt != message.attempt
                    or dataset.lastOperation != message.operation
                ):
                    return dataset
                if dataset.reconciledAttempt == message.attempt:
                    dataset = self.repository.update_locked(
                        dataset.model_copy(
                            update={
                                "reconciledAttempt": None,
                                "updatedDate": _utc_timestamp(),
                            }
                        ),
                        dataset.revision,
                    )
                if message.operation == PublishOperation.PUBLISH:
                    return self._run_publish_step(dataset, lease)
                return self._run_unpublish_step(dataset, lease)
        except LeaseUnavailableError:
            self.logger.info(
                "Publishing operation already claimed for dataset %s",
                dataset_id,
            )
            return None

    def list_datasets(
        self,
        project_id: Optional[str] = None,
        target=None,
        status=None,
    ) -> list[PublishedDataset]:
        return self.repository.list_all(
            project_id=project_id,
            target=target,
            status=status,
        )

    def list_datasets_page(self, **kwargs):
        return self.repository.list_page(**kwargs)

    def get_dataset(
        self, project_id: str, dataset_id: str
    ) -> PublishedDataset:
        return self.repository.load(project_id, dataset_id)

    def _run_publish_step(
        self, dataset: PublishedDataset, lease: Any
    ) -> PublishedDataset:
        if dataset.status not in {
            PublishStatus.PENDING,
            PublishStatus.IN_PROGRESS,
        }:
            return dataset
        try:
            provider = self.registry.resolve(dataset.target.value)
            request = self._request_from_dataset(dataset)
            info = self.registry.get_info(dataset.target.value)
            bundle = self.source_resolver.resolve_bundle(
                request,
                supporting_kinds=info.requiredSupportingArtifactKinds,
            )
            self._validate_worker_bundle(dataset, bundle)
            if dataset.status == PublishStatus.PENDING:
                current = self.repository.update_locked(
                    dataset.model_copy(
                        update={
                            "status": PublishStatus.IN_PROGRESS,
                            "updatedDate": _utc_timestamp(),
                        }
                    ),
                    dataset.revision,
                )
                self._renew_lease(lease)
            else:
                current = dataset
            if current.target.value == "planetary_computer":
                try:
                    with self.repository.project_lock(str(current.projectId)):
                        result = self._run_provider_publish_step(
                            provider,
                            current,
                            bundle,
                        )
                except LeaseUnavailableError:
                    self.logger.info(
                        "Planetary Computer collection update is busy for "
                        "project %s",
                        current.projectId,
                    )
                    self._enqueue(current, visibility_timeout=30)
                    return current
            else:
                result = self._run_provider_publish_step(
                    provider,
                    current,
                    bundle,
                )
            self._renew_lease(lease)
            if not result.isComplete:
                continued = current.model_copy(
                    update={
                        "providerMetadata": {
                            **current.providerMetadata,
                            **result.providerMetadata,
                            "continuationToken": result.continuationToken,
                        },
                        "updatedDate": _utc_timestamp(),
                    }
                )
                updated = self.repository.update_locked(
                    continued, current.revision
                )
                self._enqueue(updated, visibility_timeout=30)
                return updated
            completed = current.model_copy(
                update={
                    "status": PublishStatus.PUBLISHED,
                    "statusMessage": "",
                    "publishedDate": _utc_timestamp(),
                    "updatedDate": _utc_timestamp(),
                    "artifacts": result.artifacts,
                    "links": result.links,
                    "providerMetadata": result.providerMetadata,
                }
            )
            completed = self.repository.update_locked(
                completed, current.revision
            )
            self._audit(completed, "publish_completed")
            return completed
        except Exception as error:
            latest = self.repository.load(
                str(dataset.projectId), str(dataset.datasetId)
            )
            failed = latest.model_copy(
                update={
                    "status": PublishStatus.FAILED,
                    "statusMessage": _sanitize_status_message(error),
                    "updatedDate": _utc_timestamp(),
                }
            )
            failed = self.repository.update_locked(failed, latest.revision)
            self._audit(failed, "publish_failed")
            raise

    @staticmethod
    def _run_provider_publish_step(
        provider: Any,
        dataset: PublishedDataset,
        bundle: ArtifactBundle,
    ) -> Any:
        if dataset.providerMetadata.get("continuationToken"):
            return provider.continue_publish(dataset, bundle)
        return provider.start_publish(dataset, bundle)

    def _run_unpublish_step(
        self, dataset: PublishedDataset, lease: Any
    ) -> Optional[PublishedDataset]:
        if dataset.status not in {
            PublishStatus.UNPUBLISH_PENDING,
            PublishStatus.UNPUBLISHING,
        }:
            return dataset
        try:
            provider = self.registry.resolve(dataset.target.value)
            if dataset.status == PublishStatus.UNPUBLISH_PENDING:
                current = self.repository.update_locked(
                    dataset.model_copy(
                        update={
                            "status": PublishStatus.UNPUBLISHING,
                            "updatedDate": _utc_timestamp(),
                        }
                    ),
                    dataset.revision,
                )
                self._renew_lease(lease)
                result = provider.start_unpublish(current)
            else:
                current = dataset
                if current.providerMetadata.get("continuationToken"):
                    result = provider.continue_unpublish(current)
                else:
                    result = provider.start_unpublish(current)
            self._renew_lease(lease)
            if not result.isComplete:
                continued = current.model_copy(
                    update={
                        "providerMetadata": {
                            **current.providerMetadata,
                            **result.providerMetadata,
                            "continuationToken": result.continuationToken,
                        },
                        "updatedDate": _utc_timestamp(),
                    }
                )
                updated = self.repository.update_locked(
                    continued, current.revision
                )
                self._enqueue(updated, visibility_timeout=30)
                return updated
            self.repository.delete_locked(
                str(current.projectId), str(current.datasetId)
            )
            self._audit(current, "unpublish_completed")
            return None
        except Exception as error:
            latest = self.repository.load(
                str(dataset.projectId), str(dataset.datasetId)
            )
            failed = latest.model_copy(
                update={
                    "status": PublishStatus.UNPUBLISH_FAILED,
                    "statusMessage": _sanitize_status_message(error),
                    "updatedDate": _utc_timestamp(),
                }
            )
            failed = self.repository.update_locked(failed, latest.revision)
            self._audit(failed, "unpublish_failed")
            raise

    def mark_poisoned(self, message: PublishQueueMessage) -> PublishedDataset:
        project_id = str(message.projectId)
        dataset_id = str(message.datasetId)
        with self.repository.operation_lock(project_id, dataset_id):
            dataset = self.repository.load(project_id, dataset_id)
            expected_statuses = (
                {PublishStatus.PENDING, PublishStatus.IN_PROGRESS}
                if message.operation == PublishOperation.PUBLISH
                else {
                    PublishStatus.UNPUBLISH_PENDING,
                    PublishStatus.UNPUBLISHING,
                }
            )
            if (
                dataset.attempt != message.attempt
                or dataset.lastOperation != message.operation
                or dataset.status not in expected_statuses
            ):
                return dataset
            status = (
                PublishStatus.FAILED
                if message.operation == PublishOperation.PUBLISH
                else PublishStatus.UNPUBLISH_FAILED
            )
            failed = dataset.model_copy(
                update={
                    "status": status,
                    "statusMessage": "Publishing operation moved to poison queue",
                    "updatedDate": _utc_timestamp(),
                }
            )
            failed = self.repository.update_locked(failed, dataset.revision)
            self._audit(failed, "operation_poisoned")
            return failed

    def reconcile_stale(
        self,
        now: Optional[datetime] = None,
        stale_after: timedelta = timedelta(minutes=2),
    ) -> int:
        current_time = now or datetime.now(timezone.utc)
        nonterminal = {
            PublishStatus.PENDING,
            PublishStatus.IN_PROGRESS,
            PublishStatus.UNPUBLISH_PENDING,
            PublishStatus.UNPUBLISHING,
        }
        requeued = 0
        for candidate in self.repository.list_for_reconciliation():
            if candidate.status not in nonterminal:
                continue
            updated_at = datetime.fromisoformat(
                candidate.updatedDate.replace("Z", "+00:00")
            )
            if current_time - updated_at < stale_after:
                continue
            project_id = str(candidate.projectId)
            dataset_id = str(candidate.datasetId)
            try:
                with self.repository.operation_lock(project_id, dataset_id):
                    dataset = self.repository.load(project_id, dataset_id)
                    updated_at = datetime.fromisoformat(
                        dataset.updatedDate.replace("Z", "+00:00")
                    )
                    if (
                        dataset.status not in nonterminal
                        or current_time - updated_at < stale_after
                        or dataset.reconciledAttempt == dataset.attempt
                    ):
                        continue
                    self._enqueue(dataset, visibility_timeout=5)
                    reconciled = dataset.model_copy(
                        update={
                            "queueDispatchedAt": current_time.isoformat(),
                            "reconciledAttempt": dataset.attempt,
                            "updatedDate": current_time.isoformat(),
                        }
                    )
                    reconciled = self.repository.update_locked(
                        reconciled, dataset.revision
                    )
                    self._audit(reconciled, "operation_reconciled")
                    requeued += 1
            except LeaseUnavailableError:
                self.logger.info(
                    "Skipping reconciliation for claimed dataset %s",
                    dataset_id,
                )
        return requeued

    def get_download_urls(
        self, project_id: str, dataset_id: str
    ) -> Dict[str, str]:
        dataset = self.repository.load(project_id, dataset_id)
        if (
            dataset.target.value != "local"
            or dataset.status != PublishStatus.PUBLISHED
        ):
            return {}
        ttl = self.config.publishing_config["download_sas_minutes"]
        return {
            artifact.kind.value: self.source_resolver.artifact_storage.get_scoped_download_url(
                artifact.publishedPath, expires_minutes=ttl
            )
            for artifact in dataset.artifacts
        }

    def _enqueue(
        self, dataset: PublishedDataset, visibility_timeout: int
    ) -> None:
        message = PublishQueueMessage(
            datasetId=dataset.datasetId,
            projectId=dataset.projectId,
            operation=dataset.lastOperation,
            attempt=dataset.attempt,
        )
        self._get_queue_handler().put_message(
            message.model_dump_json(),
            visibility_timeout=visibility_timeout,
        )

    def _get_queue_handler(self):
        if self.queue_handler is None:
            from ..utils.queues import AzureQueueHandler

            queue = self.config.queue_config
            self.queue_handler = AzureQueueHandler(
                connection_string=queue["queue_connection_string"],
                queue_name=queue["publish_queue_name"],
                account_url=queue["queue_account_url"],
            )
        return self.queue_handler

    @staticmethod
    def _request_from_dataset(dataset: PublishedDataset) -> PublishRequest:
        return PublishRequest(
            requestId=dataset.requestId,
            projectId=dataset.projectId,
            imageLayerId=dataset.imageLayerId,
            modelId=dataset.modelId,
            name=dataset.name,
            description=dataset.description,
            target=dataset.target,
            artifacts=dataset.selectedArtifactKinds,
        )

    @staticmethod
    def _renew_lease(lease: Any) -> None:
        renew = getattr(lease, "renew", None)
        if callable(renew):
            renew()

    def _require_enabled(self) -> None:
        if not self.config.publishing_config["publishing_enabled"]:
            raise PublishingDisabledError("Publishing is disabled")

    def _audit(
        self,
        dataset: PublishedDataset,
        event: str,
        actor: Optional[str] = None,
    ) -> None:
        self.logger.info(
            "Publishing audit event=%s dataset=%s project=%s target=%s "
            "operation=%s attempt=%s actor=%s status=%s",
            event,
            dataset.datasetId,
            dataset.projectId,
            dataset.target.value,
            dataset.lastOperation.value,
            dataset.attempt,
            (actor or "system").strip().lower(),
            dataset.status.value,
        )

    def _persist_dispatch_failure(
        self,
        dataset: PublishedDataset,
        status: PublishStatus,
    ) -> PublishedDataset:
        failed = dataset.model_copy(
            update={
                "status": status,
                "statusMessage": "Publishing queue is unavailable",
                "queueDispatchedAt": None,
                "updatedDate": _utc_timestamp(),
            }
        )
        return self.repository.update(
            failed, expected_revision=dataset.revision
        )

    def _validate_worker_bundle(
        self, dataset: PublishedDataset, bundle: Any
    ) -> None:
        total_bytes = sum(
            artifact.sizeBytes or 0 for artifact in bundle.selectedArtifacts
        )
        if total_bytes > self.config.publishing_config["max_total_bytes"]:
            raise PublishingSizeLimitError(
                "Selected artifacts exceed PUBLISH_MAX_TOTAL_BYTES"
            )

        expected = {
            artifact.kind: artifact for artifact in dataset.sourceArtifacts
        }
        if not expected:
            return
        current_artifacts = (
            bundle.selectedArtifacts + bundle.supportingArtifacts
        )
        current = {artifact.kind: artifact for artifact in current_artifacts}
        if set(expected) != set(current):
            raise PublishingStateConflictError(
                "Source artifact selection changed after publishing was queued"
            )
        for kind, expected_artifact in expected.items():
            current_artifact = current[kind]
            if (
                expected_artifact.sourcePath != current_artifact.sourcePath
                or expected_artifact.sizeBytes != current_artifact.sizeBytes
                or expected_artifact.mediaType != current_artifact.mediaType
                or expected_artifact.sourceEtag != current_artifact.sourceEtag
            ):
                raise PublishingStateConflictError(
                    f"Source artifact changed after publishing was queued: {kind.value}"
                )

    @staticmethod
    def _require_owner(
        dataset: PublishedDataset, caller_id: str, is_admin: bool
    ) -> None:
        if is_admin:
            return
        if dataset.publishedByUser != caller_id.strip().lower():
            raise PublishingPermissionError(
                "Only the publisher or an administrator may perform this action"
            )
