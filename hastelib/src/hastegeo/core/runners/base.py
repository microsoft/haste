# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import hashlib
from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlparse

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    CapacitySnapshot,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeOutput,
    ComputeResources,
    ComputeWorkload,
    InputKind,
)


class BaseRunner(ABC):
    """Batch-shaped runner contract, kept for backward compatibility during
    the deprecation window.

    Deprecated in favor of ``ComputeRunner`` below (see ADR-0005 and
    spec/features/aml-compute-backend/design.md). ``AzureBatchRunner`` and
    ``LocalRunner`` now implement *both* contracts (``class
    AzureBatchRunner(BaseRunner, ComputeRunner)``, likewise for
    ``LocalRunner``): the legacy ``(job_id, task_id)`` methods here keep
    working for ``UnifiedRunner`` (and any other pre-existing caller),
    while ``ComputeExecutionService`` drives the same adapters through
    ``ComputeRunner`` instead. All five processors have migrated to
    ``ComputeExecutionService`` (plan.md Phase 8, done) and no longer
    construct ``UnifiedRunner``/call these methods — see
    ``unified_runner``'s module docstring. Remove this class once the
    deprecation window for any remaining external caller closes.
    """

    def __init__(self, config: Config = None):
        self.config = config or Config()

    @abstractmethod
    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        pass

    @abstractmethod
    def get_task_status(self, job_id, task_id):
        pass

    @abstractmethod
    def add_task(self, job_id, task_id, **kwargs):
        pass

    @abstractmethod
    def cleanup_task(self, job_id, task_id):
        pass

    @abstractmethod
    def cancel_task(self, job_id, task_id):
        pass


class ComputeRunner(ABC):
    """Backend-neutral compute contract implemented by each adapter.

    Every backend (Azure Batch, Azure Machine Learning, local Docker)
    implements this same interface over ``ComputeJobSpec``/
    ``ComputeJobHandle`` instead of the Batch-shaped ``(job_id, task_id)``
    contract above — see design.md#backend-neutral-contracts. Constructed
    and cached by ``RunnerRegistry``; callers should go through
    ``ComputeExecutionService`` rather than invoking adapters directly, so
    lifecycle operations are always dispatched by a persisted handle's
    ``selectedBackend`` (see design.md#lifecycle-dispatch).

    Implementations must not raise bare ``Exception`` for classifiable
    failures — use the typed errors in ``hastegeo.core.models.compute``
    (``BackendConfigurationError``, ``BackendUnavailableError``,
    ``CapacityUnavailableError``, ``SubmissionIndeterminateError``,
    ``JobNotFoundError``, ``OutputNotAvailableError``,
    ``JobCancellationError``) so callers can react specifically instead of
    catching broadly.
    """

    def __init__(self, config: Config = None):
        self.config = config or Config()

    @abstractmethod
    def validate(self, spec: ComputeJobSpec) -> None:
        """Raise a typed error if ``spec`` cannot run on this backend/
        profile (unsupported workload, missing configuration, mutable
        image reference where a digest is required, etc).

        Must never itself submit anything to the provider — called by
        ``ComputeExecutionService`` before ``submit()``, and by the router
        while evaluating ``auto`` candidates.
        """

    @abstractmethod
    def submit(self, spec: ComputeJobSpec) -> ComputeJobHandle:
        """Idempotent get-or-create submission.

        Must derive the provider job/task name deterministically from
        ``spec.executionId`` and must be safe to call more than once for
        the same ``executionId`` (worker restart, duplicate queue
        delivery, retried indeterminate outcome) without creating a second
        provider job.
        """

    @abstractmethod
    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        """Return the normalized state of the job referenced by ``handle``.

        Raises ``JobNotFoundError`` if the provider has no record of it.
        """

    @abstractmethod
    def read_output(
        self,
        handle: ComputeJobHandle,
        relative_path: str,
        *,
        as_chunks: bool = False,
    ) -> Optional[Union[str, Iterable[bytes]]]:
        """Return the content at ``relative_path`` under the job's output,
        or ``None`` if it is not yet available.

        A not-yet-produced live progress file is a normal, expected
        condition — implementations must return ``None`` for it, not raise.
        """

    @abstractmethod
    def cancel(self, handle: ComputeJobHandle) -> None:
        """Request cancellation of the job referenced by ``handle``.

        Must be idempotent, and must never overwrite an already-terminal
        provider state (succeeded/failed) with ``cancelled``.
        """

    @abstractmethod
    def finalize(self, handle: ComputeJobHandle) -> None:
        """Release temporary execution resources for ``handle``.

        Must be idempotent, must never delete provider job/run history,
        and must never disable or terminate shared infrastructure (e.g.
        a Batch job/pool other executions still use) — only resources
        exclusively owned by this execution (e.g. a per-execution job
        holding just its own task) may be fully released.
        """

    @abstractmethod
    def get_capacity(
        self, workload: ComputeWorkload, resources: ComputeResources
    ) -> CapacitySnapshot:
        """Report this backend's advisory capacity for ``(workload,
        resources)``, used by ``ComputeRouter`` to filter ``auto``
        candidates. Never authoritative over the provider's own scheduler.
        """


# --------------------------------------------------------------------------
# Shared spec-translation helpers
#
# Both AzureBatchRunner and LocalRunner implement ComputeRunner by
# translating ComputeJobSpec into their existing, already-tested
# ``add_task(job_id, task_id, ..., resource_files_for_upload=..., ...)``
# keyword contract rather than duplicating provider-specific submission
# logic. These helpers do the shared, backend-neutral half of that
# translation (input/output shape) once, so azure_batch.py/local.py only
# need to adapt the result to their own ``add_task`` keyword names/shapes.
#
# They raise plain ``ValueError`` (not a typed ``hastegeo.core.models.
# compute`` error) on inconsistency: callers are adapters, which are
# expected to catch it and re-raise as their own classified
# ``BackendConfigurationError`` with backend-specific framing.
# --------------------------------------------------------------------------


def split_destination_uri(uri: str) -> Tuple[str, str, str]:
    """Split a HASTE destination URI into ``(container_url, container_name,
    prefix)``.

    E.g. ``https://acct.blob.core.windows.net/data/proj-hash/task-id/`` ->
    ``("https://acct.blob.core.windows.net/data", "data",
    "proj-hash/task-id")``.
    """
    parsed = urlparse(uri)
    parts = [p for p in parsed.path.split("/") if p]
    container_name = parts[0] if parts else ""
    prefix = "/".join(parts[1:])
    container_url = f"{parsed.scheme}://{parsed.netloc}"
    if container_name:
        container_url = f"{container_url}/{container_name}"
    return container_url, container_name, prefix


def resource_files_from_inputs(
    inputs: List[ComputeInput],
) -> Dict[str, dict]:
    """Translate ``ComputeJobSpec.inputs`` into the legacy
    ``resource_files_for_upload`` mapping ``AzureBatchJob.add_task``/
    ``LocalRunner._download_resource_files`` expect: a dict keyed by a
    stable name, each value carrying either ``http_url`` (single file) or
    ``storage_container_url``/``blob_prefix`` (whole folder), plus the
    common ``file_path`` destination.

    ``ComputeInput.destinationRelativePath`` is a required, validated
    (non-empty, non-traversal) field, so it is used verbatim as the dict
    key. Raises ``ValueError`` if two inputs share the same
    ``destinationRelativePath`` — silently letting the second overwrite
    the first in the resulting dict would drop an input without any
    signal.
    """
    resource_files: Dict[str, dict] = {}
    for item in inputs:
        key = item.destinationRelativePath
        if key in resource_files:
            raise ValueError(
                "duplicate input destinationRelativePath "
                f"{key!r}; each input must target a distinct path"
            )
        entry: dict = {"file_path": key}
        if item.kind == InputKind.FOLDER:
            container_url, _container_name, prefix = split_destination_uri(
                item.sourceUri
            )
            entry["storage_container_url"] = container_url
            entry["blob_prefix"] = prefix
        else:
            entry["http_url"] = item.sourceUri
        resource_files[key] = entry
    return resource_files


def require_single_output_destination(
    outputs: List[ComputeOutput],
) -> Tuple[str, str, str, List[str]]:
    """Validate that every output shares one destination container *and*
    prefix, and return ``(container_url, container_name, prefix,
    source_relative_patterns)``.

    Both adapters currently support only one output container/prefix per
    task (one ``OutputFileBlobContainerDestination`` for Batch; one
    ``output_container_url``/``output_prefix`` pair for local) — this
    matches the existing, unchanged behavior of landing every output under
    one ``<project-hash>/<task-id>/...`` prefix. Raises ``ValueError`` if
    ``outputs`` is empty, or any two outputs resolve to a different
    container *or* a different prefix (comparing container alone would
    silently accept two different prefixes and use only the first one).
    """
    if not outputs:
        raise ValueError("at least one output is required")
    container_url, container_name, prefix = split_destination_uri(
        outputs[0].destinationUri
    )
    for other in outputs[1:]:
        other_container_url, _, other_prefix = split_destination_uri(
            other.destinationUri
        )
        if other_container_url != container_url or other_prefix != prefix:
            raise ValueError(
                "every output must share one destination container and "
                f"prefix; got {(container_url, prefix)!r} and "
                f"{(other_container_url, other_prefix)!r}"
            )
    patterns = [o.sourceRelativePattern for o in outputs]
    return container_url, container_name, prefix, patterns


def require_supported_uri_schemes(
    *,
    inputs: List[ComputeInput],
    outputs: List[ComputeOutput],
    allowed_schemes: Union[frozenset, set],
    backend_name: str,
) -> None:
    """Raise ``ValueError`` if any input/output URI uses a scheme this
    adapter cannot correctly translate.

    ``hastegeo.core.models.compute.ALLOWED_URI_SCHEMES`` is intentionally
    broad (covers every backend, e.g. ``azureml``/``adl``/``s3`` for AML
    or S3-sourced imagery), but ``split_destination_uri``/
    ``resource_files_from_inputs`` above assume an
    ``https://host/container/prefix``-shaped URL (Azure Blob semantics):
    they read the "container" as the first path segment, which is simply
    wrong for schemes with a different shape (``s3://bucket/key`` puts the
    bucket in the host; ``azureml://datastores/<name>/paths/<path>`` and
    ``adl://account.azuredatalakestore.net/path`` don't have a Blob-style
    container segment either). Rejecting an unsupported scheme up front
    avoids silently misparsing it instead.

    The raised message names only the rejected *scheme*, never the full
    URI: a ``ComputeJobSpec``'s declared ``sourceUri``/``destinationUri``
    is not guaranteed free of a signed query string, and this error can
    propagate through ``validate()`` into caller logs (design.md#security
    — never leak a signed URL/token via error text).
    """
    for item in inputs:
        scheme = urlparse(item.sourceUri).scheme.lower()
        if scheme not in allowed_schemes:
            raise ValueError(
                f"{backend_name} does not support input URI scheme "
                f"{scheme!r}; supported schemes: {sorted(allowed_schemes)}"
            )
    for item in outputs:
        scheme = urlparse(item.destinationUri).scheme.lower()
        if scheme not in allowed_schemes:
            raise ValueError(
                f"{backend_name} does not support output URI scheme "
                f"{scheme!r}; supported schemes: {sorted(allowed_schemes)}"
            )


def truncate_deterministic_id(
    value: str, *, max_length: int, hash_length: int = 10
) -> str:
    """Deterministically shorten ``value`` to at most ``max_length``
    characters.

    Provider-assigned identifiers (e.g. an Azure Batch job id, capped at
    ``MAX_JOB_ID_LENGTH`` characters) can be too long once a workload's
    configured base id grows past that limit. Naively slicing
    (``value[:max_length]``) risks two different long values that happen
    to share the same first ``max_length`` characters silently colliding
    into the same id — appending a short hash of the *full* original
    value instead makes that collision astronomically unlikely.
    Deterministic: the same ``value``/``max_length``/``hash_length``
    always produces the same result, so retries/idempotent lookups that
    reference a previously truncated id remain stable across calls.
    Returns ``value`` unchanged when it already fits within
    ``max_length`` — this never rewrites an id that was already valid.
    """
    if len(value) <= max_length:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:hash_length]
    suffix = f"-{digest}"
    prefix_length = max_length - len(suffix)
    if prefix_length <= 0:
        # max_length is too small to hold any readable prefix plus the
        # separator — fall back to a pure hash slice. Still deterministic
        # and still effectively unique per input; only reachable with an
        # unreasonably small max_length (Batch's own limit is 64).
        return digest[:max_length]
    return f"{value[:prefix_length]}{suffix}"
