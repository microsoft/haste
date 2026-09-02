# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Read-time helpers bridging legacy ``jobId``/``taskId`` job records and the
backend-neutral ``ComputeJobHandle`` (``hastegeo.core.models.compute``).

Job records (``TrainingJob``, ``InferenceJob``, ``ImageryPreprocessJob``,
``ZipJob`` — see ``hastegeo.core.models.projects``) carry an *optional*
``computeJob: ComputeJobHandle`` field alongside the legacy ``jobId``/
``taskId`` strings. Deliberately, no synthesized handle is ever attached at
Pydantic construction time: a legacy record only ever has ``jobId``/
``taskId`` on hand, never the ``outputUri``/target context a valid
``ComputeJobHandle`` requires (see data-model.md#legacy-compatibility). The
caller must supply that context explicitly — ``resolve_compute_job_handle``
below is the one place that decides, uniformly, whether a job record's
compute submission is represented by a new-style handle, a legacy pair that
can be synthesized given the extra context, or nothing yet (a job that
hasn't been submitted).

This module intentionally has no dependency on
``hastegeo.core.models.projects`` — it is written against a minimal
structural shape (``ComputeJobRecord``) so it works with any of the four job
record types (and any future one) without a hard import cycle.
"""

from copy import deepcopy
from typing import (
    Iterable,
    List,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

from hastegeo.core.models.compute import (
    ComputeJobHandle,
    synthesize_legacy_batch_handle,
)
from hastegeo.core.utils.metadata import MetadataUtils

#: Characters accepted verbatim in a deterministic executionId
#: (mirrors ``ComputeJobSpec.executionId``'s own validator in
#: ``hastegeo.core.models.compute`` — letters, digits, '.', '_', '-').
_EXECUTION_ID_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)

#: Fallback prefix used when every candidate part sanitizes to nothing
#: (e.g. a part that is only punctuation/whitespace).
_DEFAULT_EXECUTION_ID_PREFIX = "job"

#: Azure Batch task IDs are capped at 64 characters, and the Batch adapter
#: uses ``ComputeJobSpec.executionId`` verbatim as the task ID (see
#: ``AzureBatchRunner.submit``) — so this is the hard ceiling for the
#: *whole* identifier this helper returns, not just its hash portion.
_EXECUTION_ID_MAX_LENGTH = 64

#: Truncated sha256 hex length used for the entropy portion of the id.
#: 32 hex characters is 128 bits — still collision-resistant for HASTE's
#: job volumes — chosen so a readable prefix plus separator always fits
#: within ``_EXECUTION_ID_MAX_LENGTH`` (see ``_EXECUTION_ID_PREFIX_MAX_
#: LENGTH`` below).
_EXECUTION_ID_HASH_LENGTH = 32

#: Longest the readable prefix may be: whatever's left of the 64-char
#: budget after the hash and the '-' separator between prefix and hash.
_EXECUTION_ID_PREFIX_MAX_LENGTH = (
    _EXECUTION_ID_MAX_LENGTH - _EXECUTION_ID_HASH_LENGTH - 1
)


@runtime_checkable
class ComputeJobRecord(Protocol):
    """Structural shape shared by ``TrainingJob``, ``InferenceJob``,
    ``ImageryPreprocessJob``, and ``ZipJob``.

    Not meant to be subclassed — it exists purely so
    ``resolve_compute_job_handle`` can be type-checked against any job
    record without importing ``hastegeo.core.models.projects``.
    """

    computeJob: Optional[ComputeJobHandle]
    jobId: Optional[str]
    taskId: Optional[str]


def resolve_compute_job_handle(
    job: ComputeJobRecord,
    *,
    output_uri: Optional[str] = None,
    target_id: Optional[str] = None,
) -> Optional[ComputeJobHandle]:
    """Resolve ``job``'s compute submission to a single ``ComputeJobHandle``
    shape, regardless of whether it was submitted before or after the
    backend-neutral compute layer existed.

    Resolution order:

    1. If ``job.computeJob`` is already set, return it unchanged — a
       persisted handle is always authoritative over ``jobId``/``taskId``.
    2. Otherwise, if ``job.jobId``/``job.taskId`` are both present *and*
       the caller supplied ``output_uri``, synthesize a legacy Batch
       ``ComputeJobHandle`` via
       ``hastegeo.core.models.compute.synthesize_legacy_batch_handle``.
    3. Otherwise, return ``None`` — there is either no submission yet, or
       not enough context (``output_uri``) to synthesize one. This never
       raises for a job that simply hasn't been submitted: an absent
       ``computeJob`` with absent ``jobId``/``taskId`` is the normal shape
       of a not-yet-submitted job record.

    ``output_uri``/``target_id`` are never read from ``job`` itself —
    legacy job records don't reliably carry that context (data-model.md's
    rationale for not synthesizing at construction time), so the caller
    (which knows the record's storage/output conventions) must supply it
    explicitly.
    """
    existing = job.computeJob
    if existing is not None:
        return existing

    job_id = job.jobId
    task_id = job.taskId
    if not job_id or not task_id:
        return None
    if not output_uri:
        return None

    return synthesize_legacy_batch_handle(
        job_id=job_id,
        task_id=task_id,
        output_uri=output_uri,
        target_id=target_id,
    )


def selected_backend_of(job: Optional[ComputeJobRecord]) -> Optional[str]:
    """Return the backend name recorded on ``job``'s persisted handle.

    ``None`` when the job has no handle yet (not submitted, or a legacy
    record). Returns the plain enum *value* so callers — including log
    lines — never have to touch the handle itself.
    """
    handle = getattr(job, "computeJob", None) if job is not None else None
    if handle is None:
        return None
    return handle.selectedBackend.value


def clear_compute_handles(*job_records) -> None:
    """Drop the runtime compute handle from every supplied job record.

    ``computeJob`` is server-owned: it records which provider job HASTE
    submitted, and every later status/output/cancel call is dispatched by
    it. Accepting one from a request body would let a caller make HASTE
    poll — or cancel — an arbitrary provider job, so a request-handling
    boundary clears it from the record(s) a request launches. Each
    argument may be a single record, a list of records, or ``None``.
    """
    for job in job_records:
        if job is None:
            continue
        entries = job if isinstance(job, (list, tuple)) else [job]
        for entry in entries:
            if entry is not None:
                entry.computeJob = None


def authoritative_job_history(
    requested: Optional[Sequence],
    stored: Optional[Iterable],
) -> List:
    """Return the job history a launch request must proceed with.

    Job records (and the compute handles on them) are written by HASTE,
    never by a caller, so the *stored* history is authoritative whenever it
    is available: a request body may not add, remove, or rewrite a past
    job's runtime handle, but a legitimate client round-tripping the record
    it fetched must not lose that history either (which naively clearing
    every handle in the request would do).

    Falls back to the request's own records — with every handle cleared —
    only when there is no stored history to trust yet (a brand-new
    resource, or storage that has no record of it).
    """
    if stored is not None:
        return list(stored)
    entries = list(requested or [])
    clear_compute_handles(entries)
    return entries


MODEL_TRAINING_RUNTIME_FIELDS = ("trainingJob",)
MODEL_INFERENCE_RUNTIME_FIELDS = (
    "inferenceJobs",
    "currentInferenceTaskId",
)
MODEL_EMBEDDING_RUNTIME_FIELDS = ("embeddingJob",)
MODEL_INFERENCE_CLIENT_FORBIDDEN_FIELDS = (
    "gpkgUrl",
    "predictedDamageLayerUrl",
    "inferenceOutputPath",
)


#: ``ImageLayer`` fields the imagery workflow owns end to end: the compute
#: submission record, the progress/status the queue worker maintains, and
#: every artifact URL/statistic ``prepare-imagery`` produces. A client may
#: edit a layer's descriptive and input fields, but never these — they are
#: written by HASTE and must survive an edit exactly as stored (an edit
#: request carrying a forged ``preprocessJob.computeJob`` must not be able
#: to redirect polling or cancellation at another provider job).
IMAGE_LAYER_WORKFLOW_OWNED_FIELDS = (
    "preprocessJob",
    "status",
    "statusMessage",
    "currentStep",
    "totalSteps",
    "progressPct",
    "imageryPath",
    "labelProjectId",
    "labelProject",
    "labelsUrl",
    "preEventPreviewUrls",
    "preEventMosaicCogImageryUrl",
    "preEventProcessedImageryUrl",
    "postEventPreviewUrls",
    "postEventMosaicCogImageryUrl",
    "postEventProcessedImageryUrl",
    "processedImageryUrls",
    "rawImageryUrls",
    "previewSourceImageryUrls",
    "normalizationMeans",
    "normalizationStds",
    "normalizationFactor",
    "buildingFootprintsUrl",
    "validAreaMaskUrl",
)
IMAGE_LAYER_CLIENT_FORBIDDEN_CREATE_FIELDS = tuple(
    name
    for name in IMAGE_LAYER_WORKFLOW_OWNED_FIELDS
    if name != "preprocessJob"
)


def preserve_workflow_owned_fields(
    requested, stored, field_names: Iterable[str]
) -> None:
    """Copy every ``field_names`` value from ``stored`` onto ``requested``.

    The same "server state wins" rule as :func:`authoritative_job_history`,
    applied to a single record being *edited* rather than a job history: a
    request may change the fields a user owns, while everything HASTE's own
    workflow writes — the compute submission, runtime status/progress, and
    produced artifact URLs — is restored from what is stored, so a request
    body can neither forge nor erase it.

    Does nothing when ``stored`` is ``None`` (nothing authoritative to
    restore). Mutates ``requested`` in place.
    """
    if stored is None:
        return
    for name in field_names:
        setattr(requested, name, getattr(stored, name))


def restore_authoritative_fields(
    requested, stored, field_names: Iterable[str]
) -> None:
    """Restore server-owned fields, or reset them when no record exists.

    Launch requests may carry a round-tripped model with legitimate history
    or forged provider identifiers. Stored state wins when present. For a
    brand-new record, the model's defaults replace all request-supplied values.
    """
    source = stored if stored is not None else requested.__class__()
    for name in field_names:
        setattr(requested, name, deepcopy(getattr(source, name)))


def supplied_nonempty_fields(
    payload: dict, field_names: Iterable[str]
) -> List[str]:
    """Return server-owned fields explicitly populated by a client payload."""
    empty_values = (None, "", [], {})
    return [
        name
        for name in field_names
        if name in payload and payload[name] not in empty_values
    ]


def derive_execution_id(*parts: Optional[str]) -> str:
    """Build a deterministic, ``ComputeJobSpec.executionId``-safe
    identifier from one or more job-identity parts (e.g. a workload name
    plus a job/model UID).

    Deterministic: the same ``parts``, in the same order, always produce
    the same identifier — required for idempotent submission (design.md's
    "generate/validate the deterministic executionId before any provider
    call"). Uses ``MetadataUtils.hash_string`` (sha256, hex-encoded) for
    the same hashing convention already used elsewhere in HASTE, truncated
    to ``_EXECUTION_ID_HASH_LENGTH`` hex characters (128 bits — still
    collision-resistant for HASTE's job volumes). The first non-empty part
    additionally seeds a short, human-recognizable prefix — sanitized to
    the same character set the hash itself already satisfies — purely to
    make identifiers easier to recognize in logs/provider consoles; it
    never participates in uniqueness on its own.

    ``parts`` accepts ``None`` entries (callers may pass an optional
    identity segment through unchanged rather than filtering it first);
    ``None`` and blank/whitespace-only strings are both dropped before
    hashing.

    The full result is capped at ``_EXECUTION_ID_MAX_LENGTH`` (64)
    characters: the Azure Batch adapter uses ``executionId`` verbatim as
    the Batch task ID, and Batch task IDs are capped at 64 characters, so
    this helper must never hand back something the adapter can't submit
    as-is. The prefix is truncated (never the hash) to make room.

    Raises ``ValueError`` if every part is empty/blank, since a
    deterministic identifier cannot be derived from no identity at all.
    """
    cleaned = [
        part.strip() for part in parts if part is not None and part.strip()
    ]
    if not cleaned:
        raise ValueError(
            "derive_execution_id requires at least one non-empty part"
        )

    digest = MetadataUtils.hash_string("|".join(cleaned))[
        :_EXECUTION_ID_HASH_LENGTH
    ]

    prefix = "".join(
        char if char in _EXECUTION_ID_ALLOWED else "-" for char in cleaned[0]
    ).strip("-")[:_EXECUTION_ID_PREFIX_MAX_LENGTH]
    if not prefix:
        prefix = _DEFAULT_EXECUTION_ID_PREFIX

    execution_id = f"{prefix}-{digest}"
    assert len(execution_id) <= _EXECUTION_ID_MAX_LENGTH
    return execution_id
