# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Shared, backend-neutral plumbing for the five workload spec builders.

Every HASTE workload (training, inference, embedding, imagery preparation,
artifact packaging) describes its submission as a
``hastegeo.core.models.compute.ComputeJobSpec`` and submits it through
``hastegeo.core.runners.execution_service.ComputeExecutionService`` (plan.md
Phase 8). This module holds the parts of that translation that are identical
for all five so they are implemented — and tested — once:

* the container work-directory contract (``HASTE_JOB_WORKDIR``);
* HASTE's ``<project-hash>/<task-id>`` output prefix and its blob URI;
* deterministic, pre-queue task/execution identifiers;
* backend-preference resolution (request → workload override → default);
* the execution service/registry wiring that preserves per-workload compute
  target routing;
* ``ComputeJobState`` → existing HASTE status-string mapping.

Nothing here knows an ``AZURE_BATCH_*`` environment-variable name: all
runtime settings come from ``Config.get_compute_runtime_config()``, which
owns the neutral-setting-then-legacy-fallback resolution.
"""

from typing import Dict, List, Optional, Sequence

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    ComputeBackend,
    ComputeContainerRef,
    ComputeError,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobState,
    ComputeOutput,
    ComputeResources,
    ComputeTags,
    ComputeWorkload,
    InputKind,
    OutputPersistenceMode,
)
from hastegeo.core.utils.metadata import MetadataUtils

#: Canonical, application-owned working-directory variable every adapter
#: exports before the workload command runs (design.md#work-directory-
#: contract). Azure Batch exports it from ``AZ_BATCH_TASK_WORKING_DIR``,
#: the local Docker adapter sets it directly, and the Azure ML adapter
#: binds it to the job's durable named output.
JOB_WORKDIR_ENV = "HASTE_JOB_WORKDIR"

#: Shell reference to :data:`JOB_WORKDIR_ENV` for generated commands. This
#: is what processor-built commands use — never a provider-specific
#: variable name.
JOB_WORKDIR = f"${JOB_WORKDIR_ENV}"

#: Placeholder token the *container images* substitute inside a generated
#: config file (``docker/{training,imageryprep}/scripts/set_dirs.sh`` runs
#: ``sed`` for exactly this literal and replaces it with the resolved
#: ``HASTE_JOB_WORKDIR`` value).
#:
#: Generated YAML/JSON configs are read by the container *after*
#: substitution, so they cannot use a shell reference like
#: :data:`JOB_WORKDIR` — nothing expands environment variables inside a
#: YAML value. The token therefore stays the one already-published images
#: understand; it is defined here, once, so no processor has to name a
#: provider variable itself. ``set_dirs.sh`` resolves it from
#: ``HASTE_JOB_WORKDIR`` first and only falls back to the legacy Batch
#: variable, so the substituted value is the canonical work directory on
#: every backend.
CONTAINER_CONFIG_WORKDIR_TOKEN = "AZ_BATCH_TASK_WORKING_DIR"

#: Backend profile name per workload. Persisted on the
#: ``ComputeJobHandle`` (``backendProfile``) and used by
#: :func:`build_execution_service` to bind each workload to its own
#: provider target candidates, so imagery preparation and artifact
#: packaging keep running on the CPU pools while the model workloads keep
#: running on the GPU pools (design.md#workload-migration-matrix).
_WORKLOAD_PROFILE: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "training",
    ComputeWorkload.INFERENCE: "inference",
    ComputeWorkload.EMBEDDING: "embedding",
    ComputeWorkload.IMAGERY_PREPARATION: "imageryprep",
    ComputeWorkload.ARTIFACT_PACKAGING: "artifacts",
}


def compute_profile(workload: ComputeWorkload) -> str:
    """Return the backend profile name used for ``workload``."""
    return _WORKLOAD_PROFILE[workload]


def new_task_id(prefix: str) -> str:
    """Return a fresh HASTE task id (``<prefix>-<uuid4>``).

    The value doubles as the ``ComputeJobSpec.executionId``: it is
    generated once, *before* the work is queued, persisted on the pending
    job record, and reused verbatim by the postprocessor, so a duplicate
    queue delivery can never mint a second identifier for the same run
    (design.md#idempotent-submission). Only a new user-triggered run calls
    this again.
    """
    if not prefix or not prefix.strip():
        raise ValueError("prefix must not be empty")
    return f"{prefix.strip()}-{MetadataUtils.generate_id()}"


def output_prefix(project_id: str, task_id: str) -> str:
    """Return HASTE's canonical ``<project-hash>/<task-id>`` blob prefix.

    Unchanged from the pre-compute-layer processors: every workload's
    artifacts land here regardless of backend, so existing result URLs
    keep resolving.
    """
    if not project_id:
        raise ValueError("project_id is required to build an output prefix")
    if not task_id:
        raise ValueError("task_id is required to build an output prefix")
    return f"{MetadataUtils.hash_string(project_id)}/{task_id}"


def output_uri(container_url: str, prefix: str) -> str:
    """Join a container URL and a blob prefix into an output destination.

    Adapters split this back into ``(container_url, prefix)``; keeping the
    join in one place guarantees they see exactly the container/prefix pair
    the pre-migration processors passed to Azure Batch.
    """
    if not container_url:
        raise ValueError("container_url is required to build an output URI")
    return f"{container_url.rstrip('/')}/{prefix.strip('/')}"


def file_input(source_uri: str, destination: str) -> ComputeInput:
    """A single downloaded file staged at ``destination``."""
    return ComputeInput(
        sourceUri=source_uri,
        kind=InputKind.FILE,
        destinationRelativePath=destination,
    )


def folder_input(source_uri: str, destination: str) -> ComputeInput:
    """A whole blob prefix staged beneath ``destination``.

    The provider preserves the source directory structure under
    ``destination`` (Azure Batch ``ResourceFile.blobPrefix`` semantics),
    which the artifact-packaging workload depends on.
    """
    return ComputeInput(
        sourceUri=source_uri,
        kind=InputKind.FOLDER,
        destinationRelativePath=destination,
    )


def workspace_output(
    *,
    name: str,
    pattern: str,
    container_url: str,
    prefix: str,
    live: bool = False,
) -> ComputeOutput:
    """Build a ``ComputeOutput`` for one workspace-relative pattern.

    ``live`` selects ``LIVE_MOUNT`` persistence, required wherever HASTE
    reads a file *while the job is still running* (TensorBoard events,
    ``workflow_progress.log``, the imagery/embedding friendly logs). The
    default, ``UPLOAD_ON_COMPLETION``, matches Azure Batch's
    ``taskCompletion`` upload condition for artifacts only consumed after
    the job ends.
    """
    return ComputeOutput(
        name=name,
        sourceRelativePattern=pattern,
        destinationUri=output_uri(container_url, prefix),
        persistenceMode=(
            OutputPersistenceMode.LIVE_MOUNT
            if live
            else OutputPersistenceMode.UPLOAD_ON_COMPLETION
        ),
    )


def container_ref(
    runtime: dict, *, working_directory: str = "."
) -> ComputeContainerRef:
    """Build the container reference from a runtime-config dict.

    ``environmentReference`` is populated from the configured, immutable
    Azure ML environment version for the workload's image family when one
    is set; Azure Batch and the local Docker adapter ignore the field.
    """
    return ComputeContainerRef(
        imageReference=runtime["image"],
        environmentReference=runtime.get("environment_reference"),
        workingDirectory=working_directory,
    )


def container_resources(runtime: dict) -> ComputeResources:
    """Build the neutral resource request from a runtime-config dict."""
    return ComputeResources(
        accelerator=runtime.get("accelerator"),
        nodeCount=1,
        sharedMemoryMb=runtime.get("shared_memory_mb"),
        allowSpot=False,
    )


def spec_tags(
    *,
    workload: ComputeWorkload,
    project_id: str,
    task_id: str,
    image_layer_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> ComputeTags:
    """Build provider tags. Only identifiers — never URLs or user data."""
    return ComputeTags(
        project=project_id,
        imageLayer=image_layer_id,
        model=model_id,
        task=task_id,
        workload=workload,
    )


def resolve_backend_preference(
    *,
    requested: Optional[ComputeBackend],
    workload: ComputeWorkload,
    config: Optional[Config] = None,
) -> ComputeBackend:
    """Resolve the backend preference for one submission.

    Order (design.md#backend-resolution-order):

    1. the preference carried on the request/record — either supplied by
       the caller on this run or inherited from the originating job of an
       automatic follow-on (both arrive here as ``requested``);
    2. the configured per-workload override
       (``COMPUTE_BACKEND_<WORKLOAD>``);
    3. the configured global default (``COMPUTE_BACKEND_DEFAULT``, or its
       deprecated ``RUNNER_TYPE`` alias).

    ``ComputeBackend.AUTO`` is returned as-is: resolving it needs live
    capacity, which is ``ComputeExecutionService``/``ComputeRouter``'s job,
    not a caller's.
    """
    if requested is not None:
        return requested
    compute_config = (config or Config()).get_compute_config()
    override = compute_config["backend_overrides"].get(workload)
    if override is not None:
        return override
    return compute_config["default_backend"]


def follow_on_backend(
    selected: ComputeBackend, *, config: Optional[Config] = None
) -> Optional[ComputeBackend]:
    """Return the backend an automatic follow-on should inherit, or ``None``.

    ``None`` means "do not pin anything": with
    ``COMPUTE_FOLLOW_ON_INHERITS_BACKEND`` disabled, the follow-on resolves
    its own backend from configuration instead of the originating job's.
    An explicit preference supplied on a later request always wins over an
    inherited one, because it arrives as ``requested`` in
    :func:`resolve_backend_preference`.
    """
    compute_config = (config or Config()).get_compute_config()
    if not compute_config["follow_on_inherits_backend"]:
        return None
    return selected


def follow_on_backend_for_record(
    record, *, config: Optional[Config] = None
) -> Optional[ComputeBackend]:
    """Backend an automatic follow-on of ``record`` should request.

    Reads the backend the originating job was submitted on — the
    processor persists it on the record's ``computeBackend`` after
    submission — and applies the inheritance policy. ``None`` when the
    record carries no backend, or when inheritance is disabled.
    """
    selected = getattr(record, "computeBackend", None)
    if selected is None:
        return None
    return follow_on_backend(selected, config=config)


def backend_name(backend) -> Optional[str]:
    """Return a plain, loggable backend name (``None`` when unset).

    Used at logging boundaries so a caller never formats an enum (or,
    worse, a whole record) into a log line.
    """
    return getattr(backend, "value", backend)


def validate_backend_request(
    requested: Optional[ComputeBackend],
    workload: ComputeWorkload,
    *,
    config: Optional[Config] = None,
) -> Optional[str]:
    """Return a user-safe error message if ``requested`` cannot possibly
    run, or ``None`` when it is acceptable.

    Only deterministically knowable problems are reported, so a launch
    request fails fast with 400 instead of failing later inside a queue
    worker:

    * ``azure_ml`` requested while ``AML_MODE`` is ``Disabled``;
    * ``auto`` requested with no ``COMPUTE_AUTO_CANDIDATES_<WORKLOAD>``
      configured.

    Anything that depends on live provider state (quota, capacity, node
    health) is deliberately *not* checked here.
    """
    if requested is None:
        return None
    config = config or Config()
    if requested == ComputeBackend.AZURE_ML:
        try:
            Config.validate_aml_config(
                config.get_aml_config(), workload=workload
            )
        except ValueError as exc:
            return (
                "computeBackend 'azure_ml' is not configured for this "
                f"workload: {exc}"
            )
    if requested == ComputeBackend.AUTO:
        # Imported lazily: this is the only place the API layer needs the
        # router's env parsing, and importing the runners package eagerly
        # would pull adapter modules into the HTTP function app.
        from hastegeo.core.runners.router import candidates_from_env

        if not candidates_from_env(workload):
            return (
                "computeBackend 'auto' is not configured for this "
                "workload; no candidate backends are set."
            )
    return None


def backend_rejection_message(
    requested: Optional[ComputeBackend],
    workload: ComputeWorkload,
    *,
    config: Optional[Config] = None,
) -> Optional[str]:
    """Return a user-safe message when the backend this request would run
    on cannot possibly work, else ``None``.

    Unlike :func:`validate_backend_request`, this resolves an omitted
    preference through the configured workload/global default *first*, so
    a deployment whose default is a backend it has not enabled (e.g.
    ``COMPUTE_BACKEND_DEFAULT=azure_ml`` with ``AML_MODE=Disabled``) fails
    the request deterministically instead of queueing work that can only
    fail in a worker.

    A malformed compute configuration (an unrecognized backend name in
    ``COMPUTE_BACKEND_*``/``RUNNER_TYPE``, a broken ``auto`` candidate
    list) is reported the same way rather than raised: the request cannot
    be honored either way, and the caller gets a message naming the
    problem instead of an opaque failure.
    """
    config = config or Config()
    try:
        effective = resolve_backend_preference(
            requested=requested, workload=workload, config=config
        )
        return validate_backend_request(effective, workload, config=config)
    except (ComputeError, ValueError) as exc:
        return f"computeBackend cannot be used for this workload: {exc}"


def build_execution_service(
    config: Optional[Config] = None,
    *,
    registry=None,
):
    """Build a ``ComputeExecutionService`` with per-workload profiles bound
    to their configured compute targets.

    ``RunnerRegistry`` constructs adapters from configuration alone, which
    would put every workload on one Azure Batch pool. HASTE routes each
    workload to its own ordered pool candidates
    (``batch-compute-expansion``), so when this function creates the
    registry it also registers one Azure Batch factory per workload
    profile, each carrying that workload's ``target_candidates`` from
    ``Config.get_compute_runtime_config()``. Callers select the profile by
    passing ``profile=compute_profile(...)`` to ``submit()``; the chosen
    profile is persisted on the handle, so later lifecycle calls resolve
    the same adapter configuration.

    A caller-supplied ``registry`` is used **as-is**: its registrations are
    the caller's contract (a test's fake adapters, or a deployment that
    wires its own factories), and silently overwriting them would replace
    those adapters with real provider ones.

    Adapters stay lazily constructed: the factories below import their
    provider module only when a submission actually needs that backend, so
    a local/AML-only deployment never imports the Batch SDK (and vice
    versa). Backends other than Azure Batch fall through to the registry's
    own lazy default factory for every profile.
    """
    # Imported here rather than at module import time so importing this
    # helper (e.g. from an HTTP route that only validates a request) does
    # not drag in the runners package.
    from hastegeo.core.runners.execution_service import ComputeExecutionService
    from hastegeo.core.runners.registry import RunnerRegistry

    config = config or Config()
    if registry is not None:
        return ComputeExecutionService(registry=registry)

    registry = RunnerRegistry(config)
    for workload in ComputeWorkload:
        registry.register(
            ComputeBackend.AZURE_BATCH,
            _azure_batch_factory(config, workload),
            profile=compute_profile(workload),
        )
    return ComputeExecutionService(registry=registry)


def _azure_batch_factory(config: Config, workload: ComputeWorkload):
    """Return a lazy factory building the Batch adapter for ``workload``."""

    def _factory():
        from hastegeo.core.runners.azure_batch import AzureBatchRunner

        targets: Sequence[str] = config.get_compute_runtime_config(workload)[
            "target_candidates"
        ]
        candidates: List[str] = [t for t in targets if t]
        return AzureBatchRunner(
            config=config,
            pool_id=candidates[0] if candidates else None,
            candidate_pool_ids=candidates or None,
        )

    return _factory


#: ``ComputeJobState`` values that mean the job is still on its way to a
#: terminal state. Everything here maps to HASTE's single existing
#: "in progress" status string — the user-visible vocabulary is unchanged
#: by the finer-grained provider states.
_IN_FLIGHT_STATES = frozenset(
    {
        ComputeJobState.PENDING,
        ComputeJobState.SUBMITTING,
        ComputeJobState.QUEUED,
        ComputeJobState.PREPARING,
        ComputeJobState.RUNNING,
    }
)


def map_state_to_status(
    state: ComputeJobState, config: Optional[Config] = None
) -> str:
    """Map a neutral ``ComputeJobState`` to an existing HASTE status string.

    The four HASTE statuses (``Queued``/``InProgress``/``Processed``/
    ``Failed``/``Cancelled``) are unchanged — this only decides which of
    them a provider state corresponds to:

    * ``succeeded`` → ``Processed``
    * ``failed`` → ``Failed``
    * ``cancelled`` → ``Cancelled``
    * everything else (pending/submitting/queued/preparing/running) →
      ``InProgress``, exactly like the pre-migration
      ``get_task_status()`` contract.
    """
    status_types = (config or Config()).get_status_types()
    if state == ComputeJobState.SUCCEEDED:
        return status_types.COMPLETED.value
    if state == ComputeJobState.FAILED:
        return status_types.FAILED.value
    if state == ComputeJobState.CANCELLED:
        return status_types.CANCELLED.value
    if state in _IN_FLIGHT_STATES:
        return status_types.IN_PROGRESS.value
    raise ValueError(f"unmapped ComputeJobState: {state!r}")


def handle_log_fields(handle: Optional[ComputeJobHandle]) -> dict:
    """Return the identifier-only fields safe to log for a handle.

    Never includes ``outputUri`` or any other URL: log lines carry
    identifiers and the selected backend, never signed URLs or provider
    credentials (design.md#security, #observability).
    """
    if handle is None:
        return {"executionId": None, "backend": None, "providerJobId": None}
    return {
        "executionId": handle.executionId,
        "backend": handle.selectedBackend.value,
        "profile": handle.backendProfile,
        "providerJobId": handle.providerJobId,
        "providerTaskId": handle.providerTaskId,
        "routingReason": handle.routingReason,
    }


__all__ = [
    "CONTAINER_CONFIG_WORKDIR_TOKEN",
    "JOB_WORKDIR",
    "JOB_WORKDIR_ENV",
    "backend_name",
    "backend_rejection_message",
    "build_execution_service",
    "compute_profile",
    "container_ref",
    "container_resources",
    "file_input",
    "folder_input",
    "follow_on_backend",
    "follow_on_backend_for_record",
    "handle_log_fields",
    "map_state_to_status",
    "new_task_id",
    "output_prefix",
    "output_uri",
    "resolve_backend_preference",
    "spec_tags",
    "validate_backend_request",
    "workspace_output",
]
