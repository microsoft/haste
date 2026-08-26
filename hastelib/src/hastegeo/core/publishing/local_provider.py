from pathlib import PurePosixPath
from typing import Optional

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..models.publishing import (
    ArtifactBundle,
    ArtifactKind,
    ProviderInfo,
    PublishedArtifact,
    PublishedDataset,
    PublishRequest,
    PublishResult,
)
from .base import PublishingProvider
from .open_data import validate_source_refs


class LocalPublishingProvider(PublishingProvider):
    """Publish immutable copies into HASTE-managed artifact storage."""

    def __init__(
        self,
        config: Optional[Config] = None,
        artifact_storage: Optional[UnifiedArtifactStorage] = None,
    ) -> None:
        self.config = config or Config()
        self.artifact_storage = artifact_storage or UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )

    @property
    def info(self) -> ProviderInfo:
        enabled = self.config.publishing_config["publishing_enabled"]
        return ProviderInfo(
            id="local",
            displayName="Local (In App storage)",
            description="Immutable copy in the app's storage",
            isEnabled=enabled,
            isConfigured=True,
            disabledReason=None if enabled else "Publishing is disabled",
            supportedArtifactKinds=list(ArtifactKind),
        )

    def validate(
        self, request: PublishRequest, source: ArtifactBundle
    ) -> None:
        if not source.selectedArtifacts:
            raise ValueError("Select at least one artifact to publish")
        supported = set(self.info.supportedArtifactKinds)
        unsupported = set(request.artifacts) - supported
        if unsupported:
            names = ", ".join(sorted(kind.value for kind in unsupported))
            raise ValueError(f"Unsupported Local artifacts: {names}")

    def start_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        prefix = self._dataset_prefix(dataset)
        published_artifacts = []
        for artifact in source.selectedArtifacts:
            file_name = PurePosixPath(artifact.sourcePath).name
            destination = f"{prefix}/{artifact.kind.value}_{file_name}"
            published_path = self.artifact_storage.copy_artifact(
                artifact.sourcePath,
                destination,
                artifact.sourceEtag,
            )
            published_artifacts.append(
                PublishedArtifact(
                    **artifact.model_dump(),
                    publishedPath=published_path,
                )
            )

        report_name = f"assessment_report_{dataset.datasetId}.json"
        report_path = self.artifact_storage.store_artifact(
            artifact_name=report_name,
            data=dataset.assessmentSummary,
            namespace=prefix.split("/"),
        )
        provider_metadata = {"assessmentReportPath": report_path}

        # Source-imagery provenance sidecar — the Local analogue of the STAC
        # derived_from links (there is no catalog to surface them on). Same
        # fail-safe validation; written only when there is provenance to record.
        refs = validate_source_refs(dataset.sourceImageryReferences)
        citation = (dataset.sourceImageryCitation or "").strip() or None
        if refs or citation:
            sidecar_path = self.artifact_storage.store_artifact(
                artifact_name="source_imagery.json",
                data={
                    "sourceImageryReferences": [
                        ref.model_dump() for ref in refs
                    ],
                    "sourceImageryCitation": citation,
                    "note": (
                        "Source imagery provenance for the assets in this "
                        "bundle."
                    ),
                },
                namespace=prefix.split("/"),
            )
            provider_metadata["sourceImageryPath"] = sidecar_path

        return PublishResult(
            artifacts=published_artifacts,
            providerMetadata=provider_metadata,
            isComplete=True,
        )

    def continue_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        raise RuntimeError(
            "Local publishing does not have a continuation step"
        )

    def start_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        deleted_count = self.artifact_storage.delete_prefix(
            self._dataset_prefix(dataset)
        )
        return PublishResult(
            providerMetadata={"deletedArtifactCount": deleted_count},
            isComplete=True,
        )

    def continue_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        return self.start_unpublish(dataset)

    @staticmethod
    def _dataset_prefix(dataset: PublishedDataset) -> str:
        # Flat `published/<datasetId>` prefix (datasetId is a UUID, so globally
        # unique). Keeping the blob path to three in-container segments
        # (published/<datasetId>/<file>) lets the UI serve downloads through the
        # existing managed-identity storage proxy (get-artifacts), which the
        # VNet-only storage account requires — a direct blob SAS from the browser
        # is denied by the storage firewall.
        return f"published/{dataset.datasetId}"
