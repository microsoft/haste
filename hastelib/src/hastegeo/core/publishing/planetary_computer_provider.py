import json
import math
import re
import tempfile
from contextlib import contextmanager
from enum import Enum
from http.client import HTTPSConnection
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Optional
from urllib.parse import quote, unquote, urlparse

from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry import shape

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..models.publishing import (
    ArtifactBundle,
    ArtifactKind,
    ProviderInfo,
    PublishedArtifact,
    PublishedDataset,
    PublishOperation,
    PublishRequest,
    PublishResult,
    SourceArtifact,
)
from ..utils.gdal_security import harden_gdal
from ..utils.logs import Logger
from .base import PublishingProvider
from .planetary_computer_transport import (
    PlanetaryComputerOperationError,
    PlanetaryComputerRestAdapter,
)
from .stac import (
    ASSET_KEYS,
    DEFAULT_THUMBNAIL_MEDIA_TYPE,
    THUMBNAIL_ASSET_KEY,
    StacObjects,
    build_collection_id,
    build_item_id,
    build_stac_objects,
    rebuild_collection_after_removal,
    serialize_stac_objects,
    validate_stac_objects,
)

PC_API_VERSION = "2026-04-15"
MAX_VALID_MASK_BYTES = 32 * 1024 * 1024
AZURE_BLOB_HOST_SUFFIXES = (
    ".blob.core.windows.net",
    ".blob.core.usgovcloudapi.net",
)
_THUMBNAIL_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class PlanetaryComputerProviderError(RuntimeError):
    """Raised when Planetary Computer publishing cannot safely continue."""


class PlanetaryComputerPhase(str, Enum):
    COLLECTION_OPERATION = "collection_operation"
    COLLECTION_VERIFY = "collection_verify"
    ITEM_OPERATION = "item_operation"
    ITEM_VERIFY = "item_verify"
    ITEM_REPLACE_DELETE_OPERATION = "item_replace_delete_operation"
    ITEM_REPLACE_DELETE_VERIFY = "item_replace_delete_verify"
    DELETE_OPERATION = "delete_operation"
    DELETE_VERIFY = "delete_verify"
    DRAIN_COLLECTION = "drain_collection"
    DRAIN_ITEM = "drain_item"
    DRAIN_DELETE = "drain_delete"
    DELETE_DISCOVER = "delete_discover"
    DELETE_COLLECTION_OPERATION = "delete_collection_operation"
    DELETE_COLLECTION_VERIFY = "delete_collection_verify"


class PlanetaryComputerPublishingProvider(PublishingProvider):
    """Publish HASTE vector outputs into a Planetary Computer GeoCatalog."""

    def __init__(
        self,
        config: Optional[Config] = None,
        artifact_storage: Optional[UnifiedArtifactStorage] = None,
        sdk_adapter: Optional[PlanetaryComputerRestAdapter] = None,
        json_reader: Optional[
            Callable[[SourceArtifact], Mapping[str, Any]]
        ] = None,
        projection_resolver: Optional[Callable[[SourceArtifact], str]] = None,
        stac_validator: Callable[[StacObjects], None] = validate_stac_objects,
        asset_reachability_checker: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config or Config()
        settings = self.config.publishing_config
        self.endpoint = str(settings.get("pc_geocatalog_url") or "").rstrip(
            "/"
        )
        self.ingestion_source = str(settings.get("pc_ingestion_source") or "")
        self.collection_prefix = str(
            settings.get("pc_collection_prefix") or "haste-"
        )
        self.explorer_url = str(
            settings.get("pc_explorer_url") or self.endpoint
        ).rstrip("/")
        self.max_verify_attempts = int(settings.get("pc_verify_attempts") or 5)
        self.artifact_storage = artifact_storage or UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )
        self.sdk = sdk_adapter or PlanetaryComputerRestAdapter(
            self.endpoint
        )
        self.json_reader = json_reader or self._read_json_artifact
        self.projection_resolver = (
            projection_resolver or self._read_projection_code
        )
        self.stac_validator = stac_validator
        self.asset_reachability_checker = (
            asset_reachability_checker or self._read_signed_asset
        )
        self.logger = Logger.get_logger(__name__)

    @property
    def info(self) -> ProviderInfo:
        settings = self.config.publishing_config
        enabled = bool(settings.get("pc_provider_enabled"))
        # The GeoCatalog URL is what makes the target configurable. An ingestion
        # source is only required for private containers; public containers
        # publish without one (verified against a live GeoCatalog).
        configured = bool(self.endpoint)
        if not enabled:
            disabled_reason = "Disabled by the operator"
        elif not configured:
            disabled_reason = "Planetary Computer is not configured"
        else:
            disabled_reason = None
        return ProviderInfo(
            id="planetary_computer",
            displayName="Planetary Computer",
            description="STAC discovery and vector downloads",
            isEnabled=enabled,
            isConfigured=configured,
            disabledReason=disabled_reason,
            supportedArtifactKinds=[
                ArtifactKind.GPKG,
                ArtifactKind.VALID_MASK,
                ArtifactKind.FOOTPRINTS,
            ],
            requiredSupportingArtifactKinds=[ArtifactKind.VALID_MASK],
        )

    def validate(
        self, request: PublishRequest, source: ArtifactBundle
    ) -> None:
        self._require_configuration()
        self._validate_bundle(source)
        requested = set(request.artifacts)
        selected = {artifact.kind for artifact in source.selectedArtifacts}
        if requested != selected:
            raise ValueError("Selected Planetary Computer artifacts changed")
        for artifact in source.selectedArtifacts:
            self._artifact_href(artifact)

    def prepare_retry(
        self,
        dataset: PublishedDataset,
        operation: PublishOperation,
    ) -> dict[str, Any]:
        metadata = self._stable_metadata(dataset)
        phase = dataset.providerMetadata.get("phase")
        discovery_phases = {
            PlanetaryComputerPhase.COLLECTION_OPERATION.value,
            PlanetaryComputerPhase.COLLECTION_VERIFY.value,
            PlanetaryComputerPhase.ITEM_OPERATION.value,
            PlanetaryComputerPhase.ITEM_VERIFY.value,
            PlanetaryComputerPhase.ITEM_REPLACE_DELETE_OPERATION.value,
            PlanetaryComputerPhase.ITEM_REPLACE_DELETE_VERIFY.value,
            PlanetaryComputerPhase.DRAIN_COLLECTION.value,
            PlanetaryComputerPhase.DRAIN_ITEM.value,
            PlanetaryComputerPhase.DRAIN_DELETE.value,
            PlanetaryComputerPhase.DELETE_DISCOVER.value,
        }
        requires_discovery = bool(
            dataset.providerMetadata.get("cleanupDiscoveryRequired")
            or phase in discovery_phases
        )
        if operation == PublishOperation.UNPUBLISH and requires_discovery:
            metadata.update(
                {
                    "phase": PlanetaryComputerPhase.DELETE_DISCOVER.value,
                    "verificationAttempts": 0,
                    "cleanupDiscoveryRequired": True,
                }
            )
        return metadata

    def start_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        self._require_configuration()
        self._validate_bundle(source)
        if self.ingestion_source:
            self._validate_ingestion_source()
        projection_codes = self._projection_codes(dataset, source)
        collection_id = build_collection_id(dataset, self.collection_prefix)
        item_id = build_item_id(dataset)
        existing_collection = self.sdk.get_collection(collection_id)
        documents = self._build_documents(
            dataset,
            source,
            projection_codes,
            existing_collection,
        )
        metadata = self._operation_metadata(
            dataset,
            projection_codes,
            phase=None,
        )

        if existing_collection is None:
            try:
                operation = self.sdk.start_create_collection(
                    collection_id,
                    documents.collection,
                )
            except Exception as error:
                if not self._is_status(error, 409):
                    raise
                return self._verification_pending(
                    metadata,
                    PlanetaryComputerPhase.COLLECTION_VERIFY,
                    self._collection_href(collection_id),
                )
            if operation.is_complete:
                return self._collection_ready_or_pending(
                    dataset,
                    source,
                    projection_codes,
                    metadata,
                    collection_id,
                    item_id,
                )
            return self._operation_pending(
                metadata,
                PlanetaryComputerPhase.COLLECTION_OPERATION,
                operation.continuation_token,
            )

        self.sdk.replace_collection(
            collection_id,
            documents.collection,
        )
        return self._start_or_complete_item(
            dataset,
            source,
            documents.item,
            metadata,
            collection_id,
            item_id,
        )

    def continue_publish(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> PublishResult:
        self._require_configuration()
        self._validate_bundle(source)
        metadata = dataset.providerMetadata
        phase = self._phase(metadata)
        token = self._continuation_token(metadata)
        collection_id, item_id = self._ids(dataset)
        projection_codes = self._projection_codes(dataset, source)

        if phase == PlanetaryComputerPhase.COLLECTION_OPERATION:
            operation = self.sdk.continue_create_collection(
                collection_id,
                token,
            )
            if not operation.is_complete:
                return self._operation_pending(
                    metadata,
                    phase,
                    operation.continuation_token,
                    count_attempt=True,
                )
            return self._collection_ready_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.COLLECTION_VERIFY:
            return self._collection_ready_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.ITEM_OPERATION:
            operation = self.sdk.continue_create_item(
                collection_id,
                item_id,
                token,
            )
            if not operation.is_complete:
                return self._operation_pending(
                    metadata,
                    phase,
                    operation.continuation_token,
                    count_attempt=True,
                )
            return self._item_complete_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.ITEM_VERIFY:
            return self._item_complete_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.ITEM_REPLACE_DELETE_OPERATION:
            operation = self.sdk.continue_delete_item(
                collection_id,
                item_id,
                token,
            )
            if not operation.is_complete:
                return self._operation_pending(
                    metadata,
                    phase,
                    operation.continuation_token,
                    count_attempt=True,
                )
            return self._replace_delete_complete_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.ITEM_REPLACE_DELETE_VERIFY:
            return self._replace_delete_complete_or_pending(
                dataset,
                source,
                projection_codes,
                metadata,
                collection_id,
                item_id,
            )

        raise PlanetaryComputerProviderError(
            "Planetary Computer publish phase is invalid"
        )

    def start_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        self._require_configuration()
        metadata = dataset.providerMetadata
        phase_value = metadata.get("phase")
        if phase_value in {
            PlanetaryComputerPhase.DELETE_OPERATION.value,
            PlanetaryComputerPhase.DELETE_VERIFY.value,
            PlanetaryComputerPhase.DRAIN_COLLECTION.value,
            PlanetaryComputerPhase.DRAIN_ITEM.value,
            PlanetaryComputerPhase.DRAIN_DELETE.value,
            PlanetaryComputerPhase.DELETE_DISCOVER.value,
            PlanetaryComputerPhase.DELETE_COLLECTION_OPERATION.value,
            PlanetaryComputerPhase.DELETE_COLLECTION_VERIFY.value,
        }:
            return self.continue_unpublish(dataset)

        collection_id, item_id = self._ids(dataset)
        if phase_value == PlanetaryComputerPhase.COLLECTION_OPERATION.value:
            return self._drain_collection_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )
        if phase_value == PlanetaryComputerPhase.COLLECTION_VERIFY.value:
            return self._start_delete_or_discover(
                dataset,
                self._cleanup_discovery_metadata(metadata),
                collection_id,
                item_id,
            )
        if phase_value == PlanetaryComputerPhase.ITEM_OPERATION.value:
            return self._drain_item_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )
        if phase_value == PlanetaryComputerPhase.ITEM_VERIFY.value:
            return self._start_delete_or_discover(
                dataset,
                self._cleanup_discovery_metadata(metadata),
                collection_id,
                item_id,
            )
        if (
            phase_value
            == PlanetaryComputerPhase.ITEM_REPLACE_DELETE_OPERATION.value
        ):
            return self._drain_delete_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )
        if (
            phase_value
            == PlanetaryComputerPhase.ITEM_REPLACE_DELETE_VERIFY.value
        ):
            return self._start_delete_or_discover(
                dataset,
                self._cleanup_discovery_metadata(metadata),
                collection_id,
                item_id,
            )
        stable_metadata = self._stable_metadata(dataset)
        if metadata.get("assetsCopiedToManagedStorage") is True:
            return self._start_delete_or_complete(
                dataset,
                stable_metadata,
                collection_id,
                item_id,
            )
        return self._start_delete_or_discover(
            dataset,
            self._cleanup_discovery_metadata(stable_metadata),
            collection_id,
            item_id,
        )

    def continue_unpublish(self, dataset: PublishedDataset) -> PublishResult:
        self._require_configuration()
        metadata = dataset.providerMetadata
        phase = self._phase(metadata)
        collection_id, item_id = self._ids(dataset)

        if phase == PlanetaryComputerPhase.DELETE_OPERATION:
            operation = self.sdk.continue_delete_item(
                collection_id,
                item_id,
                self._continuation_token(metadata),
            )
            if not operation.is_complete:
                return self._operation_pending(
                    metadata,
                    phase,
                    operation.continuation_token,
                    count_attempt=True,
                )
            return self._delete_complete_or_pending(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DELETE_VERIFY:
            return self._delete_complete_or_pending(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DRAIN_COLLECTION:
            return self._drain_collection_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DRAIN_ITEM:
            return self._drain_item_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DRAIN_DELETE:
            return self._drain_delete_operation(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DELETE_DISCOVER:
            return self._start_delete_or_discover(
                dataset,
                metadata,
                collection_id,
                item_id,
            )

        if phase == PlanetaryComputerPhase.DELETE_COLLECTION_OPERATION:
            try:
                operation = self.sdk.continue_delete_collection(
                    collection_id,
                    self._continuation_token(metadata),
                )
            except PlanetaryComputerOperationError:
                return self._collection_delete_complete_or_pending(
                    dataset, metadata, collection_id
                )
            if not operation.is_complete:
                return self._operation_pending(
                    metadata,
                    PlanetaryComputerPhase.DELETE_COLLECTION_OPERATION,
                    operation.continuation_token,
                    count_attempt=True,
                )
            return self._collection_delete_complete_or_pending(
                dataset, metadata, collection_id
            )

        if phase == PlanetaryComputerPhase.DELETE_COLLECTION_VERIFY:
            return self._collection_delete_complete_or_pending(
                dataset, metadata, collection_id
            )

        raise PlanetaryComputerProviderError(
            "Planetary Computer unpublish phase is invalid"
        )

    def _drain_collection_operation(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        cleanup_metadata = self._cleanup_discovery_metadata(metadata)
        try:
            operation = self.sdk.continue_create_collection(
                collection_id,
                self._continuation_token(metadata),
            )
        except PlanetaryComputerOperationError:
            return self._start_delete_or_discover(
                dataset,
                cleanup_metadata,
                collection_id,
                item_id,
            )
        if not operation.is_complete:
            return self._operation_pending(
                cleanup_metadata,
                PlanetaryComputerPhase.DRAIN_COLLECTION,
                operation.continuation_token,
                count_attempt=True,
            )
        return self._start_delete_or_discover(
            dataset,
            cleanup_metadata,
            collection_id,
            item_id,
        )

    def _drain_item_operation(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        cleanup_metadata = self._cleanup_discovery_metadata(metadata)
        try:
            operation = self.sdk.continue_create_item(
                collection_id,
                item_id,
                self._continuation_token(metadata),
            )
            if not operation.is_complete:
                return self._operation_pending(
                    cleanup_metadata,
                    PlanetaryComputerPhase.DRAIN_ITEM,
                    operation.continuation_token,
                    count_attempt=True,
                )
        except PlanetaryComputerOperationError:
            pass
        return self._start_delete_or_discover(
            dataset,
            cleanup_metadata,
            collection_id,
            item_id,
        )

    def _drain_delete_operation(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        cleanup_metadata = self._cleanup_discovery_metadata(metadata)
        try:
            operation = self.sdk.continue_delete_item(
                collection_id,
                item_id,
                self._continuation_token(metadata),
            )
            if not operation.is_complete:
                return self._operation_pending(
                    cleanup_metadata,
                    PlanetaryComputerPhase.DRAIN_DELETE,
                    operation.continuation_token,
                    count_attempt=True,
                )
        except PlanetaryComputerOperationError:
            pass
        return self._start_delete_or_discover(
            dataset,
            cleanup_metadata,
            collection_id,
            item_id,
        )

    def _start_delete_or_complete(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        if self.sdk.get_item(collection_id, item_id) is None:
            return self._cleanup_collection_or_complete(dataset, collection_id)
        try:
            operation = self.sdk.start_delete_item(collection_id, item_id)
        except Exception as error:
            if self._is_status(error, 404):
                return self._cleanup_collection_or_complete(
                    dataset, collection_id
                )
            if self._is_status(error, 409):
                return self._verification_pending(
                    metadata,
                    PlanetaryComputerPhase.DELETE_VERIFY,
                    self._item_href(collection_id, item_id),
                )
            raise
        return self._operation_pending(
            metadata,
            PlanetaryComputerPhase.DELETE_OPERATION,
            operation.continuation_token,
        )

    def _start_delete_or_discover(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        if self.sdk.get_item(collection_id, item_id) is not None:
            return self._start_delete_or_complete(
                dataset,
                metadata,
                collection_id,
                item_id,
            )
        attempts = int(metadata.get("verificationAttempts") or 0) + 1
        if attempts > self.max_verify_attempts:
            raise PlanetaryComputerProviderError(
                "Planetary Computer cleanup verification timed out"
            )
        updated = dict(metadata)
        updated["phase"] = PlanetaryComputerPhase.DELETE_DISCOVER.value
        updated["verificationAttempts"] = attempts
        updated["operationAttempts"] = 0
        return PublishResult(
            providerMetadata=updated,
            continuationToken=self._item_href(collection_id, item_id),
            isComplete=False,
        )

    @staticmethod
    def _cleanup_discovery_metadata(
        metadata: Mapping[str, Any]
    ) -> dict[str, Any]:
        updated = dict(metadata)
        updated["verificationAttempts"] = 0
        updated["cleanupDiscoveryRequired"] = True
        return updated

    def _cleanup_collection_or_complete(
        self,
        dataset: PublishedDataset,
        collection_id: str,
    ) -> PublishResult:
        # The dataset's item is gone. Collections are per-project and may still
        # hold other datasets, so only delete the collection once no items
        # remain; otherwise refresh its rolling summary to drop this dataset.
        existing = self.sdk.get_collection(collection_id)
        if existing is None:
            return PublishResult(
                providerMetadata=self._stable_metadata(dataset)
            )
        if self.sdk.list_item_ids(collection_id):
            self.sdk.replace_collection(
                collection_id,
                rebuild_collection_after_removal(existing, dataset),
            )
            return PublishResult(
                providerMetadata=self._stable_metadata(dataset)
            )
        return self._start_delete_collection_or_complete(
            dataset,
            self._stable_metadata(dataset),
            collection_id,
        )

    def _start_delete_collection_or_complete(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
    ) -> PublishResult:
        try:
            operation = self.sdk.start_delete_collection(collection_id)
        except Exception as error:
            if self._is_status(error, 404):
                return PublishResult(
                    providerMetadata=self._stable_metadata(dataset)
                )
            if self._is_status(error, 409):
                return self._verification_pending(
                    metadata,
                    PlanetaryComputerPhase.DELETE_COLLECTION_VERIFY,
                    self._collection_href(collection_id),
                )
            raise
        if operation.is_complete:
            return self._collection_delete_complete_or_pending(
                dataset, metadata, collection_id
            )
        return self._operation_pending(
            metadata,
            PlanetaryComputerPhase.DELETE_COLLECTION_OPERATION,
            operation.continuation_token,
        )

    def _collection_delete_complete_or_pending(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
    ) -> PublishResult:
        if self.sdk.get_collection(collection_id) is None:
            return PublishResult(
                providerMetadata=self._stable_metadata(dataset)
            )
        return self._verification_pending(
            metadata,
            PlanetaryComputerPhase.DELETE_COLLECTION_VERIFY,
            self._collection_href(collection_id),
        )

    def _collection_ready_or_pending(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        projection_codes: Mapping[str, str],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        existing_collection = self.sdk.get_collection(collection_id)
        if existing_collection is None:
            return self._verification_pending(
                metadata,
                PlanetaryComputerPhase.COLLECTION_VERIFY,
                self._collection_href(collection_id),
            )
        documents = self._build_documents(
            dataset,
            source,
            projection_codes,
            existing_collection,
        )
        self.sdk.replace_collection(
            collection_id,
            documents.collection,
        )
        return self._start_or_complete_item(
            dataset,
            source,
            documents.item,
            metadata,
            collection_id,
            item_id,
        )

    def _start_or_complete_item(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        expected_item: Mapping[str, Any],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        existing_item = self.sdk.get_item(collection_id, item_id)
        if existing_item is not None:
            try:
                self._verify_item(
                    source,
                    expected_item,
                    existing_item,
                    verify_reachability=False,
                )
            except PlanetaryComputerProviderError:
                return self._start_replace_item_delete(
                    dataset,
                    source,
                    expected_item,
                    metadata,
                    collection_id,
                    item_id,
                )
            return self._completed_publish(
                dataset,
                source,
                expected_item,
                existing_item,
            )
        return self._start_item_operation(
            expected_item,
            metadata,
            collection_id,
            item_id,
        )

    def _start_item_operation(
        self,
        expected_item: Mapping[str, Any],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        try:
            operation = self.sdk.start_create_item(
                collection_id,
                item_id,
                expected_item,
            )
        except Exception as error:
            if not self._is_status(error, 409):
                raise
            return self._verification_pending(
                metadata,
                PlanetaryComputerPhase.ITEM_VERIFY,
                self._item_href(collection_id, item_id),
            )
        return self._operation_pending(
            metadata,
            PlanetaryComputerPhase.ITEM_OPERATION,
            operation.continuation_token,
        )

    def _start_replace_item_delete(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        expected_item: Mapping[str, Any],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        try:
            operation = self.sdk.start_delete_item(collection_id, item_id)
        except Exception as error:
            if self._is_status(error, 404):
                return self._start_item_operation(
                    expected_item,
                    metadata,
                    collection_id,
                    item_id,
                )
            if not self._is_status(error, 409):
                raise
            return self._verification_pending(
                metadata,
                PlanetaryComputerPhase.ITEM_REPLACE_DELETE_VERIFY,
                self._item_href(collection_id, item_id),
            )
        return self._operation_pending(
            metadata,
            PlanetaryComputerPhase.ITEM_REPLACE_DELETE_OPERATION,
            operation.continuation_token,
        )

    def _replace_delete_complete_or_pending(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        projection_codes: Mapping[str, str],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        if self.sdk.get_item(collection_id, item_id) is not None:
            return self._verification_pending(
                metadata,
                PlanetaryComputerPhase.ITEM_REPLACE_DELETE_VERIFY,
                self._item_href(collection_id, item_id),
            )
        return self._collection_ready_or_pending(
            dataset,
            source,
            projection_codes,
            metadata,
            collection_id,
            item_id,
        )

    def _item_complete_or_pending(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        projection_codes: Mapping[str, str],
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        actual_item = self.sdk.get_item(collection_id, item_id)
        if actual_item is None:
            return self._verification_pending(
                metadata,
                PlanetaryComputerPhase.ITEM_VERIFY,
                self._item_href(collection_id, item_id),
            )
        collection = self.sdk.get_collection(collection_id)
        if collection is None:
            raise PlanetaryComputerProviderError(
                "Planetary Computer collection disappeared after ingestion"
            )
        documents = self._build_documents(
            dataset,
            source,
            projection_codes,
            collection,
        )
        return self._completed_publish(
            dataset,
            source,
            documents.item,
            actual_item,
        )

    def _delete_complete_or_pending(
        self,
        dataset: PublishedDataset,
        metadata: Mapping[str, Any],
        collection_id: str,
        item_id: str,
    ) -> PublishResult:
        if self.sdk.get_item(collection_id, item_id) is None:
            return self._cleanup_collection_or_complete(dataset, collection_id)
        return self._verification_pending(
            metadata,
            PlanetaryComputerPhase.DELETE_VERIFY,
            self._item_href(collection_id, item_id),
        )

    def _completed_publish(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        expected_item: Mapping[str, Any],
        actual_item: Mapping[str, Any],
    ) -> PublishResult:
        published_artifacts = self._verify_item(
            source,
            expected_item,
            actual_item,
        )
        collection_id, _ = self._ids(dataset)
        metadata = self._stable_metadata(dataset)
        metadata["assetsCopiedToManagedStorage"] = True
        return PublishResult(
            artifacts=published_artifacts,
            links={
                "stac_collection": self._collection_href(collection_id),
                "explorer": self.explorer_url,
            },
            providerMetadata=metadata,
        )

    def _verify_item(
        self,
        source: ArtifactBundle,
        expected_item: Mapping[str, Any],
        actual_item: Mapping[str, Any],
        *,
        verify_reachability: bool = True,
    ) -> list[PublishedArtifact]:
        if actual_item.get("id") != expected_item.get("id"):
            raise PlanetaryComputerProviderError(
                "Planetary Computer item ID verification failed"
            )
        if actual_item.get("collection") != expected_item.get("collection"):
            raise PlanetaryComputerProviderError(
                "Planetary Computer collection verification failed"
            )
        expected_geometry = expected_item.get("geometry")
        actual_geometry = actual_item.get("geometry")
        if not expected_geometry or not actual_geometry:
            raise PlanetaryComputerProviderError(
                "Planetary Computer item geometry is missing"
            )
        if not shape(expected_geometry).equals(shape(actual_geometry)):
            raise PlanetaryComputerProviderError(
                "Planetary Computer item geometry verification failed"
            )
        self._verify_item_bbox(expected_item, actual_item)
        self._verify_item_properties(expected_item, actual_item)

        expected_assets = expected_item.get("assets") or {}
        actual_assets = actual_item.get("assets") or {}
        if not isinstance(expected_assets, Mapping) or not isinstance(
            actual_assets, Mapping
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer item assets are invalid"
            )
        # The thumbnail is a best-effort preview: don't fail verification (or
        # the whole publish) if the GeoCatalog drops or adds it.
        expected_asset_keys = set(expected_assets) - {THUMBNAIL_ASSET_KEY}
        actual_asset_keys = set(actual_assets) - {THUMBNAIL_ASSET_KEY}
        if actual_asset_keys != expected_asset_keys:
            raise PlanetaryComputerProviderError(
                "Planetary Computer selected assets changed"
            )
        published_artifacts = []
        for artifact in source.selectedArtifacts:
            asset_key = ASSET_KEYS[artifact.kind]
            expected_asset = expected_assets.get(asset_key) or {}
            actual_asset = actual_assets.get(asset_key) or {}
            if not isinstance(actual_asset, Mapping):
                raise PlanetaryComputerProviderError(
                    f"Planetary Computer asset is missing: {asset_key}"
                )
            for field in ("type", "title", "proj:code"):
                if actual_asset.get(field) != expected_asset.get(field):
                    raise PlanetaryComputerProviderError(
                        f"Planetary Computer asset {field} changed: "
                        f"{asset_key}"
                    )
            expected_roles = set(expected_asset.get("roles") or [])
            actual_roles = set(actual_asset.get("roles") or [])
            if expected_roles != actual_roles:
                raise PlanetaryComputerProviderError(
                    f"Planetary Computer asset roles changed: {asset_key}"
                )
            managed_href = self._managed_asset_href(actual_asset.get("href"))
            if self._same_url(managed_href, expected_asset.get("href")):
                raise PlanetaryComputerProviderError(
                    f"Planetary Computer did not copy asset: {asset_key}"
                )
            if verify_reachability:
                self._verify_managed_asset_reachable(managed_href)
            published_artifacts.append(
                PublishedArtifact(
                    **artifact.model_dump(),
                    publishedPath=managed_href,
                )
            )
        return published_artifacts

    @staticmethod
    def _verify_item_bbox(
        expected_item: Mapping[str, Any],
        actual_item: Mapping[str, Any],
    ) -> None:
        expected_bbox = expected_item.get("bbox")
        actual_bbox = actual_item.get("bbox")
        if not (
            isinstance(expected_bbox, list)
            and isinstance(actual_bbox, list)
            and len(expected_bbox) == len(actual_bbox) == 4
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer item bbox is invalid"
            )
        try:
            matches = all(
                math.isclose(
                    float(expected),
                    float(actual),
                    rel_tol=0,
                    abs_tol=1e-9,
                )
                for expected, actual in zip(expected_bbox, actual_bbox)
            )
        except (TypeError, ValueError):
            matches = False
        if not matches:
            raise PlanetaryComputerProviderError(
                "Planetary Computer item bbox verification failed"
            )

    @staticmethod
    def _verify_item_properties(
        expected_item: Mapping[str, Any],
        actual_item: Mapping[str, Any],
    ) -> None:
        expected = expected_item.get("properties")
        actual = actual_item.get("properties")
        if not isinstance(expected, Mapping) or not isinstance(
            actual, Mapping
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer item properties are invalid"
            )
        for key, expected_value in expected.items():
            if actual.get(key) != expected_value:
                raise PlanetaryComputerProviderError(
                    f"Planetary Computer item property changed: {key}"
                )

    def _build_documents(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
        projection_codes: Mapping[str, str],
        existing_collection: Optional[Mapping[str, Any]],
    ):
        mask = source.get(ArtifactKind.VALID_MASK)
        if mask is None:
            raise ValueError("Planetary Computer requires a valid-area mask")
        valid_mask = self.json_reader(mask)
        asset_hrefs = {
            artifact.sourcePath: self._artifact_href(artifact)
            for artifact in source.selectedArtifacts
        }
        collection_id = build_collection_id(dataset, self.collection_prefix)
        thumbnail_href, thumbnail_media_type = self._resolve_thumbnail_href(
            dataset, source
        )
        objects = build_stac_objects(
            dataset,
            source,
            valid_mask,
            asset_hrefs,
            projection_codes,
            self._collection_href(collection_id),
            valid_mask_crs=self._valid_mask_crs(valid_mask),
            existing_collection=existing_collection,
            collection_prefix=self.collection_prefix,
            thumbnail_href=thumbnail_href,
            thumbnail_media_type=thumbnail_media_type,
        )
        self.stac_validator(objects)
        return serialize_stac_objects(objects)

    def _resolve_thumbnail_href(
        self, dataset: PublishedDataset, source: ArtifactBundle
    ) -> tuple[Optional[str], str]:
        # Copy the post-event preview into the dataset's published prefix (the
        # ingestion-source container the GeoCatalog can read) and return a plain
        # blob href for it. Best-effort: any failure yields no thumbnail rather
        # than breaking the publish.
        preview_url = getattr(source, "thumbnailUrl", None)
        if not preview_url:
            return None, DEFAULT_THUMBNAIL_MEDIA_TYPE
        try:
            relative_path = self._preview_relative_path(preview_url)
            if not relative_path or not self.artifact_storage.artifact_exists(
                relative_path
            ):
                return None, DEFAULT_THUMBNAIL_MEDIA_TYPE
            extension = PurePosixPath(relative_path).suffix.lower() or ".png"
            media_type = _THUMBNAIL_MEDIA_TYPES.get(
                extension, DEFAULT_THUMBNAIL_MEDIA_TYPE
            )
            destination = (
                f"published/{dataset.datasetId}/thumbnail{extension}"
            )
            etag = self.artifact_storage.get_artifact_etag(relative_path)
            published_path = self.artifact_storage.copy_artifact(
                relative_path, destination, etag
            )
            resolved = self.artifact_storage.resolve_artifact_path(
                published_path
            )
            base_url = str(self.artifact_storage.get_base_url()).rstrip("/")
            href = f"{base_url}/{quote(resolved, safe='/-_.~')}"
            return href, media_type
        except Exception as error:
            self.logger.warning(
                "Skipping Planetary Computer thumbnail: %s",
                type(error).__name__,
            )
            return None, DEFAULT_THUMBNAIL_MEDIA_TYPE

    def _preview_relative_path(self, preview_url: str) -> Optional[str]:
        # A preview URL is only usable if it lives in the same account+container
        # as the published artifacts (the container the ingestion source reads).
        base = urlparse(str(self.artifact_storage.get_base_url()))
        parsed = urlparse(preview_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname != base.hostname
        ):
            return None
        base_path = base.path.rstrip("/")
        if base_path:
            if not parsed.path.startswith(base_path + "/"):
                return None
            relative = parsed.path[len(base_path) + 1 :]
        else:
            relative = parsed.path.lstrip("/")
        return unquote(relative) or None

    @staticmethod
    def _valid_mask_crs(valid_mask: Mapping[str, Any]) -> str:
        crs_value = valid_mask.get("crs")
        if crs_value is None:
            return "EPSG:4326"
        if not isinstance(crs_value, Mapping):
            raise ValueError("Valid-area mask CRS is invalid")
        properties = crs_value.get("properties")
        if not isinstance(properties, Mapping):
            raise ValueError("Valid-area mask CRS is invalid")
        name = properties.get("name")
        if crs_value.get("type") != "name" or not isinstance(name, str):
            raise ValueError("Valid-area mask CRS is invalid")
        try:
            parsed = CRS.from_user_input(name)
        except CRSError as error:
            raise ValueError("Valid-area mask CRS is invalid") from error
        return parsed.to_string()

    def _projection_codes(
        self,
        dataset: PublishedDataset,
        source: ArtifactBundle,
    ) -> dict[str, str]:
        persisted = dataset.providerMetadata.get("projectionCodes") or {}
        if not isinstance(persisted, Mapping):
            raise PlanetaryComputerProviderError(
                "Planetary Computer projection metadata is invalid"
            )
        projection_codes = {}
        for artifact in source.selectedArtifacts:
            if artifact.kind == ArtifactKind.VALID_MASK:
                continue
            projection_code = persisted.get(artifact.sourcePath)
            if not projection_code:
                projection_code = self.projection_resolver(artifact)
            projection_codes[artifact.sourcePath] = str(projection_code)
        return projection_codes

    def _validate_bundle(self, source: ArtifactBundle) -> None:
        if not source.selectedArtifacts:
            raise ValueError("Select at least one artifact to publish")
        supported = set(self.info.supportedArtifactKinds)
        unsupported = {
            artifact.kind
            for artifact in source.selectedArtifacts
            if artifact.kind not in supported
        }
        if unsupported:
            names = ", ".join(sorted(kind.value for kind in unsupported))
            raise ValueError(
                f"Unsupported Planetary Computer artifacts: {names}"
            )
        mask = source.get(ArtifactKind.VALID_MASK)
        if mask is None:
            raise ValueError("Planetary Computer requires a valid-area mask")
        if mask.sizeBytes and mask.sizeBytes > MAX_VALID_MASK_BYTES:
            raise ValueError("Valid-area mask is too large")

    def _require_configuration(self) -> None:
        if not self.info.isEnabled or not self.info.isConfigured:
            raise PlanetaryComputerProviderError(
                self.info.disabledReason
                or "Planetary Computer provider is unavailable"
            )
        if self.ingestion_source and not re.fullmatch(
            r"[A-Za-z0-9._-]{1,256}", self.ingestion_source
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer ingestion source ID is invalid"
            )
        if not 1 <= self.max_verify_attempts <= 60:
            raise PlanetaryComputerProviderError(
                "Planetary Computer verification limit is invalid"
            )
        self._safe_https_url(self.endpoint, allow_path=False)
        # The Explorer URL is a display-only link surfaced on the dataset row.
        # MPC Pro's real Explorer links carry a query string
        # (e.g. ?geocatalogname=...&c=...&z=...), so allow query/fragment here
        # while keeping the GeoCatalog and asset URLs strict.
        self._safe_https_url(
            self.explorer_url, allow_path=True, allow_query=True
        )

    def _validate_ingestion_source(self) -> None:
        source = self.sdk.get_ingestion_source(self.ingestion_source)
        if source is None:
            raise PlanetaryComputerProviderError(
                "Planetary Computer ingestion source was not found"
            )
        kind = self._mapping_value(source, "kind")
        if kind not in {"BlobManagedIdentity", "SasToken"}:
            raise PlanetaryComputerProviderError(
                "Planetary Computer ingestion source type is unsupported"
            )
        connection = self._mapping_value(
            source,
            "connectionInfo",
            "connection_info",
        )
        container_url = self._mapping_value(
            connection,
            "containerUrl",
            "container_uri",
        )
        expected_url = str(self.artifact_storage.get_base_url()).rstrip("/")
        if not isinstance(container_url, str) or not self._same_url(
            expected_url,
            container_url.rstrip("/"),
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer ingestion source container does not "
                "match HASTE storage"
            )

    def _artifact_href(self, artifact: SourceArtifact) -> str:
        base_url = str(self.artifact_storage.get_base_url()).rstrip("/")
        parsed = self._safe_https_url(base_url, allow_path=True)
        if str(parsed.hostname).lower().startswith("devstoreaccount1"):
            raise ValueError(
                "Planetary Computer cannot ingest from the storage emulator"
            )
        if not self._is_azure_blob_host(str(parsed.hostname)):
            raise ValueError(
                "Planetary Computer source must use Azure Blob Storage"
            )
        relative_path = self.artifact_storage.resolve_artifact_path(
            artifact.sourcePath
        )
        encoded_path = quote(relative_path, safe="/-_.~")
        return f"{base_url}/{encoded_path}"

    def _managed_asset_href(self, value: Any) -> str:
        if not isinstance(value, str):
            raise PlanetaryComputerProviderError(
                "Planetary Computer managed asset URL is missing"
            )
        parsed = self._safe_https_url(value, allow_path=True)
        if parsed.query:
            raise PlanetaryComputerProviderError(
                "Planetary Computer managed asset URL must not contain a token"
            )
        if not self._is_azure_blob_host(str(parsed.hostname)):
            raise PlanetaryComputerProviderError(
                "Planetary Computer managed asset URL is not Azure Blob "
                "Storage"
            )
        return value

    def _verify_managed_asset_reachable(self, managed_href: str) -> None:
        try:
            signed_href = self.sdk.get_signed_asset_url(managed_href)
            self._validate_signed_asset_url(managed_href, signed_href)
            self.asset_reachability_checker(signed_href)
        except PlanetaryComputerProviderError:
            raise
        except Exception as error:
            raise PlanetaryComputerProviderError(
                "Planetary Computer managed asset is not reachable"
            ) from error

    @classmethod
    def _validate_signed_asset_url(
        cls,
        managed_href: str,
        signed_href: str,
    ) -> None:
        if not isinstance(signed_href, str) or len(signed_href) > 8192:
            raise PlanetaryComputerProviderError(
                "Planetary Computer signed asset URL is invalid"
            )
        unsigned = urlparse(managed_href)
        signed = urlparse(signed_href)
        try:
            signed_port = signed.port
        except ValueError as error:
            raise PlanetaryComputerProviderError(
                "Planetary Computer signed asset URL is invalid"
            ) from error
        if (
            signed.scheme != "https"
            or not signed.hostname
            or signed.username is not None
            or signed.password is not None
            or signed.fragment
            or not signed.query
            or (signed_port is not None and not 1 <= signed_port <= 65535)
            or signed.hostname.lower() != str(unsigned.hostname).lower()
            or signed_port != unsigned.port
            or signed.path != unsigned.path
        ):
            raise PlanetaryComputerProviderError(
                "Planetary Computer signed asset URL is invalid"
            )
        if not cls._is_azure_blob_host(signed.hostname):
            raise PlanetaryComputerProviderError(
                "Planetary Computer signed asset URL is not Azure Blob "
                "Storage"
            )

    @staticmethod
    def _read_signed_asset(signed_href: str) -> None:
        parsed = urlparse(signed_href)
        connection = HTTPSConnection(
            str(parsed.hostname),
            parsed.port or 443,
            timeout=30,
        )
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        try:
            connection.request(
                "GET",
                target,
                headers={"Range": "bytes=0-0"},
            )
            response = connection.getresponse()
            if response.status not in {200, 206}:
                raise PlanetaryComputerProviderError(
                    "Planetary Computer managed asset is not reachable"
                )
            response.read(1)
        except PlanetaryComputerProviderError:
            raise
        except Exception as error:
            raise PlanetaryComputerProviderError(
                "Planetary Computer managed asset is not reachable"
            ) from error
        finally:
            connection.close()

    @staticmethod
    def _mapping_value(value: Any, *names: str) -> Any:
        if isinstance(value, Mapping):
            for name in names:
                if name in value:
                    return value[name]
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
        return None

    @staticmethod
    def _same_url(first: Any, second: Any) -> bool:
        if not isinstance(first, str) or not isinstance(second, str):
            return False
        first_url = urlparse(first)
        second_url = urlparse(second)
        try:
            first_port = first_url.port
            second_port = second_url.port
        except ValueError:
            return False
        return (
            first_url.scheme.lower() == second_url.scheme.lower()
            and str(first_url.hostname).lower()
            == str(second_url.hostname).lower()
            and first_port == second_port
            and first_url.path == second_url.path
            and first_url.params == second_url.params
            and first_url.query == second_url.query
            and first_url.fragment == second_url.fragment
        )

    @staticmethod
    def _is_azure_blob_host(hostname: str) -> bool:
        host = hostname.lower().rstrip(".")
        return any(
            host.endswith(suffix) for suffix in AZURE_BLOB_HOST_SUFFIXES
        )

    @staticmethod
    def _safe_https_url(
        value: str, *, allow_path: bool, allow_query: bool = False
    ):
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("Planetary Computer URL is invalid") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (not allow_query and (parsed.fragment or parsed.query))
            or (port is not None and not 1 <= port <= 65535)
            or (not allow_path and parsed.path not in {"", "/"})
        ):
            raise ValueError("Planetary Computer URL must use HTTPS")
        return parsed

    def _operation_metadata(
        self,
        dataset: PublishedDataset,
        projection_codes: Mapping[str, str],
        phase: Optional[PlanetaryComputerPhase],
    ) -> dict[str, Any]:
        metadata = self._stable_metadata(dataset)
        metadata["projectionCodes"] = dict(projection_codes)
        metadata["verificationAttempts"] = 0
        if phase is not None:
            metadata["phase"] = phase.value
        return metadata

    def _stable_metadata(self, dataset: PublishedDataset) -> dict[str, Any]:
        collection_id = str(
            dataset.providerMetadata.get("collectionId")
            or build_collection_id(dataset, self.collection_prefix)
        )
        item_ids = dataset.providerMetadata.get("itemIds") or [
            build_item_id(dataset)
        ]
        if not isinstance(item_ids, list) or len(item_ids) != 1:
            raise PlanetaryComputerProviderError(
                "Planetary Computer item metadata is invalid"
            )
        return {
            "collectionId": collection_id,
            "itemIds": [str(item_ids[0])],
            "apiVersion": PC_API_VERSION,
            "ingestionSource": self.ingestion_source,
        }

    def _operation_pending(
        self,
        metadata: Mapping[str, Any],
        phase: PlanetaryComputerPhase,
        continuation_token: Optional[str],
        *,
        count_attempt: bool = False,
    ) -> PublishResult:
        if not continuation_token:
            raise PlanetaryComputerProviderError(
                "Planetary Computer operation URL is missing"
            )
        updated = dict(metadata)
        updated["phase"] = phase.value
        updated["verificationAttempts"] = 0
        attempts = int(metadata.get("operationAttempts") or 0)
        if count_attempt:
            attempts += 1
            if attempts > self.max_verify_attempts:
                raise PlanetaryComputerProviderError(
                    "Planetary Computer ingestion timed out"
                )
        else:
            attempts = 0
        updated["operationAttempts"] = attempts
        return PublishResult(
            providerMetadata=updated,
            continuationToken=continuation_token,
            isComplete=False,
        )

    def _verification_pending(
        self,
        metadata: Mapping[str, Any],
        phase: PlanetaryComputerPhase,
        continuation_token: str,
    ) -> PublishResult:
        attempts = int(metadata.get("verificationAttempts") or 0) + 1
        if attempts > self.max_verify_attempts:
            raise PlanetaryComputerProviderError(
                "Planetary Computer verification timed out"
            )
        updated = dict(metadata)
        updated["phase"] = phase.value
        updated["verificationAttempts"] = attempts
        updated["operationAttempts"] = 0
        return PublishResult(
            providerMetadata=updated,
            continuationToken=continuation_token,
            isComplete=False,
        )

    @staticmethod
    def _phase(metadata: Mapping[str, Any]) -> PlanetaryComputerPhase:
        try:
            return PlanetaryComputerPhase(str(metadata.get("phase")))
        except ValueError as error:
            raise PlanetaryComputerProviderError(
                "Planetary Computer operation phase is missing"
            ) from error

    @staticmethod
    def _continuation_token(metadata: Mapping[str, Any]) -> str:
        token = metadata.get("continuationToken")
        if not isinstance(token, str) or not token:
            raise PlanetaryComputerProviderError(
                "Planetary Computer operation URL is missing"
            )
        return token

    def _ids(self, dataset: PublishedDataset) -> tuple[str, str]:
        metadata = self._stable_metadata(dataset)
        return metadata["collectionId"], metadata["itemIds"][0]

    def _collection_href(self, collection_id: str) -> str:
        encoded = quote(collection_id, safe="-_.")
        return f"{self.endpoint}/stac/collections/{encoded}"

    def _item_href(self, collection_id: str, item_id: str) -> str:
        encoded_collection = quote(collection_id, safe="-_.")
        encoded_item = quote(item_id, safe="-_+,.()")
        return (
            f"{self.endpoint}/stac/collections/{encoded_collection}/items/"
            f"{encoded_item}"
        )

    @staticmethod
    def _is_status(error: Exception, status_code: int) -> bool:
        direct_status = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        response_status = getattr(response, "status_code", None)
        return direct_status == status_code or response_status == status_code

    def _read_json_artifact(
        self, artifact: SourceArtifact
    ) -> Mapping[str, Any]:
        with self._materialized_artifact(artifact) as local_path:
            with open(local_path, encoding="utf-8") as source_file:
                value = json.load(source_file)
        if not isinstance(value, Mapping):
            raise ValueError("Valid-area mask JSON must be an object")
        return value

    def _read_projection_code(self, artifact: SourceArtifact) -> str:
        harden_gdal()
        import fiona

        with self._materialized_artifact(artifact) as local_path:
            layers = fiona.listlayers(local_path)
            if not layers:
                raise ValueError("GeoPackage has no vector layers")
            source_crs_values = []
            for layer in layers:
                with fiona.open(local_path, layer=layer) as source:
                    source_crs_values.append(source.crs_wkt or source.crs)
        if any(not value for value in source_crs_values):
            raise ValueError(
                f"Artifact has no CRS: {PurePosixPath(artifact.sourcePath).name}"
            )
        try:
            epsg_codes = {
                CRS.from_user_input(value).to_epsg()
                for value in source_crs_values
            }
        except CRSError as error:
            raise ValueError("Artifact CRS is invalid") from error
        if None in epsg_codes:
            raise ValueError("Artifact CRS has no EPSG authority code")
        if len(epsg_codes) != 1:
            raise ValueError("GeoPackage layers use different CRS values")
        epsg = epsg_codes.pop()
        return f"EPSG:{epsg}"

    @contextmanager
    def _materialized_artifact(
        self, artifact: SourceArtifact
    ) -> Iterator[Path]:
        relative_path = self.artifact_storage.resolve_artifact_path(
            artifact.sourcePath
        )
        with tempfile.TemporaryDirectory() as directory:
            self.artifact_storage.fetch_artifact(
                src_path=relative_path,
                dst_path=directory,
            )
            local_path = Path(directory, relative_path)
            if not local_path.is_file():
                matches = list(
                    Path(directory).rglob(PurePosixPath(relative_path).name)
                )
                if len(matches) != 1 or not matches[0].is_file():
                    raise FileNotFoundError(artifact.sourcePath)
                local_path = matches[0]
            yield local_path
