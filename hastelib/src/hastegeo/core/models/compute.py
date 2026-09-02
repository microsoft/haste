# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Backend-neutral compute models.

Typed vocabulary shared by every compute backend adapter (Azure Batch,
Azure Machine Learning, local Docker): ``ComputeJobSpec`` (what to run),
``ComputeJobHandle`` (what ran, and where to find it again), capacity
snapshots used by ``auto`` routing, and the typed exceptions adapters raise.

Wired end to end: each workload processor builds a ``ComputeJobSpec``,
``hastegeo.core.runners.execution_service.ComputeExecutionService``
validates/resolves/submits it through the ``RunnerRegistry``-constructed
adapter (Azure Batch, Azure Machine Learning, or local Docker — see
``hastegeo.core.runners.{azure_batch,azure_ml,local}``), and the resulting
``ComputeJobHandle`` is what callers persist and dispatch subsequent
lifecycle calls against. See spec/features/aml-compute-backend/
{design.md,data-model.md} for the full contract this implements, and
ADR-0005 for the architecture rationale. Validation here is deliberately
centralized: path/URI/credential checks are implemented once and reused by
every field that needs them, rather than duplicated per adapter.
"""

import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

from hastegeo.__about__ import __version__ as _HASTE_VERSION
from hastegeo.core.utils.metadata import MetadataUtils
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class ComputeBackend(str, Enum):
    LOCAL = "local"
    AZURE_BATCH = "azure_batch"
    AZURE_ML = "azure_ml"
    AUTO = "auto"


class ComputeWorkload(str, Enum):
    TRAINING = "training"
    INFERENCE = "inference"
    EMBEDDING = "embedding"
    IMAGERY_PREPARATION = "imagery_preparation"
    ARTIFACT_PACKAGING = "artifact_packaging"


class ComputeJobState(str, Enum):
    PENDING = "pending"
    SUBMITTING = "submitting"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: States a job cannot transition out of. Used by adapters/callers to guard
#: against overwriting a terminal state with a stale/racing update (see
#: design.md#edge-cases-and-failure-behavior, NEG-003).
TERMINAL_JOB_STATES = frozenset(
    {
        ComputeJobState.SUCCEEDED,
        ComputeJobState.FAILED,
        ComputeJobState.CANCELLED,
    }
)


class InputKind(str, Enum):
    FILE = "file"
    FOLDER = "folder"


class InputDeliveryMode(str, Enum):
    DOWNLOAD = "download"
    MOUNT = "mount"
    DIRECT = "direct"


class OutputPersistenceMode(str, Enum):
    LIVE_MOUNT = "live_mount"
    UPLOAD_ON_COMPLETION = "upload_on_completion"


class CapacityState(str, Enum):
    AVAILABLE = "available"
    QUEUEABLE = "queueable"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Typed exceptions
#
# Adapters raise these; ``ComputeExecutionService``/``ComputeRouter`` catch
# specific subclasses (never bare ``Exception`` and never this common base)
# so an unclassified adapter failure is never silently swallowed.
# --------------------------------------------------------------------------


class ComputeError(Exception):
    """Common ancestor for typed compute-layer errors.

    Exists for ``isinstance`` checks against "any compute error" in tests
    and logging, not for callers to catch broadly instead of a specific
    subclass.
    """


class BackendConfigurationError(ComputeError):
    """The requested backend/profile is missing required configuration, or
    is not implemented/registered. Raised before any provider call."""


class BackendUnavailableError(ComputeError):
    """The backend is reachable but currently unhealthy (pre-acceptance)."""


class CapacityUnavailableError(ComputeError):
    """No candidate backend reports usable capacity for the workload."""


class SubmissionIndeterminateError(ComputeError):
    """The provider call outcome is unknown (timeout/connection reset after
    the request may have reached the provider). Callers must reconcile via
    the deterministic provider name, never blindly retry against a
    different backend."""


class JobNotFoundError(ComputeError):
    """The provider has no record of the job referenced by a handle."""


class OutputNotAvailableError(ComputeError):
    """The requested output is not yet available. Not necessarily an error
    — e.g. a live progress file that hasn't been written yet."""


class JobCancellationError(ComputeError):
    """Cancellation could not be completed."""


# --------------------------------------------------------------------------
# Validation helpers
#
# Exposed as module-level functions (not private) so adapters can reuse them
# for values that don't flow through a pydantic field, and so the "before
# every log line" credential check in design.md#security has one place to
# live.
# --------------------------------------------------------------------------

# http is required for the local Azurite storage emulator (see
# hastegeo.core.runners.local._normalize_azurite_url); https covers Azure
# Blob/Data Lake and provider imagery in deployed environments; abfss/wasbs
# cover Data Lake Gen2 / legacy Blob driver URIs; s3 covers imagery sources
# ingested from AWS; file covers local-adapter execution directories;
# azureml covers Azure Machine Learning datastore-relative URIs (e.g.
# "azureml://datastores/<name>/paths/<path>"); adl covers legacy Azure Data
# Lake Store Gen1 URIs (e.g. "adl://<account>.azuredatalakestore.net/...").
# Both azureml/adl carry a non-empty authority component (the datastore
# name / account host respectively) between "//" and the next "/", so they
# satisfy the same "must have a host component" check as every other
# non-file scheme below.
ALLOWED_URI_SCHEMES = frozenset(
    {"https", "http", "abfss", "wasbs", "s3", "file", "azureml", "adl"}
)

# Rejects only the single most volatile, non-versioned image tag
# (":latest", case-insensitive) outside dev/test. Deliberately does *not*
# require an ACR digest generically: Azure Batch deployments may
# legitimately reference a versioned, non-digest tag (e.g. ":v1.2.3"), and
# requiring a digest for every backend would break that existing,
# supported configuration. Enforcing a stronger, digest-only immutability
# guarantee is the Azure Machine Learning adapter's responsibility for its
# own resolved ``environmentReference`` (see ``validate_environment_
# reference`` below) — AML resolves an immutable *environment version*
# independently of the container image tag/digest itself.
_MUTABLE_LATEST_TAG_RE = re.compile(r":latest\s*$", re.IGNORECASE)

# Well-known secret-shaped environment/tag *key* names. Matched against a
# separator-normalized, lowercased key so "API_KEY", "api-key", and "apikey"
# all match, while an unrelated key like "MODEL_TOKEN_LIMIT" does not (its
# normalized form "modeltokenlimit" isn't in the denylist) — deliberately
# narrow to avoid false positives on ordinary identifiers.
_CREDENTIAL_KEY_DENYLIST = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "apikey",
        "accesskey",
        "accountkey",
        "clientsecret",
        "sastoken",
        "token",
        "authtoken",
        "authorization",
        "privatekey",
        "connectionstring",
        "refreshtoken",
        "sessiontoken",
    }
)

# A second, smaller set matched as a *substring* of the normalized key
# rather than requiring an exact match. Each entry is a longer, unambiguous
# compound (e.g. cloud-provider key-naming conventions like
# "AWS_SECRET_ACCESS_KEY") chosen specifically to avoid matching short,
# generic words that could appear inside an unrelated identifier (which is
# why "token"/"secret" alone stay exact-match only in the set above).
_CREDENTIAL_KEY_SUBSTRING_DENYLIST = frozenset(
    {
        "secretaccesskey",
        "accesskeyid",
        "accountkey",
        "clientsecret",
        "sastoken",
        "privatekey",
        "connectionstring",
        "apikey",
        "authtoken",
        "refreshtoken",
        "sessiontoken",
    }
)

# Azure SAS query strings always combine a signature with at least one other
# SAS parameter (sv/se/sp/...); requiring both avoids flagging a URL whose
# query string merely happens to contain "sig=" for an unrelated reason.
_SAS_SIG_RE = re.compile(r"(?:^|[?&])sig=", re.IGNORECASE)
_SAS_HINT_RE = re.compile(
    r"(?:^|[?&])(sv|se|sp|sr|spr|st|skoid|sktid)=", re.IGNORECASE
)
_CONN_STR_KEY_RE = re.compile(
    r"(?i)\b(accountkey|sharedaccesskey|sharedaccesssignature|"
    r"client_secret|clientsecret)\s*="
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._-]{10,}")
_JWT_RE = re.compile(
    r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$"
)
_PASSWORD_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|apikey)\s*=\s*\S"
)


def _normalize_key(key: str) -> str:
    return re.sub(r"[-_ ]", "", key).lower()


def is_credential_shaped_key(key: str) -> bool:
    """True if ``key`` (an environment/tag key name) matches a well-known
    secret-key naming convention.

    Checks the normalized key against ``_CREDENTIAL_KEY_DENYLIST`` for an
    exact match, then against ``_CREDENTIAL_KEY_SUBSTRING_DENYLIST`` for a
    substring match (catching compounds like ``AWS_SECRET_ACCESS_KEY``
    without the short generic tokens in the exact-match set producing
    false positives on substrings, e.g. ``MODEL_TOKEN_LIMIT``).
    """
    normalized = _normalize_key(key)
    if normalized in _CREDENTIAL_KEY_DENYLIST:
        return True
    return any(
        token in normalized for token in _CREDENTIAL_KEY_SUBSTRING_DENYLIST
    )


def looks_like_credential(value: Optional[str]) -> bool:
    """Best-effort, false-positive-averse detector for credential-shaped text.

    Flags well-known secret *shapes* — SAS query-parameter combinations,
    connection-string keys, bearer tokens, JWTs, and ``key=value``
    password/secret pairs — rather than any string containing a generically
    secret-adjacent word. This keeps ordinary identifiers (image digests,
    model names, workload tags) from being rejected as false positives.
    """
    if not value:
        return False
    if _SAS_SIG_RE.search(value) and _SAS_HINT_RE.search(value):
        return True
    if _CONN_STR_KEY_RE.search(value):
        return True
    if _BEARER_RE.search(value):
        return True
    if _JWT_RE.match(value.strip()):
        return True
    if _PASSWORD_KV_RE.search(value):
        return True
    return False


def assert_no_credential_material(
    value: Optional[str], *, field_name: str
) -> None:
    """Raise ``ValueError`` if ``value`` looks like a credential.

    Called both by the field/model validators below (construction time) and
    intended for adapters to call immediately before logging any value
    sourced from a spec/handle (design.md#security: "checked at
    construction and before every log line").
    """
    if looks_like_credential(value):
        raise ValueError(
            f"{field_name} must not contain credentials, tokens, or signed "
            "query strings"
        )


def redact_if_credential(value: Optional[str]) -> Optional[str]:
    """Return ``value`` unchanged, or a fixed redaction marker if it looks
    like a credential.

    For log call sites that must not raise (best-effort diagnostic
    logging) — prefer ``assert_no_credential_material`` at construction
    time and use this only where raising is not appropriate.
    """
    if value is None:
        return None
    return "<redacted>" if looks_like_credential(value) else value


def validate_relative_path(path: str, *, field_name: str) -> str:
    """Validate a workspace-relative path (input destination or output
    pattern).

    Rejects: empty values, backslashes (kept out entirely so behavior is
    identical across adapters regardless of host OS), absolute paths
    (leading ``/`` or a drive letter), any literal ``..`` segment, and empty
    path segments (e.g. ``a//b``). Segments are checked on the raw string
    before any normalization, so a path can't rely on something like
    ``os.path.normpath`` collapsing a traversal attempt away first.
    """
    if path is None or not path.strip():
        raise ValueError(f"{field_name} must not be empty")
    if "\\" in path:
        raise ValueError(f"{field_name} must use '/' path separators")
    if path.startswith("/"):
        raise ValueError(f"{field_name} must not be an absolute path")
    if re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"{field_name} must not be an absolute path")
    segments = path.split("/")
    if any(segment == ".." for segment in segments):
        raise ValueError(f"{field_name} must not contain '..' segments")
    if any(segment == "" for segment in segments):
        raise ValueError(f"{field_name} must not contain empty path segments")
    return path


def validate_uri_scheme(uri: str, *, field_name: str) -> str:
    """Validate that ``uri`` uses a recognized, allowlisted scheme.

    See ``ALLOWED_URI_SCHEMES`` for the rationale behind each entry.
    """
    if uri is None or not uri.strip():
        raise ValueError(f"{field_name} must not be empty")
    parsed = urlparse(uri)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_URI_SCHEMES:
        raise ValueError(
            f"{field_name} has an unrecognized URI scheme: {parsed.scheme!r}"
        )
    if scheme != "file" and not parsed.netloc:
        raise ValueError(f"{field_name} is missing a host component")
    return uri


def is_deployed_environment() -> bool:
    """True outside local dev/test — gates the immutable image-digest rule.

    Mirrors ``Config.__init__``'s own ``os.getenv("env", "dev")`` read
    (``hastegeo.core.config``) directly, rather than importing ``Config``,
    so this module carries no dependency on the config layer.
    """
    return os.getenv("env", "dev").strip().lower() not in ("dev", "test", "")


def validate_image_reference(image_reference: str) -> str:
    """Reject the mutable ``:latest`` container image tag outside dev/test.

    This intentionally does *not* require an ACR digest for every backend:
    Azure Batch deployments may legitimately reference a versioned,
    non-digest tag (e.g. ``:v1.2.3``), and that configuration must keep
    working. ``:latest`` specifically is rejected in deployed environments
    because it is the one tag value that never identifies a fixed image —
    every other tag or an ``@sha256:<digest>`` reference is accepted.
    """
    if image_reference is None or not image_reference.strip():
        raise ValueError("imageReference must not be empty")
    if is_deployed_environment() and _MUTABLE_LATEST_TAG_RE.search(
        image_reference.strip()
    ):
        raise ValueError(
            "imageReference must not use the mutable ':latest' tag in "
            "deployed environments; use a versioned tag or an "
            "'...@sha256:<64 hex>' digest reference"
        )
    return image_reference


def validate_environment_reference(
    environment_reference: Optional[str],
) -> Optional[str]:
    """Validate the optional, adapter-resolved AML environment version.

    Unlike ``imageReference`` (the container image tag/digest, shared by
    every backend), ``environmentReference`` is specifically the Azure
    Machine Learning environment *version* the AML adapter resolves for a
    given image (data-model.md's "resolved AML environment version,
    adapter-populated"). AML registers environment versions as immutable
    once created, so this enforces the stronger rule appropriate to that
    field alone: when set, it must not be empty and must not point at a
    mutable ``:latest``/``@latest`` alias in deployed environments.
    """
    if environment_reference is None:
        return None
    if not environment_reference.strip():
        raise ValueError("environmentReference must not be empty when set")
    normalized = environment_reference.strip().lower()
    if is_deployed_environment() and (
        normalized.endswith(":latest") or normalized.endswith("@latest")
    ):
        raise ValueError(
            "environmentReference must reference a specific immutable "
            "version, not ':latest'/'@latest', in deployed environments"
        )
    return environment_reference


# --------------------------------------------------------------------------
# Capacity model
# --------------------------------------------------------------------------


class ComputeResources(BaseModel):
    """Shared resource-request shape used by both ``ComputeJobSpec.resources``
    and ``ComputeRunner.get_capacity()``."""

    model_config = ConfigDict(extra="forbid")

    accelerator: Optional[str] = Field(default=None)
    nodeCount: int = Field(default=1, ge=1)
    sharedMemoryMb: Optional[int] = Field(default=None, ge=0)
    allowSpot: bool = Field(default=False)
    targetOverride: Optional[str] = Field(default=None)


class CapacitySnapshot(BaseModel):
    """Short-lived, advisory capacity report from one adapter.

    Never authoritative over the provider's own scheduler — see
    data-model.md#caching-strategy for the intended short TTL.
    """

    model_config = ConfigDict(extra="forbid")

    backend: ComputeBackend
    workload: ComputeWorkload
    state: CapacityState
    observedAt: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    detail: Optional[str] = Field(default=None)

    @field_validator("backend")
    @classmethod
    def _backend_not_auto(cls, value: ComputeBackend) -> ComputeBackend:
        if value == ComputeBackend.AUTO:
            raise ValueError("CapacitySnapshot.backend must not be 'auto'")
        return value

    @field_validator("detail")
    @classmethod
    def _detail_no_credentials(cls, value: Optional[str]) -> Optional[str]:
        assert_no_credential_material(value, field_name="detail")
        return value


# --------------------------------------------------------------------------
# ComputeJobSpec
# --------------------------------------------------------------------------


class ComputeContainerRef(BaseModel):
    """Container reference plus the job-workspace root.

    ``imageReference`` may be any tag or an ``@sha256:<digest>`` reference
    except the mutable ``:latest`` tag in deployed environments (see
    ``validate_image_reference``) — this keeps existing Azure Batch
    deployments that pin a versioned, non-digest tag working.
    ``environmentReference`` is the stricter, AML-specific immutable
    environment *version* the AML adapter resolves separately (see
    ``validate_environment_reference``); it is unset for backends that
    don't use it. ``workingDirectory`` is relative to ``HASTE_JOB_WORKDIR``
    (the application-owned workspace variable — see design.md#work-
    directory-contract), not an absolute in-container path, so it is
    validated with the same relative-path rule as input/output paths.
    """

    model_config = ConfigDict(extra="forbid")

    imageReference: str
    environmentReference: Optional[str] = Field(default=None)
    workingDirectory: str = Field(default=".")

    @field_validator("imageReference")
    @classmethod
    def _validate_image_reference(cls, value: str) -> str:
        return validate_image_reference(value)

    @field_validator("environmentReference")
    @classmethod
    def _validate_environment_reference(
        cls, value: Optional[str]
    ) -> Optional[str]:
        return validate_environment_reference(value)

    @field_validator("workingDirectory")
    @classmethod
    def _validate_working_directory(cls, value: str) -> str:
        return validate_relative_path(
            value, field_name="container.workingDirectory"
        )


class ComputeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sourceUri: str
    kind: InputKind
    destinationRelativePath: str
    deliveryMode: InputDeliveryMode = Field(default=InputDeliveryMode.DOWNLOAD)

    @field_validator("sourceUri")
    @classmethod
    def _validate_source_uri(cls, value: str) -> str:
        return validate_uri_scheme(value, field_name="inputs[].sourceUri")

    @field_validator("destinationRelativePath")
    @classmethod
    def _validate_destination(cls, value: str) -> str:
        return validate_relative_path(
            value, field_name="inputs[].destinationRelativePath"
        )


class ComputeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    sourceRelativePattern: str
    destinationUri: str
    persistenceMode: OutputPersistenceMode = Field(
        default=OutputPersistenceMode.UPLOAD_ON_COMPLETION
    )

    @field_validator("sourceRelativePattern")
    @classmethod
    def _validate_pattern(cls, value: str) -> str:
        # A glob pattern (e.g. "checkpoints/*.pt") is a valid relative path
        # for this check's purposes: glob metacharacters are ordinary,
        # non-empty path segments, so the same traversal/absolute-path rule
        # that governs input destinations applies unchanged.
        return validate_relative_path(
            value, field_name="outputs[].sourceRelativePattern"
        )

    @field_validator("destinationUri")
    @classmethod
    def _validate_destination_uri(cls, value: str) -> str:
        return validate_uri_scheme(
            value, field_name="outputs[].destinationUri"
        )


class ComputeTags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1)
    imageLayer: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    task: Optional[str] = Field(default=None)
    workload: ComputeWorkload
    hasteVersion: str = Field(default_factory=lambda: _HASTE_VERSION)

    @field_validator("project", "imageLayer", "model", "task", "hasteVersion")
    @classmethod
    def _no_credentials(cls, value, info) -> Optional[str]:
        assert_no_credential_material(
            value, field_name=f"tags.{info.field_name}"
        )
        return value


class ComputeJobSpec(BaseModel):
    """Backend-neutral description of one compute submission.

    Built by a workload-specific ``build_*_job_spec()`` next to each
    processor (see design.md#workload-migration-matrix) and passed to
    ``ComputeExecutionService.submit()``. Never constructed from raw,
    untrusted request bodies — ``command`` is an internally generated
    trusted shell invocation, never built from client input.
    """

    model_config = ConfigDict(extra="forbid")

    executionId: str = Field(min_length=1)
    workload: ComputeWorkload
    backendPreference: ComputeBackend = Field(default=ComputeBackend.AUTO)
    container: ComputeContainerRef
    command: str = Field(min_length=1)
    inputs: List[ComputeInput] = Field(default_factory=list)
    outputs: List[ComputeOutput] = Field(default_factory=list)
    environment: Dict[str, str] = Field(default_factory=dict)
    resources: ComputeResources = Field(default_factory=ComputeResources)
    timeoutSeconds: int = Field(default=3600, gt=0)
    tags: ComputeTags

    @field_validator("executionId")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("executionId must not be empty")
        # Used verbatim to build deterministic provider job/task names
        # (Batch task ID, AML job name, local execution directory name) —
        # keep it to characters every provider accepts.
        if not re.match(r"^[A-Za-z0-9._-]+$", normalized):
            raise ValueError(
                "executionId must contain only letters, digits, '.', '_' "
                "or '-'"
            )
        return normalized

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: Dict[str, str]) -> Dict[str, str]:
        for key, entry in value.items():
            if is_credential_shaped_key(key):
                raise ValueError(
                    f"environment key {key!r} looks like a credential name; "
                    "environment must be non-secret only"
                )
            assert_no_credential_material(
                entry, field_name=f"environment[{key!r}]"
            )
        return value

    @model_validator(mode="after")
    def _validate_tags_workload_matches(self) -> "ComputeJobSpec":
        if self.tags.workload != self.workload:
            raise ValueError("tags.workload must match workload")
        return self


# --------------------------------------------------------------------------
# ComputeJobHandle
# --------------------------------------------------------------------------


class BatchProviderDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobId: str = Field(min_length=1)
    taskId: str = Field(min_length=1)


class AzureMlProviderDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobName: str = Field(min_length=1)
    workspace: str = Field(min_length=1)


class LocalProviderDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executionDirectory: str = Field(min_length=1)
    processId: Optional[int] = Field(default=None)


ProviderDetailDiscriminator = Literal["batch", "azure_ml", "local"]


class ComputeProviderDetail(BaseModel):
    """Discriminated, provider-specific detail on a ``ComputeJobHandle``.

    Exactly one of ``batch``/``azureMl``/``local`` is populated, matching
    ``discriminator``. Modeled as sibling optional slots (rather than a true
    pydantic discriminated union) to match the persisted JSON shape in
    data-model.md exactly.
    """

    model_config = ConfigDict(extra="forbid")

    discriminator: ProviderDetailDiscriminator
    batch: Optional[BatchProviderDetail] = Field(default=None)
    azureMl: Optional[AzureMlProviderDetail] = Field(default=None)
    local: Optional[LocalProviderDetail] = Field(default=None)

    @model_validator(mode="after")
    def _validate_single_detail(self) -> "ComputeProviderDetail":
        slots = {
            "batch": self.batch,
            "azureMl": self.azureMl,
            "local": self.local,
        }
        expected_slot = {
            "batch": "batch",
            "azure_ml": "azureMl",
            "local": "local",
        }[self.discriminator]
        if slots[expected_slot] is None:
            raise ValueError(
                f"providerDetail.{expected_slot} must be set when "
                f"discriminator is {self.discriminator!r}"
            )
        others = [
            name
            for name, value in slots.items()
            if name != expected_slot and value is not None
        ]
        if others:
            raise ValueError(
                "providerDetail must populate exactly one provider slot "
                f"(discriminator={self.discriminator!r}); also set: {others}"
            )
        return self


#: Routing reason recorded when a legacy (jobId/taskId-only) job record is
#: synthesized into a ``ComputeJobHandle`` at read time. See
#: data-model.md#legacy-compatibility.
LEGACY_SYNTHESIZED_ROUTING_REASON = "legacy-synthesized"


class ComputeJobHandle(BaseModel):
    """Persisted record of one backend submission.

    Never contains access tokens, account keys, SAS tokens, raw
    credentials, or full signed input URLs — every free-form string field
    is checked at construction via ``assert_no_credential_material``.
    """

    model_config = ConfigDict(extra="forbid")

    executionId: str = Field(min_length=1)
    requestedBackend: ComputeBackend
    selectedBackend: ComputeBackend
    backendProfile: str = Field(default="default", min_length=1)
    providerJobId: str = Field(min_length=1)
    providerTaskId: Optional[str] = Field(default=None)
    targetId: str = Field(min_length=1)
    outputUri: str
    submittedAt: str
    routingReason: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1)
    providerDetail: ComputeProviderDetail

    @field_validator("selectedBackend")
    @classmethod
    def _selected_not_auto(cls, value: ComputeBackend) -> ComputeBackend:
        if value == ComputeBackend.AUTO:
            raise ValueError("selectedBackend must not be 'auto'")
        return value

    @field_validator("outputUri")
    @classmethod
    def _validate_output_uri(cls, value: str) -> str:
        validate_uri_scheme(value, field_name="outputUri")
        # "no full signed input URLs" (data-model.md#never-persisted)
        # applies to outputUri too — reject a SAS-signed URL rather than
        # persisting it on the handle.
        assert_no_credential_material(value, field_name="outputUri")
        return value

    @field_validator(
        "providerJobId",
        "providerTaskId",
        "targetId",
        "routingReason",
        "backendProfile",
    )
    @classmethod
    def _no_credentials(cls, value, info):
        assert_no_credential_material(value, field_name=info.field_name)
        return value

    @model_validator(mode="after")
    def _validate_backend_detail_consistency(self) -> "ComputeJobHandle":
        expected_discriminator = {
            ComputeBackend.AZURE_BATCH: "batch",
            ComputeBackend.AZURE_ML: "azure_ml",
            ComputeBackend.LOCAL: "local",
        }[self.selectedBackend]
        if self.providerDetail.discriminator != expected_discriminator:
            raise ValueError(
                "providerDetail.discriminator must match selectedBackend "
                f"({self.selectedBackend.value} -> {expected_discriminator!r} "
                f"expected, got {self.providerDetail.discriminator!r})"
            )
        return self


def synthesize_legacy_batch_handle(
    *,
    job_id: str,
    task_id: str,
    output_uri: str,
    target_id: Optional[str] = None,
) -> ComputeJobHandle:
    """Build a Batch ``ComputeJobHandle`` for a job record that predates the
    neutral compute layer (only ``jobId``/``taskId`` persisted).

    Intended for use at *read* time so callers can treat every job record
    uniformly through ``ComputeJobHandle`` regardless of when it was
    submitted (data-model.md#legacy-compatibility). Never used at write
    time: legacy records are never migrated/backfilled in place.
    """
    if job_id is None or not job_id.strip():
        raise ValueError("job_id must not be empty")
    if task_id is None or not task_id.strip():
        raise ValueError("task_id must not be empty")
    return ComputeJobHandle(
        executionId=task_id,
        requestedBackend=ComputeBackend.AZURE_BATCH,
        selectedBackend=ComputeBackend.AZURE_BATCH,
        backendProfile="default",
        providerJobId=job_id,
        providerTaskId=task_id,
        targetId=target_id or job_id,
        outputUri=output_uri,
        submittedAt=MetadataUtils.get_timestamp(),
        routingReason=LEGACY_SYNTHESIZED_ROUTING_REASON,
        attempt=1,
        providerDetail=ComputeProviderDetail(
            discriminator="batch",
            batch=BatchProviderDetail(jobId=job_id, taskId=task_id),
        ),
    )


__all__ = [
    "ALLOWED_URI_SCHEMES",
    "LEGACY_SYNTHESIZED_ROUTING_REASON",
    "TERMINAL_JOB_STATES",
    "AzureMlProviderDetail",
    "BackendConfigurationError",
    "BackendUnavailableError",
    "BatchProviderDetail",
    "CapacityState",
    "CapacityUnavailableError",
    "CapacitySnapshot",
    "ComputeBackend",
    "ComputeContainerRef",
    "ComputeError",
    "ComputeInput",
    "ComputeJobHandle",
    "ComputeJobSpec",
    "ComputeJobState",
    "ComputeOutput",
    "ComputeProviderDetail",
    "ComputeResources",
    "ComputeTags",
    "ComputeWorkload",
    "InputDeliveryMode",
    "InputKind",
    "JobCancellationError",
    "JobNotFoundError",
    "LocalProviderDetail",
    "OutputNotAvailableError",
    "OutputPersistenceMode",
    "SubmissionIndeterminateError",
    "assert_no_credential_material",
    "is_credential_shaped_key",
    "is_deployed_environment",
    "looks_like_credential",
    "redact_if_credential",
    "synthesize_legacy_batch_handle",
    "validate_environment_reference",
    "validate_image_reference",
    "validate_relative_path",
    "validate_uri_scheme",
]
