from abc import ABC, abstractmethod

from ..models.publishing import (
    ArtifactBundle,
    ProviderInfo,
    PublishedDataset,
    PublishOperation,
    PublishRequest,
    PublishResult,
)


class PublishingProvider(ABC):
    """Provider contract for bounded, replay-safe publishing steps."""

    @property
    @abstractmethod
    def info(self) -> ProviderInfo:
        pass  # pragma: no cover

    @abstractmethod
    def validate(
        self, request: PublishRequest, source: ArtifactBundle
    ) -> None:
        pass  # pragma: no cover

    def prepare_retry(
        self,
        dataset: PublishedDataset,
        operation: PublishOperation,
    ) -> dict:
        """Return provider metadata safe for a new operation attempt."""
        return dict(dataset.providerMetadata)

    def update_published_metadata(self, dataset: PublishedDataset) -> None:
        """Push edited metadata (name/description/viewer) to the live target.

        No-op by default; providers backed by an external catalog override it.
        """
        return None

    @abstractmethod
    def start_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        pass  # pragma: no cover

    @abstractmethod
    def continue_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        pass  # pragma: no cover

    @abstractmethod
    def start_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        pass  # pragma: no cover

    @abstractmethod
    def continue_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        pass  # pragma: no cover
