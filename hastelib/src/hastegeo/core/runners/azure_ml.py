# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Azure Machine Learning (AML) ``ComputeRunner`` adapter.

Submits/polls/reads/cancels/finalizes AML command jobs behind the same
``ComputeRunner`` contract ``AzureBatchRunner``/``LocalRunner`` implement
(see ``base.py``, design.md#aml-submission-mapping, ADR-0005).

Lazy-import contract: the optional ``azure-ai-ml`` package (HASTE's
``azure-ml`` extra) is never imported at module scope, and no ``MLClient``
is constructed until an ``AzureMLRunner`` method that actually needs one is
called — a Batch/local-only deployment that never selects the ``azure_ml``
backend pays no import/initialization cost for it, even if this module
happens to be imported (design.md#configuration). ``azure-core``/
``azure-identity``/``azure-storage-blob`` are unconditional HASTE
dependencies already imported elsewhere (e.g. ``azure_batch.py``), so they
are imported at module scope here too.

Existing-resource-only contract: regardless of ``AML_MODE`` (``Create`` or
``Existing`` — this adapter does not distinguish between them), this
module never creates, updates, or deletes an AML workspace, compute
cluster, environment, or datastore. It only ever *consumes* resources that
must already exist (named by ``AML_SUBSCRIPTION_ID``/``AML_WORKSPACE_
NAME``/``AML_COMPUTE_<WORKLOAD>``/``AML_ENVIRONMENT_<FAMILY>``/etc — see
``config.py``). ``Existing`` is the supported Stage-1 path; any future
IaC-driven provisioning story for ``Create`` is out of this module's
scope. Submitted command jobs and their (retained) run history are the
only AML objects this module ever writes.
"""

import glob
import importlib
import os
import re
import shlex
import shutil
import tempfile
import threading
from typing import Dict, Iterable, List, Optional, Tuple, Union

from azure.core.exceptions import (
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from hastegeo.core.config import AML_IDENTITY_MODES, AML_MODES, Config
from hastegeo.core.models.compute import (
    TERMINAL_JOB_STATES,
    AzureMlProviderDetail,
    BackendConfigurationError,
    BackendUnavailableError,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeError,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeOutput,
    ComputeProviderDetail,
    ComputeResources,
    ComputeWorkload,
    InputDeliveryMode,
    InputKind,
    JobCancellationError,
    JobNotFoundError,
    OutputNotAvailableError,
    OutputPersistenceMode,
    SubmissionIndeterminateError,
    assert_no_credential_material,
    validate_environment_reference,
    validate_relative_path,
)
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils

from .base import (
    ComputeRunner,
    require_single_output_destination,
    split_destination_uri,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: ``COMPUTE_BACKEND_<WORKLOAD>``/``AML_COMPUTE_<WORKLOAD>`` env-var suffix
#: per workload. Duplicated (not imported) from ``config.py``'s private-ish
#: module constant of the same shape, and from ``router.py``'s own private
#: copy, because none of the three modules should depend on one another for
#: this — see ``config.py``'s comment on its own copy for the rationale.
_WORKLOAD_ENV_SUFFIX: Dict[ComputeWorkload, str] = {
    ComputeWorkload.TRAINING: "TRAINING",
    ComputeWorkload.INFERENCE: "INFERENCE",
    ComputeWorkload.EMBEDDING: "EMBEDDING",
    ComputeWorkload.IMAGERY_PREPARATION: "IMAGERYPREP",
    ComputeWorkload.ARTIFACT_PACKAGING: "ARTIFACTS",
}

#: Name of the single AML named output every submission binds to the
#: configured HASTE datastore (design.md's "one durable HASTE output root
#: via configured datastore URI"). ``HASTE_JOB_WORKDIR`` is bound directly
#: to this output's local mount/upload path (not a symlinked subfolder of
#: it) so every file a workload writes anywhere under its working
#: directory — root-level checkpoints, TensorBoard event files, logs,
#: manifests, as well as anything under an ``outputs/`` subfolder — lands
#: under the durable output root, matching training's actual layout
#: (design.md#workload-migration-matrix).
_OUTPUT_NAME = "haste_output"

#: Bootstrap-script umask (design.md#security's AML ENTRYPOINT-bypass
#: hardening): AML command jobs may run ``command`` directly against the
#: image without invoking its own ``ENTRYPOINT``, so any permission setup
#: an entrypoint would otherwise have done is not guaranteed. ``0022``
#: (the common shell default) leaves owner read/write/execute intact
#: while guaranteeing group/other at least read (and execute on
#: directories), regardless of the image's own default umask.
_BOOTSTRAP_UMASK = "0022"

#: Shell variable name the bootstrap script uses to capture and later
#: re-exit with the workload command's real exit code, after finalization
#: (``chmod``) has run — never the finalization step's own exit code.
_BOOTSTRAP_EXIT_CODE_VAR = "HASTE_INNER_EXIT_CODE"

#: Durable, provider-parity stdout/stderr capture file names (matching
#: Azure Batch's own standard ``stdout.txt``/``stderr.txt`` task files),
#: written directly under ``HASTE_OUTPUT_ROOT`` so a failed job's
#: diagnostics are readable via the same bounded durable-storage
#: ``read_output`` path other outputs use — never requiring a full SDK
#: output download just to see why a job failed.
_BOOTSTRAP_STDOUT_FILE = "stdout.txt"
_BOOTSTRAP_STDERR_FILE = "stderr.txt"

#: Bound on the SDK-download fallback read in ``read_output`` (never an
#: unbounded read of provider-managed storage — design.md#security).
_MAX_FALLBACK_READ_BYTES = 10 * 1024 * 1024  # 10 MiB

#: Max length of a derived AML job name — well under any documented AML
#: asset-name limit, chosen defensively rather than to the exact limit.
_MAX_JOB_NAME_LENGTH = 200

_JOB_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_-]+")

#: Sentinel distinguishing "blob not found at this candidate path" (keep
#: searching) from an actual (possibly falsy-looking, though never in
#: practice) blob read result in ``_try_read_blob``.
_BLOB_NOT_FOUND = object()

# AML job status strings (public values as documented for
# ``azure.ai.ml.entities.Job.status``; not imported from the SDK's own
# ``operations._run_history_constants.JobStatus`` because that module is
# private/unversioned — hardcoding the small, documented set here is safer
# against internal SDK reshuffles). Matched case-insensitively.
_AML_STATUS_MAP: Dict[str, ComputeJobState] = {
    "notstarted": ComputeJobState.SUBMITTING,
    "starting": ComputeJobState.SUBMITTING,
    "provisioning": ComputeJobState.PREPARING,
    "preparing": ComputeJobState.PREPARING,
    "queued": ComputeJobState.QUEUED,
    "running": ComputeJobState.RUNNING,
    # Still executing (post-processing / cancellation-in-flight) — not yet
    # terminal, so neither counts as SUCCEEDED/FAILED/CANCELLED until the
    # provider reports one of those explicitly (design.md's "Unknown
    # provider status" / "Cancellation races with completion" edge cases).
    "finalizing": ComputeJobState.RUNNING,
    "cancelrequested": ComputeJobState.RUNNING,
    "completed": ComputeJobState.SUCCEEDED,
    "failed": ComputeJobState.FAILED,
    "canceled": ComputeJobState.CANCELLED,
    "notresponding": ComputeJobState.FAILED,
    # A job that is not currently scheduled/executing but may resume;
    # nearest neutral state is QUEUED (rare for AML command jobs).
    "paused": ComputeJobState.QUEUED,
}

_HTTP_CONFLICT_STATUS_CODES = frozenset({409})


class UnmappedAmlJobStatusError(ComputeError):
    """An AML job reported a status string this adapter has no mapping for.

    Raised instead of guessing a ``ComputeJobState`` — design.md's "Unknown
    provider status" edge case: log the raw provider state server-side and
    fail explicitly rather than silently reporting ``running``.
    """


class AmbiguousOutputMatchError(ComputeError):
    """A non-exact ``read_output`` lookup matched more than one blob (or,
    via the SDK-download fallback, more than one downloaded file).

    Raised when ``relative_path`` is not found at the exact expected
    location and a bounded listing/search under the job's own output
    prefix finds more than one candidate via any of the nested-suffix or
    basename-prefix matching strategies — e.g. the same filename written
    under two different subdirectories, or two TensorBoard event files
    both starting with the requested basename. There is no single
    correct answer to return, so this is a typed, explicit failure rather
    than an arbitrary pick of "the first match".
    """


def _select_unique_match(
    matches: List[str], *, context: str, relative_path: str
) -> Optional[str]:
    """Resolve a list of non-exact match candidates to a single result.

    Shared by every non-exact matching strategy in both
    ``AzureMLRunner._read_output_from_durable_storage`` (blob names) and
    ``AzureMLRunner._read_output_via_sdk_fallback`` (local downloaded file
    paths), so "zero matches" and "more than one match" are handled
    identically regardless of which strategy — nested-suffix, basename-
    prefix, or (for the SDK fallback) exact-then-prefix glob — produced
    the candidate list. Returns ``None`` for zero matches (not yet
    available); raises ``AmbiguousOutputMatchError`` for more than one.
    """
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousOutputMatchError(
            f"{len(matches)} matches for {relative_path!r} within "
            f"{context}; cannot determine which one to read"
        )
    return matches[0]


def _lazy_import(module_name: str, *names: str) -> Tuple[object, ...]:
    """Import ``names`` from ``module_name`` on first use.

    Raises ``BackendConfigurationError`` (not a bare ``ImportError``) when
    the optional ``azure-ai-ml`` package is not installed, so a caller that
    never exercises the ``azure_ml`` backend never sees an unclassified
    import failure, and a deployment that *does* select it gets an
    actionable, typed error instead of a traceback into this module's
    internals.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise BackendConfigurationError(
            "the 'azure-ai-ml' package is not installed; install HASTE's "
            f"'azure-ml' extra to use the azure_ml compute backend ({exc})"
        ) from exc
    return tuple(getattr(module, name) for name in names)


def _lazy_ml_exceptions() -> Tuple[type, type]:
    """Lazily import ``(JobException, ValidationException)`` from
    ``azure.ai.ml.exceptions``.

    Both derive from the SDK's own ``MlException`` ->
    ``azure.core.exceptions.AzureError`` — a separate hierarchy from
    ``HttpResponseError`` (client-side/state-validation failures the SDK
    raises itself, not necessarily wrapping an HTTP response) — so they
    need their own ``except`` clauses alongside ``azure.core.exceptions``.
    Deliberately only these two documented, actionable classes are
    imported/caught (never a blanket ``MlException`` catch): narrower
    classes keep an unclassified, truly-unexpected SDK exception visible
    instead of silently absorbing it.
    """
    return _lazy_import(
        "azure.ai.ml.exceptions", "JobException", "ValidationException"
    )


_URL_QUERY_RE = re.compile(r"(https?://[^\s'\"]+?)\?[^\s'\")]*")


def _sanitize_error_text(value: object) -> str:
    """Best-effort scrub of any embedded signed URL query string from an
    SDK exception's message before it is logged or wrapped into a typed
    error (design.md#security: never leak a signed URL/token).
    """
    text = str(value)
    return _URL_QUERY_RE.sub(r"\1?<redacted>", text)


def _is_conflict_error(exc: HttpResponseError) -> bool:
    status_code = getattr(exc, "status_code", None)
    return status_code in _HTTP_CONFLICT_STATUS_CODES


#: HTTP status treated as a throttling/rate-limit signal — a pre-processing
#: rejection, not a possible-partial-creation outcome.
_HTTP_TOO_MANY_REQUESTS = 429


def _classify_submission_http_error(exc: HttpResponseError) -> ComputeError:
    """Classify a non-conflict ``HttpResponseError`` raised by
    ``jobs.create_or_update`` (design.md#idempotent-submission).

    - A 429 (throttled) response is a pre-processing rejection — Azure
      always rejects throttled requests before doing any work, so the job
      was never created; classified as ``BackendUnavailableError`` (an
      availability signal ``ComputeExecutionService``'s ``auto`` routing
      can retry against another candidate) rather than reconciled.
    - A 5xx response leaves the outcome genuinely ambiguous — the request
      may have reached the provider and created the job before the
      response was lost — so it is ``SubmissionIndeterminateError``,
      which callers must reconcile via ``get()``, never blindly retry.
    - Any other (deterministic 4xx validation/configuration) status is
      ``BackendConfigurationError``: the request could not have created
      the job.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code == _HTTP_TOO_MANY_REQUESTS:
        return BackendUnavailableError(
            "Azure Machine Learning throttled the submission request "
            f"(429): {_sanitize_error_text(exc)}"
        )
    if status_code is not None and 500 <= status_code < 600:
        return SubmissionIndeterminateError(
            f"Azure Machine Learning returned a server error "
            f"({status_code}) submitting the job; outcome is "
            f"indeterminate: {_sanitize_error_text(exc)}"
        )
    return BackendConfigurationError(
        "Azure Machine Learning rejected job submission "
        f"({status_code}): {_sanitize_error_text(exc)}"
    )


class AzureMLRunner(ComputeRunner):
    """``ComputeRunner`` adapter backed by Azure Machine Learning command
    jobs (``azure-ai-ml`` SDK v2), per design.md#aml-submission-mapping.
    """

    def __init__(self, config: Config = None):
        super().__init__(config)
        self.config = config or Config()
        self.aml_config = self.config.get_aml_config()
        self.logger = Logger.get_logger(__name__)
        self._client = None
        self._client_lock = threading.Lock()
        self._credential_instance = None

    # -- lazy client/credential ----------------------------------------

    def _credential(self) -> DefaultAzureCredential:
        # DefaultAzureCredential/azure-storage-blob are unconditional HASTE
        # dependencies (already imported at module scope, mirroring
        # azure_batch.py) — only the azure-ai-ml SDK itself is lazy.
        if self._credential_instance is None:
            self._credential_instance = DefaultAzureCredential()
        return self._credential_instance

    def _get_client(self):
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    (MLClient,) = _lazy_import("azure.ai.ml", "MLClient")
                    self._client = MLClient(
                        self._credential(),
                        subscription_id=self.aml_config["subscription_id"],
                        resource_group_name=self.aml_config["resource_group"],
                        workspace_name=self.aml_config["workspace_name"],
                        # Never logging_enable/debug (never surface job
                        # payloads/URLs to client-side SDK logs); never
                        # opt this deployment into SDK telemetry.
                        enable_telemetry=False,
                    )
        return self._client

    # -- configuration resolution ---------------------------------------

    def _validate_config(self) -> None:
        mode = self.aml_config["mode"]
        if mode not in AML_MODES:
            raise BackendConfigurationError(
                f"AML_MODE={mode!r} must be one of {AML_MODES}"
            )
        if mode == "Disabled":
            raise BackendConfigurationError(
                "Azure Machine Learning is disabled (AML_MODE=Disabled); "
                "set AML_MODE to 'Create' or 'Existing' to select the "
                "azure_ml compute backend — this adapter does not "
                "distinguish between them and does not provision "
                "resources for either: the workspace/compute/"
                "environment/datastore named below must already exist"
            )
        missing = [
            env_name
            for key, env_name in (
                ("subscription_id", "AML_SUBSCRIPTION_ID"),
                ("resource_group", "AML_RESOURCE_GROUP"),
                ("workspace_name", "AML_WORKSPACE_NAME"),
                ("datastore_name", "AML_DATASTORE_NAME"),
            )
            if not self.aml_config.get(key)
        ]
        if missing:
            raise BackendConfigurationError(
                "Azure Machine Learning is not configured. Missing "
                "application settings: " + ", ".join(missing)
            )
        identity_mode = self.aml_config["identity_mode"]
        if identity_mode not in AML_IDENTITY_MODES:
            raise BackendConfigurationError(
                f"AML_IDENTITY_MODE={identity_mode!r} must be one of "
                f"{AML_IDENTITY_MODES}"
            )
        if identity_mode == "managed" and not self.aml_config.get(
            "managed_identity_id"
        ):
            raise BackendConfigurationError(
                "AML_IDENTITY_MODE=managed requires AML_MANAGED_IDENTITY_ID "
                "to be set"
            )

    def _compute_for_workload(
        self, workload: ComputeWorkload, target_override: Optional[str] = None
    ) -> str:
        if target_override:
            return target_override
        compute_name = self.aml_config["compute_by_workload"].get(workload)
        if not compute_name:
            suffix = _WORKLOAD_ENV_SUFFIX[workload]
            raise BackendConfigurationError(
                f"no AML compute cluster configured for workload "
                f"{workload.value!r} (set AML_COMPUTE_{suffix})"
            )
        return compute_name

    def _environment_reference_for(self, spec: ComputeJobSpec) -> str:
        """Resolve the immutable AML environment version for ``spec``.

        Prefers an explicit ``spec.container.environmentReference`` when
        the caller (a workload's ``build_*_job_spec()``) already supplied
        one — it is never overridden. Otherwise falls back to the
        workload's image-family setting (``AML_ENVIRONMENT_TRAINING`` for
        training/inference/embedding, ``AML_ENVIRONMENT_IMAGERYPREP`` for
        imagery preparation/artifact packaging), matching the AML IaC's
        per-image-family environment registration rather than deriving an
        environment lookup key from an arbitrary container image
        reference.
        """
        if spec.container.environmentReference:
            return validate_environment_reference(
                spec.container.environmentReference
            )
        reference = self.aml_config["environment_by_workload"].get(
            spec.workload
        )
        if not reference:
            env_name = Config.aml_environment_env_var_name_for_workload(
                spec.workload
            )
            raise BackendConfigurationError(
                "no AML environment configured for workload "
                f"{spec.workload.value!r} (set {env_name}, or supply "
                "container.environmentReference explicitly)"
            )
        return validate_environment_reference(reference)

    def _job_name_for(self, execution_id: str) -> str:
        prefix = self.aml_config["experiment_prefix"]
        sanitized = _JOB_NAME_SANITIZE_RE.sub("-", execution_id)
        name = f"{prefix}-{sanitized}".lower()
        return name[:_MAX_JOB_NAME_LENGTH]

    def _experiment_name_for(self, workload: ComputeWorkload) -> str:
        prefix = self.aml_config["experiment_prefix"]
        return f"{prefix}-{workload.value}"

    def _identity(self):
        identity_mode = self.aml_config["identity_mode"]
        (
            ManagedIdentityConfiguration,
            UserIdentityConfiguration,
        ) = _lazy_import(
            "azure.ai.ml.entities",
            "ManagedIdentityConfiguration",
            "UserIdentityConfiguration",
        )
        if identity_mode == "managed":
            return ManagedIdentityConfiguration(
                resource_id=self.aml_config["managed_identity_id"]
            )
        if identity_mode == "user":
            return UserIdentityConfiguration()
        # ``_validate_config`` should have already rejected any other
        # value before a submission gets this far.
        raise BackendConfigurationError(
            f"unsupported AML_IDENTITY_MODE={identity_mode!r}"
        )

    # -- ComputeRunner contract ------------------------------------------

    def validate(self, spec: ComputeJobSpec) -> None:
        self._validate_config()
        try:
            require_single_output_destination(spec.outputs)
        except ValueError as exc:
            raise BackendConfigurationError(str(exc)) from exc
        try:
            _resolve_output_layout(spec.outputs)
        except ValueError as exc:
            raise BackendConfigurationError(str(exc)) from exc
        self._compute_for_workload(
            spec.workload, spec.resources.targetOverride
        )
        self._environment_reference_for(spec)

    def submit(self, spec: ComputeJobSpec) -> ComputeJobHandle:
        self.validate(spec)
        job_name = self._job_name_for(spec.executionId)
        client = self._get_client()

        existing = self._get_existing_job(
            client, job_name, expected_execution_id=spec.executionId
        )
        if existing is not None:
            self.logger.info(
                "AML job %s already exists for executionId=%s; "
                "reconciling instead of resubmitting.",
                job_name,
                spec.executionId,
            )
            return self._handle_from_job(spec, existing)

        command_job = self._build_command_job(spec, job_name)
        JobException, ValidationException = _lazy_ml_exceptions()
        try:
            created = client.jobs.create_or_update(command_job)
        except (ValidationException, JobException) as exc:
            # Client-side/SDK-raised (not an HTTP response): the SDK
            # itself rejected the job specification (e.g. schema
            # validation) before or without a network round-trip — always
            # a deterministic configuration problem, never ambiguous.
            raise BackendConfigurationError(
                "Azure Machine Learning rejected the job specification: "
                f"{_sanitize_error_text(exc)}"
            ) from exc
        except ResourceExistsError as exc:
            reconciled = self._get_existing_job(
                client, job_name, expected_execution_id=spec.executionId
            )
            if reconciled is None:
                raise SubmissionIndeterminateError(
                    "Azure Machine Learning reported the job already "
                    f"exists, but it could not be retrieved: "
                    f"{_sanitize_error_text(exc)}"
                ) from exc
            return self._handle_from_job(spec, reconciled)
        except (ServiceRequestError, ServiceResponseError) as exc:
            # Network-level failure: the provider may or may not have
            # accepted the request. Reconcile via get(), never retry
            # create blindly (design.md#idempotent-submission).
            raise SubmissionIndeterminateError(
                "Azure Machine Learning submission outcome is "
                f"indeterminate for executionId={spec.executionId}: "
                f"{_sanitize_error_text(exc)}"
            ) from exc
        except HttpResponseError as exc:
            if _is_conflict_error(exc):
                reconciled = self._get_existing_job(
                    client, job_name, expected_execution_id=spec.executionId
                )
                if reconciled is not None:
                    return self._handle_from_job(spec, reconciled)
                raise SubmissionIndeterminateError(
                    "Azure Machine Learning reported a submission "
                    f"conflict, but the job could not be retrieved: "
                    f"{_sanitize_error_text(exc)}"
                ) from exc
            raise _classify_submission_http_error(exc) from exc

        return self._handle_from_job(spec, created)

    def _get_existing_job(
        self, client, job_name: str, *, expected_execution_id: str
    ):
        JobException, ValidationException = _lazy_ml_exceptions()
        try:
            job = client.jobs.get(job_name)
        except ResourceNotFoundError:
            return None
        except (ValidationException, JobException) as exc:
            raise BackendConfigurationError(
                f"Azure Machine Learning rejected the lookup for job "
                f"{job_name}: {_sanitize_error_text(exc)}"
            ) from exc
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise SubmissionIndeterminateError(
                f"could not confirm whether AML job {job_name} already "
                f"exists: {_sanitize_error_text(exc)}"
            ) from exc
        except HttpResponseError as exc:
            raise BackendUnavailableError(
                f"Azure Machine Learning job lookup failed for {job_name}: "
                f"{_sanitize_error_text(exc)}"
            ) from exc
        self._verify_reconciled_execution_id(job, expected_execution_id)
        return job

    def _verify_reconciled_execution_id(
        self, job, expected_execution_id: str
    ) -> None:
        """Guard against reconciling onto a same-named but unrelated job.

        The deterministic job name is derived from ``executionId``
        (``_job_name_for``), but names are sanitized/truncated, so two
        different ``executionId`` values could in principle collide on
        the same AML job name. Every submission tags its job with the
        ``executionId`` it was submitted for (``_sanitized_tags``)
        specifically so a get-before-create/conflict reconciliation can
        confirm it is reconciling onto the job it actually submitted, not
        a same-named collision — raising a typed configuration error
        instead of silently adopting the wrong job.
        """
        tags = getattr(job, "tags", None) or {}
        actual_execution_id = tags.get("executionId")
        if actual_execution_id != expected_execution_id:
            raise BackendConfigurationError(
                f"Azure Machine Learning job {job.name!r} exists but its "
                f"executionId tag ({actual_execution_id!r}) does not "
                f"match the requested executionId "
                f"({expected_execution_id!r}); refusing to reconcile onto "
                "an unrelated job (deterministic job-name collision)"
            )

    def _handle_from_job(
        self, spec: ComputeJobSpec, job, *, attempt: int = 1
    ) -> ComputeJobHandle:
        compute_name = self._compute_for_workload(
            spec.workload, spec.resources.targetOverride
        )
        return ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=ComputeBackend.AZURE_ML,
            selectedBackend=ComputeBackend.AZURE_ML,
            backendProfile="default",
            providerJobId=job.name,
            providerTaskId=None,
            targetId=compute_name,
            outputUri=spec.outputs[0].destinationUri,
            submittedAt=MetadataUtils.get_timestamp(),
            routingReason="adapter-default",
            attempt=attempt,
            providerDetail=ComputeProviderDetail(
                discriminator="azure_ml",
                azureMl=AzureMlProviderDetail(
                    jobName=job.name,
                    workspace=self.aml_config["workspace_name"],
                ),
            ),
        )

    def _build_command_job(self, spec: ComputeJobSpec, job_name: str):
        Input, Output, command = _lazy_import(
            "azure.ai.ml", "Input", "Output", "command"
        )
        AssetTypes, InputOutputModes = _lazy_import(
            "azure.ai.ml.constants", "AssetTypes", "InputOutputModes"
        )
        input_mode_map = {
            InputDeliveryMode.DOWNLOAD: InputOutputModes.DOWNLOAD,
            InputDeliveryMode.MOUNT: InputOutputModes.MOUNT,
            InputDeliveryMode.DIRECT: InputOutputModes.DIRECT,
        }

        compute_name = self._compute_for_workload(
            spec.workload, spec.resources.targetOverride
        )
        environment_reference = self._environment_reference_for(spec)

        inputs = {}
        input_names: List[str] = []
        for index, item in enumerate(spec.inputs):
            name = f"input_{index}"
            input_names.append(name)
            inputs[name] = Input(
                type=(
                    AssetTypes.URI_FOLDER
                    if item.kind == InputKind.FOLDER
                    else AssetTypes.URI_FILE
                ),
                path=item.sourceUri,
                mode=input_mode_map[item.deliveryMode],
            )

        (
            _container_url,
            _container_name,
            prefix,
            _patterns,
        ) = require_single_output_destination(spec.outputs)
        output_mode = (
            InputOutputModes.RW_MOUNT
            if any(
                o.persistenceMode == OutputPersistenceMode.LIVE_MOUNT
                for o in spec.outputs
            )
            else InputOutputModes.UPLOAD
        )
        outputs = {
            _OUTPUT_NAME: Output(
                type=AssetTypes.URI_FOLDER,
                path=(
                    f"azureml://datastores/"
                    f"{self.aml_config['datastore_name']}/paths/{prefix}"
                ),
                mode=output_mode,
            )
        }

        bootstrap_command = _build_bootstrap_command(
            working_directory=spec.container.workingDirectory,
            inputs=spec.inputs,
            input_names=input_names,
            outputs=spec.outputs,
            job_id=job_name,
            task_id=spec.executionId,
            inner_command=spec.command,
        )

        shm_size = (
            f"{spec.resources.sharedMemoryMb}m"
            if spec.resources.sharedMemoryMb
            else None
        )

        return command(
            name=job_name,
            display_name=job_name,
            experiment_name=self._experiment_name_for(spec.workload),
            command=bootstrap_command,
            environment=environment_reference,
            environment_variables=dict(spec.environment),
            compute=compute_name,
            inputs=inputs,
            outputs=outputs,
            instance_count=spec.resources.nodeCount,
            shm_size=shm_size,
            timeout=spec.timeoutSeconds,
            identity=self._identity(),
            tags=_sanitized_tags(spec),
        )

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        job = self._get_job_or_raise(handle)
        raw = (job.status or "").strip().lower()
        state = _AML_STATUS_MAP.get(raw)
        if state is None:
            self.logger.error(
                "Unmapped Azure Machine Learning job status %r for job %s",
                job.status,
                handle.providerJobId,
            )
            raise UnmappedAmlJobStatusError(
                "unmapped Azure Machine Learning job status: "
                f"{job.status!r}"
            )
        return state

    def _get_job_or_raise(self, handle: ComputeJobHandle):
        client = self._get_client()
        JobException, ValidationException = _lazy_ml_exceptions()
        try:
            return client.jobs.get(handle.providerJobId)
        except ResourceNotFoundError as exc:
            raise JobNotFoundError(
                f"Azure Machine Learning job {handle.providerJobId} not "
                "found"
            ) from exc
        except (ValidationException, JobException) as exc:
            raise BackendConfigurationError(
                "Azure Machine Learning rejected the status lookup for "
                f"job {handle.providerJobId}: {_sanitize_error_text(exc)}"
            ) from exc
        except (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            raise BackendUnavailableError(
                "Azure Machine Learning status check failed for "
                f"{handle.providerJobId}: {_sanitize_error_text(exc)}"
            ) from exc

    def read_output(
        self,
        handle: ComputeJobHandle,
        relative_path: str,
        *,
        as_chunks: bool = False,
    ) -> Optional[Union[str, Iterable[bytes]]]:
        validate_relative_path(relative_path, field_name="relative_path")
        durable = self._read_output_from_durable_storage(
            handle, relative_path, as_chunks=as_chunks
        )
        if durable is not None:
            return durable
        return self._read_output_via_sdk_fallback(
            handle, relative_path, as_chunks=as_chunks
        )

    def _read_output_from_durable_storage(
        self, handle: ComputeJobHandle, relative_path: str, *, as_chunks: bool
    ) -> Optional[Union[str, Iterable[bytes]]]:
        """Read ``relative_path`` from the durable HASTE output prefix.

        Tries three strategies in order, bounded throughout to this
        handle's own job prefix (never the whole container — the
        datastore may hold many jobs' outputs):

        1. the exact expected blob path (``<job prefix>/<relative_path>``);
        2. a unique blob ending with ``/<relative_path>`` at any nesting
           depth, mirroring Azure Batch's ``get_file_by_match_from_task``
           nested-match behavior for files a workload wrote a directory
           or two deeper than the caller expected (e.g. under
           ``outputs/`` or ``logs/``);
        3. a unique blob *anywhere* under the job prefix (any nesting
           depth — not just ``relative_path``'s own depth) whose basename
           merely *starts with* ``relative_path``'s basename — matching
           Azure Batch's own substring-based file matching for names a
           workload appends a run-specific suffix to and/or nests inside
           a run-specific subdirectory (e.g. TensorBoard's
           ``logs/model_<id>/version_0/events.out.tfevents.<timestamp>.
           <host>.<pid>.<n>`` against a caller-supplied
           ``events.out.tfevents``).

        Returns ``None`` if no strategy finds anything (not yet
        available — the SDK-download fallback covers the still-running
        case). Any strategy finding more than one candidate raises
        ``AmbiguousOutputMatchError`` rather than arbitrarily picking one
        — multiple matches are never silently resolved.
        """
        container_url, _container_name, prefix = split_destination_uri(
            handle.outputUri
        )
        container_client = ContainerClient.from_container_url(
            container_url, credential=self._credential()
        )

        exact_blob_name = (
            f"{prefix}/{relative_path}" if prefix else relative_path
        )
        result = self._try_read_blob(
            container_client, exact_blob_name, as_chunks=as_chunks
        )
        if result is not _BLOB_NOT_FOUND:
            return result

        try:
            matches = self._find_nested_blob_matches(
                container_client, prefix, relative_path
            )
            if not matches:
                matches = self._find_basename_prefix_blob_matches(
                    container_client, prefix, relative_path
                )
        except (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            self.logger.warning(
                "listing %r under job prefix %r failed (%s); trying the "
                "SDK download fallback",
                relative_path,
                prefix,
                _sanitize_error_text(exc),
            )
            return None

        match = _select_unique_match(
            matches,
            context=f"job prefix {prefix!r}",
            relative_path=relative_path,
        )
        if match is None:
            return None

        result = self._try_read_blob(
            container_client, match, as_chunks=as_chunks
        )
        return None if result is _BLOB_NOT_FOUND else result

    def _try_read_blob(self, container_client, blob_name: str, *, as_chunks):
        """Read one blob, or ``_BLOB_NOT_FOUND``/``None``.

        ``_BLOB_NOT_FOUND`` (not a definitive answer) tells the caller it
        may still try another candidate location; ``None`` means a
        transient read failure — give up on durable storage entirely for
        this call and let the SDK-download fallback take over, same as
        before this method existed.
        """
        try:
            downloader = container_client.get_blob_client(
                blob_name
            ).download_blob()
        except ResourceNotFoundError:
            return _BLOB_NOT_FOUND
        except (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            self.logger.warning(
                "durable blob read failed for %s (%s); trying the SDK "
                "download fallback",
                blob_name,
                _sanitize_error_text(exc),
            )
            return None
        if as_chunks:
            return downloader.chunks()
        return downloader.readall().decode("utf-8")

    def _find_nested_blob_matches(
        self, container_client, prefix: str, relative_path: str
    ) -> List[str]:
        """List blob names under this job's own prefix ending with
        ``/<relative_path>`` — bounded to ``prefix`` (``name_starts_with``)
        so this never scans outside the job's own output prefix into
        another job's (or another project's) data.
        """
        list_prefix = f"{prefix}/" if prefix else ""
        suffix = f"/{relative_path}"
        return [
            blob.name
            for blob in container_client.list_blobs(
                name_starts_with=list_prefix
            )
            if blob.name.endswith(suffix)
        ]

    def _find_basename_prefix_blob_matches(
        self, container_client, prefix: str, relative_path: str
    ) -> List[str]:
        """List blob names *anywhere* under this job's own prefix (any
        nesting depth — deliberately not constrained to ``relative_path``'s
        own depth) whose basename starts with ``relative_path``'s
        basename.

        Covers names a workload appends a run-specific suffix to, and/or
        nests inside a run-specific subdirectory, that neither the exact
        nor the nested-suffix check can match — most notably
        TensorBoard's own layout, where the actual event file lands as
        something like
        ``logs/model_<id>/version_0/events.out.tfevents.<timestamp>.
        <host>.<pid>.<n>`` against a caller-supplied
        ``events.out.tfevents`` (matching Azure Batch's own substring-
        based ``get_file_by_match_from_task``, which likewise does not
        constrain by directory depth). Bounded to ``prefix`` like
        ``_find_nested_blob_matches`` — never scans outside this job's
        own output prefix.
        """
        list_prefix = f"{prefix}/" if prefix else ""
        requested_basename = relative_path.rsplit("/", 1)[-1]

        matches = []
        for blob in container_client.list_blobs(name_starts_with=list_prefix):
            relative_name = blob.name[len(list_prefix) :]
            blob_basename = relative_name.rsplit("/", 1)[-1]
            if blob_basename.startswith(requested_basename):
                matches.append(blob.name)
        return matches

    def _read_output_via_sdk_fallback(
        self, handle: ComputeJobHandle, relative_path: str, *, as_chunks: bool
    ) -> Optional[Union[str, Iterable[bytes]]]:
        client = self._get_client()
        (JobException,) = _lazy_import(
            "azure.ai.ml.exceptions", "JobException"
        )
        tmp_dir = tempfile.mkdtemp(prefix="haste-aml-output-")
        try:
            try:
                client.jobs.download(
                    name=handle.providerJobId,
                    download_path=tmp_dir,
                    output_name=_OUTPUT_NAME,
                )
            except JobException:
                # Documented ``download()`` behavior: raised when the job
                # is not yet in a terminal state — its output is not
                # downloadable yet, a normal/expected condition (not a
                # failure), same as a not-yet-written live progress file.
                self.logger.info(
                    "Azure Machine Learning job %s is not yet in a "
                    "terminal state; output is not downloadable yet",
                    handle.providerJobId,
                )
                return None
            except ResourceNotFoundError as exc:
                raise JobNotFoundError(
                    f"Azure Machine Learning job {handle.providerJobId} "
                    "not found"
                ) from exc
            except (
                HttpResponseError,
                ServiceRequestError,
                ServiceResponseError,
            ) as exc:
                raise OutputNotAvailableError(
                    "Azure Machine Learning output download failed for "
                    f"job {handle.providerJobId}: "
                    f"{_sanitize_error_text(exc)}"
                ) from exc

            # Exact match first, then a basename-prefix match (e.g. a
            # TensorBoard ``events.out.tfevents.<ts>.<host>.<pid>.<n>``
            # file against a caller-supplied ``events.out.tfevents``) —
            # mirroring the durable-storage matching strategy above.
            exact_matches = glob.glob(
                os.path.join(tmp_dir, "**", relative_path), recursive=True
            )
            candidates = exact_matches or glob.glob(
                os.path.join(tmp_dir, "**", relative_path + "*"),
                recursive=True,
            )
            match = _select_unique_match(
                candidates,
                context=(
                    "the downloaded output for job "
                    f"{handle.providerJobId!r}"
                ),
                relative_path=relative_path,
            )
            if match is None:
                return None
            with open(match, "rb") as file_obj:
                data = file_obj.read(_MAX_FALLBACK_READ_BYTES + 1)
            if len(data) > _MAX_FALLBACK_READ_BYTES:
                raise OutputNotAvailableError(
                    f"{relative_path!r} exceeds the bounded fallback read "
                    "size"
                )
            if as_chunks:
                return iter([data])
            return data.decode("utf-8")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def cancel(self, handle: ComputeJobHandle) -> None:
        try:
            state = self.get_status(handle)
        except JobNotFoundError:
            self.logger.info(
                "cancel: Azure Machine Learning job %s not found; "
                "treating cancellation as a no-op",
                handle.providerJobId,
            )
            return
        if state in TERMINAL_JOB_STATES:
            self.logger.info(
                "cancel: Azure Machine Learning job %s is already "
                "terminal (%s); no-op",
                handle.providerJobId,
                state.value,
            )
            return
        client = self._get_client()
        JobException, ValidationException = _lazy_ml_exceptions()
        try:
            poller = client.jobs.begin_cancel(handle.providerJobId)
            poller.wait(timeout=self.aml_config["submission_timeout_seconds"])
        except ResourceNotFoundError:
            # Already gone — idempotent no-op.
            return
        except (ValidationException, JobException) as exc:
            raise JobCancellationError(
                "Azure Machine Learning rejected the cancellation request "
                f"for job {handle.providerJobId}: "
                f"{_sanitize_error_text(exc)}"
            ) from exc
        except HttpResponseError as exc:
            if _is_conflict_error(exc):
                # Completed between our status check and this call.
                return
            raise JobCancellationError(
                "Azure Machine Learning could not cancel job "
                f"{handle.providerJobId}: {_sanitize_error_text(exc)}"
            ) from exc
        except (ServiceRequestError, ServiceResponseError) as exc:
            raise JobCancellationError(
                "Azure Machine Learning could not cancel job "
                f"{handle.providerJobId}: {_sanitize_error_text(exc)}"
            ) from exc

    def finalize(self, handle: ComputeJobHandle) -> None:
        """True idempotent no-op: retains AML job history.

        There is no temporary execution resource this adapter needs to
        release, and no provider cleanup action to take — unlike Batch's
        node-side working directory, AML already owns the job's lifecycle
        and artifacts, and HASTE never deletes or disables AML job history
        (design.md's "AML job record retained" requirement). Deliberately
        makes *no* provider call — a transient failure to look up the
        job's status must never turn this legitimate no-op into a failure
        (design.md's "Finalization is repeated" requirement: idempotent
        under any circumstance, not just the happy path).
        """
        self.logger.info(
            "finalize: no-op for Azure Machine Learning job %s (AML "
            "retains job history/artifacts; nothing to release)",
            handle.providerJobId,
        )

    def get_capacity(
        self, workload: ComputeWorkload, resources: ComputeResources
    ) -> CapacitySnapshot:
        try:
            compute_name = self._compute_for_workload(
                workload, resources.targetOverride
            )
        except BackendConfigurationError as exc:
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.UNAVAILABLE,
                detail=str(exc),
            )

        client = self._get_client()
        try:
            compute = client.compute.get(compute_name)
        except ResourceNotFoundError:
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.UNAVAILABLE,
                detail=f"compute cluster {compute_name!r} not found",
            )
        except (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.UNKNOWN,
                detail=(f"capacity check failed: {_sanitize_error_text(exc)}"),
            )

        provisioning_state = (
            getattr(compute, "provisioning_state", "") or ""
        ).lower()
        if provisioning_state in ("failed", "deleting"):
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.UNAVAILABLE,
                detail=(
                    f"compute cluster {compute_name!r} provisioning_state="
                    f"{provisioning_state!r}"
                ),
            )

        try:
            nodes = list(client.compute.list_nodes(compute_name))
        except (
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            # Node-level detail is best-effort; a scale-to-zero cluster
            # with zero nodes is normal, not an error, so treat any
            # inability to list nodes as "may still queue/scale up" rather
            # than "unavailable" — never pretend to know exact capacity.
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.QUEUEABLE,
                detail=(
                    "node listing unavailable "
                    f"({_sanitize_error_text(exc)}); compute cluster "
                    f"{compute_name!r} may still scale up"
                ),
            )

        idle_count = sum(
            1
            for node in nodes
            if getattr(node, "current_job_name", None) is None
        )
        if idle_count > 0:
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_ML,
                workload=workload,
                state=CapacityState.AVAILABLE,
                detail=(f"{idle_count} idle node(s) on {compute_name!r}"),
            )
        return CapacitySnapshot(
            backend=ComputeBackend.AZURE_ML,
            workload=workload,
            state=CapacityState.QUEUEABLE,
            detail=(
                f"no idle node on {compute_name!r}; cluster may scale up "
                "from zero (min_instances=0)"
            ),
        )


def _sanitized_tags(spec: ComputeJobSpec) -> Dict[str, str]:
    """Sanitize ``spec.tags`` (already credential-checked at construction —
    see ``ComputeTags``) plus ``executionId`` and a spot-allowance
    observability tag, one more time immediately before they leave the
    process as AML job tags (design.md#security: "checked at construction
    and before every log line" — tags shown in the Azure Portal get the
    same treatment).

    ``executionId`` is included specifically so a get-before-create/
    conflict reconciliation can verify it is reconciling onto the job it
    actually submitted rather than a same-named collision (see
    ``AzureMLRunner._verify_reconciled_execution_id``) — ``executionId``
    is a HASTE-internal identifier, not a secret, so tagging it does not
    violate the "no credential/signed-URL in tags" rule.
    """
    raw = spec.tags.model_dump(exclude_none=True)
    tags: Dict[str, str] = {}
    for key, value in raw.items():
        text = value.value if hasattr(value, "value") else str(value)
        assert_no_credential_material(text, field_name=f"tags.{key}")
        tags[key] = text
    tags["executionId"] = spec.executionId
    # AML spot/low-priority allocation is a whole-compute-cluster property
    # (mirrors Azure Batch's pool-level dedicated/low-priority node split),
    # not a per-job knob on an already-provisioned AmlCompute cluster, so
    # ``resources.allowSpot`` cannot change scheduling for a fixed named
    # compute target. Recording the request (rather than silently dropping
    # it) keeps it observable even though this adapter cannot act on it
    # beyond selecting a differently-provisioned compute cluster via
    # ``resources.targetOverride``.
    tags["requestedSpot"] = "true" if spec.resources.allowSpot else "false"
    return tags


def _build_bootstrap_command(
    *,
    working_directory: str,
    inputs: List[ComputeInput],
    input_names: List[str],
    outputs: List[ComputeOutput],
    job_id: str,
    task_id: str,
    inner_command: str,
) -> str:
    """Build the fixed, internal bootstrap command every AML submission
    runs: binds ``HASTE_JOB_WORKDIR`` (plus legacy ``AZ_BATCH_*`` aliases),
    lays out ``outputs`` to reproduce Azure Batch's own upload-flattening
    behavior, stages each input at its requested workspace-relative
    destination, then invokes the trusted ``inner_command`` (design.md#work-
    directory-contract, #aml-submission-mapping).

    ``HASTE_OUTPUT_ROOT`` is always the AML named output's own local
    mount/upload path (``${{outputs.haste_output}}``) — the one durable
    location a submission's output data actually lands at
    (design.md's "one durable HASTE output root via configured datastore
    URI"). ``HASTE_JOB_WORKDIR`` (what the workload actually treats as its
    working directory) is derived from ``outputs`` via
    ``_resolve_output_layout``:

    - a **root** pattern (an output whose ``sourceRelativePattern`` has no
      static leading directory, e.g. ``**/*`` — matching Batch's own
      "upload everything under the task working directory, preserving
      structure" mode) binds ``HASTE_JOB_WORKDIR`` directly to
      ``HASTE_OUTPUT_ROOT``, so training's full checkpoint/TensorBoard/
      log directory structure (and any live-mounted progress files) is
      preserved exactly as written, matching design.md#workload-
      migration-matrix's training requirement;
    - a **static-directory** pattern (e.g. ``outputs/*.tif``,
      ``logs/*.log``, ``inference/**/*``) instead gets a fresh local,
      non-durable ``HASTE_JOB_WORKDIR`` (``mktemp -d``), with each
      pattern's static directory symlinked *directly* to
      ``HASTE_OUTPUT_ROOT`` — reproducing Batch's own upload flattening
      (Batch's ``OutputFile`` uploads a matched file to the destination
      prefix root, not nested under the pattern's own local directory).
      Multiple different static directories may point at (symlink to) the
      same durable root — this is expected, not a conflict, and mirrors
      Batch uploading from several different local subdirectories into
      one shared destination prefix.

    Mixing a root pattern with a static-directory pattern, or two
    static-directory patterns where one is a parent of another, is an
    unsupported/ambiguous shape rejected by ``_resolve_output_layout``
    (surfaced as ``BackendConfigurationError`` by ``validate()`` before
    any provider call).

    Every dynamic value is quoted with ``shlex.quote`` — this never
    concatenates untrusted input into the command string; ``inner_command``
    itself is the processor-generated, already-trusted command HASTE always
    passes here, never anything derived from a request body.

    AML's own ``${{inputs.<name>}}``/``${{outputs.<name>}}`` template
    tokens are emitted as literal text (built via string concatenation, not
    f-string brace interpolation, to avoid ambiguity between Python's and
    AML's own use of ``{{``/``}}``) and resolved by AML itself at runtime,
    not by this function.

    ``inner_command`` is appended after normalizing one matching outer
    quote pair off it (see ``_normalize_quoted_command``): every migrated
    processor emits its whole shell chain pre-wrapped in a single outer
    quote (e.g. ``'cd /app && python x.py'``) for the Batch/local
    adapters, which pass it through a layer that expects that shape. Here
    each bootstrap line — including this one — is executed directly by
    bash, so leaving the wrapper on would make bash treat the entire
    quoted chain as one (non-existent) command name instead of running it
    as a shell chain.

    AML ENTRYPOINT-bypass hardening: AML command jobs may run ``command``
    directly against the image, without invoking the image's own
    ``ENTRYPOINT`` (unlike Batch/local, which run the container's normal
    entrypoint) — any permission/umask setup or exit-code handling an
    image's entrypoint would otherwise have done is not guaranteed to run.
    This script therefore explicitly:

    - sets ``umask 0022`` up front, so every file/directory this script or
      the workload creates is group/other-readable regardless of the
      image's own default umask (least-surprise for anything later
      reading the durable output outside this job's own user context);
    - runs the workload command with ``set +e`` (temporarily suspending
      ``errexit``) and captures its real exit code, specifically so a
      failing workload does not make ``set -e`` abort the script *before*
      the finalization step below runs;
    - redirects the workload's stdout/stderr straight to durable
      ``stdout.txt``/``stderr.txt`` files directly under
      ``HASTE_OUTPUT_ROOT`` (Azure Batch standard-file parity), so a
      failed job's diagnostics are readable through the same bounded
      durable-storage ``read_output`` path as any other output, without
      ever requiring a full SDK output download just to see why a job
      failed. Deliberately plain ``>``/``2>`` redirection, not a
      ``tee``-via-process-substitution "capture and also stream live"
      design — process substitution's background reader is a documented,
      platform-dependent hang risk for anything that waits on this
      script's own stdout/stderr reaching EOF (observed hanging
      indefinitely under Python's ``subprocess.run(capture_output=True)``
      on this project's own Windows/MSYS test environment); a job's
      historical stdout/stderr being written straight to the durable
      output root — not also mirrored live — is what design.md actually
      asks for (a diagnostic durably available afterward), and plain
      redirection can never introduce that hang class;
    - runs a best-effort, non-fatal ``chmod -R o+rX`` over
      ``HASTE_OUTPUT_ROOT`` (never just ``HASTE_JOB_WORKDIR`` — in the
      static-directory layout that is a throwaway local directory, not
      where the durable data lives) after the workload command, on both
      success and failure;
    - re-exits with the workload's original captured exit code — never
      the chmod's — so AML's own success/failure reporting for the job
      reflects the workload, not this script's finalization housekeeping.
      finalization housekeeping.
    """
    output_token = "${{outputs." + _OUTPUT_NAME + "}}"
    is_root, static_dirs = _resolve_output_layout(outputs)

    lines = [
        "set -euo pipefail",
        f"umask {_BOOTSTRAP_UMASK}",
        f'export HASTE_OUTPUT_ROOT="{output_token}"',
    ]
    if is_root:
        lines.append('export HASTE_JOB_WORKDIR="$HASTE_OUTPUT_ROOT"')
    else:
        lines.append('export HASTE_JOB_WORKDIR="$(mktemp -d)"')
    lines.append('mkdir -p "$HASTE_JOB_WORKDIR"')
    lines.append('cd "$HASTE_JOB_WORKDIR"')
    lines.append('export AZ_BATCH_TASK_WORKING_DIR="$HASTE_JOB_WORKDIR"')
    lines.append(f"export AZ_BATCH_JOB_ID={shlex.quote(job_id)}")
    lines.append(f"export AZ_BATCH_TASK_ID={shlex.quote(task_id)}")

    for static_dir in static_dirs:
        quoted_dir = shlex.quote(static_dir)
        lines.append(f'mkdir -p "$(dirname {quoted_dir})"')
        lines.append(f'ln -sfn "$HASTE_OUTPUT_ROOT" {quoted_dir}')

    for name, item in zip(input_names, inputs):
        dest = shlex.quote(item.destinationRelativePath)
        source_token = "${{inputs." + name + "}}"
        lines.append(f'mkdir -p "$(dirname {dest})"')
        lines.append(f'ln -sfn "{source_token}" {dest}')

    normalized_working_directory = (working_directory or ".").strip()
    if normalized_working_directory not in ("", "."):
        quoted_workdir = shlex.quote(normalized_working_directory)
        lines.append(f"mkdir -p {quoted_workdir}")
        lines.append(f"cd {quoted_workdir}")

    # Run the workload with errexit suspended so a non-zero exit does not
    # abort the script before finalization (chmod + faithful re-exit)
    # below runs — see the ENTRYPOINT-bypass note above. Re-enabling
    # `set -e` afterwards is defensive/for readability; nothing after
    # this point can itself fail the job, since `exit` is unconditional
    # and `chmod` is explicitly best-effort. The whole normalized shell
    # chain is wrapped in a `{ ...; }` group so the stdout/stderr
    # redirections below apply to the entire chain, not just its last
    # command. Plain redirection (never `tee`-via-process-substitution —
    # see the docstring above for why) means `$?` is simply and reliably
    # the workload's own exit status, exactly as before this capture was
    # added.
    stdout_path = '"$HASTE_OUTPUT_ROOT/' + _BOOTSTRAP_STDOUT_FILE + '"'
    stderr_path = '"$HASTE_OUTPUT_ROOT/' + _BOOTSTRAP_STDERR_FILE + '"'
    lines.append("set +e")
    lines.append(
        "{ "
        + _normalize_quoted_command(inner_command)
        + "; } "
        + f"> {stdout_path} "
        + f"2> {stderr_path}"
    )
    lines.append(f"{_BOOTSTRAP_EXIT_CODE_VAR}=$?")
    lines.append("set -e")
    lines.append('chmod -R o+rX "$HASTE_OUTPUT_ROOT" || true')
    lines.append(f'exit "${_BOOTSTRAP_EXIT_CODE_VAR}"')
    return "\n".join(lines)


def _normalize_quoted_command(inner_command: str) -> str:
    """Strip one matching outer single/double-quote pair off a workload
    command, if present.

    Every migrated processor's ``build_*_job_spec()`` emits ``command`` as
    its whole shell chain wrapped in a single outer quote — e.g.
    ``'cd /app && python train.py --config config.yaml'`` or
    ``"cd /app && python run_workflow.py ..."`` — a shape the Batch/local
    adapters pass through unchanged to a layer that expects it pre-quoted
    (see ``azure_batch.py``'s own ``_export_haste_job_workdir`` handling
    of "quoted train-style" commands). The AML bootstrap script instead
    runs every line, including this one, directly through bash, so
    leaving that wrapper on would make bash parse the whole quoted chain
    as a single literal token and try to execute a (non-existent) command
    by that name, rather than running it as a shell chain.

    Only ever removes the outermost pair — whatever is inside (further
    quotes, escapes, ``&&`` chains, etc.) is preserved exactly as written,
    so the inner shell chain is unaffected. A mismatched pair (e.g. starts
    with ``"`` but ends with ``'``), a lone leading/trailing quote with no
    matching partner, or no wrapping quote at all are all left completely
    unchanged — those are not this function's problem to fix, and (for a
    genuinely malformed command) fail the same way they would have
    without this normalization.
    """
    if (
        len(inner_command) >= 2
        and inner_command[0] == inner_command[-1]
        and inner_command[0] in ("'", '"')
    ):
        return inner_command[1:-1]
    return inner_command


#: Glob metacharacters that mark a path segment as containing a wildcard,
#: for ``_pattern_static_directory``'s purposes. Deliberately a small,
#: conservative set (``*``/``?``/``[``) matching common shell/glob
#: convention, not a full glob-syntax parser.
_WILDCARD_CHARS = frozenset("*?[")


def _pattern_static_directory(pattern: str) -> str:
    """Return the static (wildcard-free) leading directory portion of an
    output ``sourceRelativePattern``.

    Walks ``pattern``'s ``/``-separated segments (excluding the last,
    which is always either the wildcarded file-match portion or a literal
    filename — never itself part of the "directory to symlink") and
    accumulates segments until one containing a glob metacharacter is
    found. Examples:

    - ``"outputs/*.tif"`` -> ``"outputs"``
    - ``"logs/*.log"`` -> ``"logs"``
    - ``"inference/**/*"`` -> ``"inference"`` (stops at the ``**`` segment)
    - ``"**/*"`` -> ``""`` (a *root* pattern — the very first segment is
      already a wildcard)
    - ``"manifest.json"`` -> ``""`` (a single literal segment: the file
      itself lives directly at the job workspace root)
    - ``"logs/manifest.json"`` -> ``"logs"`` (fully literal, no glob
      metacharacter anywhere, but still nested one directory deep)

    An empty return value is the sentinel ``_resolve_output_layout`` uses
    to identify a *root* pattern (design.md's "for a root pattern like
    ``**/*``, bind HASTE_JOB_WORKDIR to the output root").
    """
    segments = pattern.split("/")
    static_segments: List[str] = []
    for segment in segments[:-1]:
        if any(ch in _WILDCARD_CHARS for ch in segment):
            break
        static_segments.append(segment)
    return "/".join(static_segments)


def _resolve_output_layout(
    outputs: List[ComputeOutput],
) -> Tuple[bool, List[str]]:
    """Classify ``outputs`` into a durable-output-layout mode.

    Returns ``(is_root, static_dirs)``:

    - ``(True, [])`` — every output is a *root* pattern (static directory
      ``""``, e.g. ``**/*``): ``HASTE_JOB_WORKDIR`` binds directly to the
      durable output root, preserving full directory structure (training's
      requirement — checkpoints, TensorBoard events, live progress logs at
      whatever nested paths the workload writes them).
    - ``(False, static_dirs)`` — every output has a non-empty static
      directory (e.g. ``outputs/*.tif``, ``logs/*.log``,
      ``inference/**/*``); ``static_dirs`` is the sorted, de-duplicated
      set of those directories, each of which the bootstrap script
      symlinks directly to the durable output root — reproducing Azure
      Batch's own upload flattening of a wildcarded ``sourceRelativePattern``
      (design.md#aml-submission-mapping).

    Raises:
        ValueError: ``outputs`` mixes a root pattern with a static-
            directory pattern (ambiguous — "preserve everything" and
            "flatten this specific directory" cannot both apply to the
            same submission), or two static directories overlap (one is
            a parent of another, e.g. ``"outputs"`` and
            ``"outputs/nested"`` — symlinking both independently is
            undefined). Two *equal* static directories from different
            outputs are not a conflict — they simply share one symlink.
    """
    static_dirs_seen = set()
    has_root = False
    for output in outputs:
        static_dir = _pattern_static_directory(output.sourceRelativePattern)
        if static_dir == "":
            has_root = True
        else:
            static_dirs_seen.add(static_dir)

    if has_root and static_dirs_seen:
        raise ValueError(
            "cannot mix a root output pattern (e.g. '**/*', matching "
            "from the job workspace root, preserving full structure) "
            "with a static-directory output pattern (e.g. "
            "'outputs/*.tif', flattened onto the durable output root) "
            "in the same submission; conflicting static directories: "
            f"{sorted(static_dirs_seen)!r}"
        )

    if has_root:
        return True, []

    sorted_dirs = sorted(static_dirs_seen)
    for index, outer in enumerate(sorted_dirs):
        for inner in sorted_dirs[index + 1 :]:
            if inner.startswith(outer + "/"):
                raise ValueError(
                    f"overlapping output static directories {outer!r} "
                    f"and {inner!r}: one output pattern's static "
                    "directory must not be a parent of another's"
                )
    return False, sorted_dirs


__all__ = [
    "AmbiguousOutputMatchError",
    "AzureMLRunner",
    "UnmappedAmlJobStatusError",
]
