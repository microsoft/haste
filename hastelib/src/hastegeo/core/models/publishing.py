import hashlib
import json
import unicodedata
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_https_url(value: Optional[str]) -> Optional[str]:
    """Trim and require an https URL; empty/None becomes None."""
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("value must be an https URL")
    return normalized


PUBLISHING_UUID_NAMESPACE = uuid.NAMESPACE_URL
PUBLISHING_UUID_NAME_PREFIX = (
    "https://github.com/microsoft/haste/data-publishing"
)


class PublishTarget(str, Enum):
    LOCAL = "local"
    PLANETARY_COMPUTER = "planetary_computer"


class PublishStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    UNPUBLISH_PENDING = "UNPUBLISH_PENDING"
    UNPUBLISHING = "UNPUBLISHING"
    UNPUBLISH_FAILED = "UNPUBLISH_FAILED"


class PublishOperation(str, Enum):
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"


class ArtifactKind(str, Enum):
    GPKG = "gpkg"
    VALID_MASK = "valid_mask"
    FOOTPRINTS = "footprints"
    PROCESSED_COG = "processed_cog"


class ProviderConfigField(BaseModel):
    key: str
    label: str
    required: bool
    secret: bool = False


class ProviderInfo(BaseModel):
    id: str
    displayName: str
    description: str = ""
    isEnabled: bool
    isConfigured: bool
    disabledReason: Optional[str] = None
    supportsAsync: bool = True
    supportedArtifactKinds: List[ArtifactKind] = Field(default_factory=list)
    requiredSupportingArtifactKinds: List[ArtifactKind] = Field(
        default_factory=list
    )
    configRequirements: List[ProviderConfigField] = Field(default_factory=list)


class SourceArtifact(BaseModel):
    kind: ArtifactKind
    sourcePath: str
    mediaType: str
    sizeBytes: Optional[int] = Field(default=None, ge=0)
    sourceEtag: str = Field(min_length=1, max_length=256)


class PublishedArtifact(SourceArtifact):
    publishedPath: str


class PublishDatasetOptions(BaseModel):
    projectId: uuid.UUID
    projectName: str
    imageLayerId: str
    imageLayerName: str
    modelId: str
    modelName: str
    defaultName: str
    availableArtifacts: List[SourceArtifact] = Field(default_factory=list)


class ArtifactBundle(BaseModel):
    selectedArtifacts: List[SourceArtifact] = Field(default_factory=list)
    supportingArtifacts: List[SourceArtifact] = Field(default_factory=list)

    def get(self, kind: ArtifactKind) -> Optional[SourceArtifact]:
        for artifact in self.selectedArtifacts + self.supportingArtifacts:
            if artifact.kind == kind:
                return artifact
        return None


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestId: uuid.UUID
    projectId: uuid.UUID
    imageLayerId: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    modelId: str = Field(
        min_length=1,
        max_length=8,
        pattern=r"^[0-9]+$",
    )
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    interactiveViewerUrl: Optional[str] = Field(default=None, max_length=2000)
    target: PublishTarget
    artifacts: List[ArtifactKind] = Field(min_length=1)

    @field_validator("imageLayerId", "modelId", "name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value).strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return unicodedata.normalize("NFC", value).strip()

    @field_validator("interactiveViewerUrl")
    @classmethod
    def normalize_viewer_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_https_url(value)

    @field_validator("artifacts")
    @classmethod
    def normalize_artifacts(
        cls, value: List[ArtifactKind]
    ) -> List[ArtifactKind]:
        return sorted(set(value), key=lambda artifact: artifact.value)


class PublishResult(BaseModel):
    artifacts: List[PublishedArtifact] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)
    providerMetadata: Dict[str, Any] = Field(default_factory=dict)
    continuationToken: Optional[str] = None
    isComplete: bool = True


class PublishedDataset(BaseModel):
    schemaVersion: int = 1
    revision: int = Field(default=1, ge=1)
    datasetId: uuid.UUID
    requestId: uuid.UUID
    requestFingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str
    description: str = ""
    interactiveViewerUrl: Optional[str] = None
    projectId: uuid.UUID
    projectName: str = ""
    imageLayerId: str
    imageLayerName: str = ""
    modelId: str
    modelName: str = ""
    target: PublishTarget
    status: PublishStatus
    statusMessage: str = ""
    lastOperation: PublishOperation = PublishOperation.PUBLISH
    attempt: int = Field(default=1, ge=1)
    queueDispatchedAt: Optional[str] = None
    reconciledAttempt: Optional[int] = Field(default=None, ge=1)
    publishedByUser: str
    publishedByName: Optional[str] = None
    createdDate: str
    updatedDate: str
    publishedDate: Optional[str] = None
    artifacts: List[PublishedArtifact] = Field(default_factory=list)
    selectedArtifactKinds: List[ArtifactKind] = Field(default_factory=list)
    sourceArtifacts: List[SourceArtifact] = Field(default_factory=list)
    links: Dict[str, str] = Field(default_factory=dict)
    providerMetadata: Dict[str, Any] = Field(default_factory=dict)
    assessmentSummary: Dict[str, Any] = Field(default_factory=dict)


class PublishQueueMessage(BaseModel):
    datasetId: uuid.UUID
    projectId: uuid.UUID
    operation: PublishOperation
    attempt: int = Field(ge=1)


def derive_dataset_id(
    project_id: uuid.UUID, request_id: uuid.UUID
) -> uuid.UUID:
    name = (
        f"{PUBLISHING_UUID_NAME_PREFIX}/"
        f"{str(project_id).lower()}/{str(request_id).lower()}"
    )
    return uuid.uuid5(PUBLISHING_UUID_NAMESPACE, name)


def compute_request_fingerprint(
    request: PublishRequest, publisher_id: str
) -> str:
    normalized_publisher = publisher_id.strip().lower()
    if not normalized_publisher:
        raise ValueError("publisher_id must not be empty")

    canonical_request = {
        "projectId": str(request.projectId).lower(),
        "imageLayerId": request.imageLayerId,
        "modelId": request.modelId,
        "name": request.name,
        "description": request.description or "",
        "target": request.target.value,
        "artifacts": [artifact.value for artifact in request.artifacts],
        "publisherId": normalized_publisher,
    }
    encoded = json.dumps(
        canonical_request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
