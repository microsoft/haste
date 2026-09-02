# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import io
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from azure.batch import BatchServiceClient
from azure.batch.batch_auth import SharedKeyCredentials
from azure.batch.models import (
    AllocationState,
    AutoUserScope,
    AutoUserSpecification,
    BatchErrorException,
    CachingType,
    ComputeNodeIdentityReference,
    ComputeNodeState,
    ContainerConfiguration,
    ContainerRegistry,
    ElevationLevel,
    EnvironmentSetting,
    ImageReference,
    JobAddParameter,
    JobPatchParameter,
    JobState,
    OnAllTasksComplete,
    OSDisk,
    OutputFile,
    OutputFileBlobContainerDestination,
    OutputFileDestination,
    OutputFileUploadCondition,
    OutputFileUploadOptions,
    PoolAddParameter,
    PoolInformation,
    PoolResizeParameter,
    ResourceFile,
    TaskAddParameter,
    TaskConstraints,
    TaskContainerSettings,
    TaskState,
    UserIdentity,
    VirtualMachineConfiguration,
)
from azure.core.exceptions import (
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    ContainerSasPermissions,
    generate_container_sas,
)
from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    BackendConfigurationError,
    BackendUnavailableError,
    BatchProviderDetail,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeResources,
    ComputeWorkload,
    JobCancellationError,
    JobNotFoundError,
    OutputNotAvailableError,
    SubmissionIndeterminateError,
    validate_relative_path,
)
from hastegeo.core.utils.batch_config import (
    MAX_JOB_ID_LENGTH,
    BatchConfigurationError,
    resolve_job_id,
    validate_batch_config,
)
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils
from tenacity import (
    RetryError,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import (
    BaseRunner,
    ComputeRunner,
    require_single_output_destination,
    require_supported_uri_schemes,
)
from .base import resource_files_from_inputs as _resource_files_from_inputs
from .base import truncate_deterministic_id

# Batch's ResourceFile.http_url / OutputFileBlobContainerDestination only
# accept a real http(s) blob URL, and split_destination_uri (base.py)
# assumes an https://host/container/prefix shape — so those are the only
# input/output URI schemes this adapter can actually translate. Other
# schemes hastegeo.core.models.compute.ALLOWED_URI_SCHEMES otherwise
# permits (s3, azureml, adl, abfss, wasbs, file) are for backends whose
# translation understands their different shapes; misinterpreting them
# here as Blob-shaped URLs would silently corrupt the container/prefix.
_BATCH_SUPPORTED_URI_SCHEMES = frozenset({"http", "https"})

# Characters processor-generated commands may use to wrap the entire
# command in a single quoted chain (see _export_haste_job_workdir below).
_COMMAND_QUOTE_CHARS = ('"', "'")


def _export_haste_job_workdir(command: str) -> str:
    """Prefix ``command`` with an export of ``HASTE_JOB_WORKDIR`` from the
    legacy ``$AZ_BATCH_TASK_WORKING_DIR`` variable.

    Real processor-generated commands are commonly wrapped in a single
    leading/trailing quote character (e.g.
    ``'"cd /app && python train.py --config c.yaml"'``) so the image
    entrypoint receives the whole ``&&``-chained command as one shell
    string/token. Naively prepending the export *before* that wrapper
    would put it outside the quotes, splitting the command_line into two
    tokens and changing how Batch/Docker parse the argument. When such a
    wrapper is present, the export is inserted just inside the opening
    quote instead, so the export and the original command stay inside
    the same single quoted chain. A double-quote wrapper requires the
    export's own ``$AZ_BATCH_TASK_WORKING_DIR`` reference to use escaped
    inner double quotes so it doesn't prematurely close the wrapper. A
    single-quote wrapper briefly closes around the variable reference so
    the shell expands it, then reopens; adjacent quoted segments still
    form one command token. Unquoted commands are prefixed normally.
    """
    if (
        len(command) >= 2
        and command[0] in _COMMAND_QUOTE_CHARS
        and command[-1] == command[0]
    ):
        quote = command[0]
        inner = command[1:-1]
        if quote == '"':
            export_stmt = (
                'export HASTE_JOB_WORKDIR=\\"$AZ_BATCH_TASK_WORKING_DIR\\" '
                "&& "
            )
            return f"{quote}{export_stmt}{inner}{quote}"
        return (
            "'export HASTE_JOB_WORKDIR='"
            '"$AZ_BATCH_TASK_WORKING_DIR"'
            f"' && {inner}'"
        )
    return (
        'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && ' + command
    )


# Node-scoped Batch file APIs (list/get/delete_from_task) are answered by the
# compute node that ran the task, so they fail once that node goes away. On
# autoscale pools with `$NodeDeallocationOption = taskcompletion` (and on
# low-priority/spot nodes that get preempted) the node is torn down at exactly
# the moment the caller reads the task's outputs back.
#
# NodeNotReady is a 409, not a 5xx, so the server-error retry never covered it.
# A node that is starting/rebooting recovers, so those codes are retried; a node
# that is gone never will, so those are surfaced as a non-fatal "unavailable".
TRANSIENT_NODE_ERROR_CODES = frozenset({"NodeNotReady", "NodeStateInvalid"})
TERMINAL_NODE_ERROR_CODES = frozenset({"NodeNotFound"})


class AzureBatchRunner(BaseRunner, ComputeRunner):
    def __init__(
        self, config: Config = None, pool_id=None, candidate_pool_ids=None
    ):
        super().__init__(config)
        config = config or Config()
        self.batch_config = config.get_azure_batch_config()
        # Ordered candidate pools for capacity-aware routing (v2.1.0): the runner
        # binds the actual pool at submit time (see add_task). Falls back to the
        # single pool_id (or the training pool) for backward compatibility.
        self.pool_id = pool_id or self.batch_config["training_pool_id"]
        self.candidate_pool_ids = candidate_pool_ids or [self.pool_id]
        self.manage_pools = self.batch_config.get("manage_pools", True)
        self.batch_cluster = AzureBatchJob(
            account_name=self.batch_config["account_name"],
            account_key=self.batch_config["account_key"],
            batch_url=self.batch_config["batch_url"],
            pool_id=self.pool_id,
            user_assigned_identity_resource_id=self.batch_config[
                "user_assigned_identity_resource_id"
            ],
            use_sas=self.batch_config.get("use_sas", False),
            manage_pools=self.manage_pools,
        )
        self.logger = Logger.get_logger(__name__)

    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        try:
            full_file_name = self.batch_cluster.get_file_by_match_from_task(
                job_id, task_id, filename
            )
            if full_file_name is None:
                return None
            output = self.batch_cluster.get_file_from_task(
                job_id, task_id, full_file_name
            )
        except (BatchErrorException, RetryError) as e:
            # The node that ran the task is gone (deallocated, preempted or
            # rebooting), so its copy of the file is unreachable. Report it as
            # a missing file rather than a failure: the task's outputs were
            # already uploaded to blob on completion, so callers can recover
            # from there.
            cause = unwrap_retry_error(e)
            if not is_node_unavailable_error(cause):
                raise
            self.logger.warning(
                "Node serving task %s (job %s) is unavailable (%s); "
                "cannot read %s from the node.",
                task_id,
                job_id,
                batch_error_code(cause),
                filename,
            )
            return None
        if output is None:
            return None
        if as_chunk:
            return output
        content = io.StringIO()
        for chunk in output:
            content.write(chunk.decode("utf-8"))
        content = content.getvalue()
        return content

    def get_task_status(self, job_id, task_id):
        if self.batch_cluster.is_task_succeeded(job_id, task_id):
            return self.config.get_status_types().COMPLETED.value
        elif self.batch_cluster.is_task_failed(job_id, task_id):
            return self.config.get_status_types().FAILED.value
        else:
            # Task state is `preparing` or `running`
            return self.config.get_status_types().IN_PROGRESS.value

    def add_task(
        self,
        job_id=None,
        task_id=None,
        image_name=None,
        command=None,
        arguments=None,
        work_dir=None,
        output_container_url=None,
        output_prefix=None,
        resource_files_for_upload=None,
        file_pattern=None,
        env_vars=None,
    ):
        if image_name is None:
            image_name = self.batch_config["docker_image"]
        if command is None:
            command = self.batch_config["command"]
        if arguments is None:
            arguments = self.batch_config["arguments"]
        if output_container_url is None:
            output_container_url = self.batch_config["output_container_url"]
        if work_dir is None:
            work_dir = self.batch_config["docker_container_work_dir"]
        # NOTE: test workdir option to eliminate the cd into /app here
        command = command

        # Validate before the first Batch call so a missing application
        # setting is reported as itself, rather than as an opaque Azure error
        # raised from deep inside pool creation.
        validate_batch_config(self.batch_config, self.manage_pools)

        # Capacity-aware routing (v2.1.0): pick the pool at submit time from the
        # ordered candidates (preference-first, spillover-second), then bind the
        # job to it.
        selected_pool = self.batch_cluster.select_pool(self.candidate_pool_ids)
        self.batch_cluster.pool_id = selected_pool
        self.logger.info(
            "Selected pool %s for job_id: %s task_id: %s",
            selected_pool,
            job_id,
            task_id,
        )

        # A Batch job is pinned to one pool, so the job id has to follow the
        # pool this task was routed to; otherwise a second task that spills over
        # to another pool collides with the job the first one created.
        job_id = resolve_job_id(job_id, selected_pool, self.candidate_pool_ids)

        # Pre-created IaC/autoscale pools manage their own lifecycle; only
        # auto-create/resize for legacy single-pool envs (manage_pools=True).
        if self.manage_pools:
            self.logger.info(
                "Creating pool for job_id: %s and task_id: %s", job_id, task_id
            )
            # Both workload images must be whitelisted on the pool, matching
            # infra/modules/batchPool.bicep; a pool created with only the
            # training image cannot start imageryprep tasks.
            registry_images = []
            for candidate in (
                self.batch_config["registry_image"],
                self.batch_config["imageprep_docker_image"],
            ):
                if candidate and candidate not in registry_images:
                    registry_images.append(candidate)
            self.batch_cluster.create_pool_if_not_exists(
                self.batch_config["vm_size"],
                self.batch_config["vm_publisher"],
                self.batch_config["vm_offer"],
                self.batch_config["vm_sku"],
                self.batch_config["vm_version"],
                self.batch_config["target_dedicated_nodes"],
                self.batch_config["target_low_priority_nodes"],
                self.batch_config["registry_server"],
                registry_images,
                self.batch_config["node_agent_sku_id"],
            )
        self.logger.info(
            "Creating job for job_id: %s and task_id: %s", job_id, task_id
        )
        job_id = self.batch_cluster.create_job(job_id)

        self.batch_cluster.add_task(
            job_id=job_id,
            task_id=task_id,
            image_name=image_name,
            command=command,
            arguments=arguments,
            work_dir=work_dir,
            output_container_url=output_container_url,
            output_prefix=output_prefix,
            resource_files_for_upload=resource_files_for_upload,
            file_pattern=file_pattern,
            env_vars=env_vars,
            retention_time=self.batch_config["task_retention_time"],
        )
        return job_id, task_id

    def cleanup_task(self, job_id, task_id):
        try:
            self.batch_cluster.delete_files_from_task(job_id, task_id)
        except (BatchErrorException, RetryError) as e:
            # Deleting the working directory of a node that no longer exists is
            # already a no-op, and the task's `retention_time` reclaims the disk
            # anyway — never fail the workload over it.
            cause = unwrap_retry_error(e)
            if not is_node_unavailable_error(cause):
                raise
            self.logger.warning(
                "Node serving task %s (job %s) is unavailable (%s); "
                "skipping working-directory cleanup.",
                task_id,
                job_id,
                batch_error_code(cause),
            )
        self.batch_cluster.disable_job(job_id)

    def cancel_task(self, job_id, task_id):
        return self.batch_cluster.cancel_task(job_id, task_id)

    # ---------------------------------------------------------------
    # ComputeRunner contract
    #
    # Translates ComputeJobSpec into calls on the legacy add_task/
    # get_task_status/get_filecontent_from_task/cancel_task methods above,
    # so multi-pool routing, per-job SAS, and node-loss handling are
    # reused unchanged rather than duplicated (design.md#backend-neutral-
    # compute-runner, ADR-0005).
    # ---------------------------------------------------------------

    def validate(self, spec: ComputeJobSpec) -> None:
        try:
            validate_batch_config(self.batch_config, self.manage_pools)
        except BatchConfigurationError as exc:
            raise BackendConfigurationError(str(exc)) from exc
        if not spec.outputs:
            raise BackendConfigurationError(
                "Azure Batch requires at least one output so the task's "
                "artifacts land at a known blob prefix"
            )
        try:
            require_supported_uri_schemes(
                inputs=spec.inputs,
                outputs=spec.outputs,
                allowed_schemes=_BATCH_SUPPORTED_URI_SCHEMES,
                backend_name="Azure Batch",
            )
            require_single_output_destination(spec.outputs)
            _resource_files_from_inputs(spec.inputs)
        except ValueError as exc:
            raise BackendConfigurationError(str(exc)) from exc

    def _execution_job_id(self, execution_id: str) -> str:
        """Deterministic, per-execution Batch job id.

        The same ``executionId`` always maps to the same job id
        regardless of which pool ends up being selected on a given
        attempt — this is what fixes the cross-pool duplicate-task bug: a
        pool-*scoped* job id (the legacy ``resolve_job_id`` convention,
        still used by ``add_task``/``create_job`` above) changes if a
        retry's live capacity selection picks a different candidate pool,
        so a retry can silently create a second, duplicate task with the
        same executionId in a different job/pool. Bounded/hash-safe via
        ``truncate_deterministic_id`` since ``MAX_JOB_ID_LENGTH`` is 64
        and ``executionId`` has no length limit of its own.
        """
        return truncate_deterministic_id(
            f"haste-{execution_id}", max_length=MAX_JOB_ID_LENGTH
        )

    def submit(self, spec: ComputeJobSpec) -> ComputeJobHandle:
        self.validate(spec)
        task_id = spec.executionId
        job_id = self._execution_job_id(spec.executionId)
        resource_files = _resource_files_from_inputs(spec.inputs)
        (
            output_container_url,
            _container_name,
            output_prefix,
            patterns,
        ) = require_single_output_destination(spec.outputs)
        file_patterns = [
            f"$AZ_BATCH_TASK_WORKING_DIR/{pattern}" for pattern in patterns
        ]
        # HASTE_JOB_WORKDIR is the application-owned workspace variable
        # processor-generated commands are moving to (design.md#work-
        # directory-contract); Batch only knows the real working
        # directory at container start time (via the node-agent-set
        # $AZ_BATCH_TASK_WORKING_DIR), so it can't be passed as a static
        # env_vars entry — export it from that legacy variable before the
        # workload command runs instead. Legacy $AZ_BATCH_* variables are
        # left exactly as Batch sets them.
        command = _export_haste_job_workdir(spec.command)

        # Read-first reconciliation: check whether this execution already
        # has a job *before* touching pool selection/creation at all. A
        # retry/duplicate delivery whose job already exists must never
        # re-run select_pool()/create_pool_if_not_exists() — a freshly
        # (re)selected pool could have been deleted or become unavailable
        # since the original submission, and Batch's own job.add() can
        # reject the add for an invalid pool before it even has a chance
        # to return JobExists, breaking reconciliation; manage_pools
        # could also needlessly create/resize a pool this execution
        # doesn't need. See get_execution_job_pool's docstring.
        try:
            actual_pool = self.batch_cluster.get_execution_job_pool(job_id)
        except RetryError as exc:
            cause = unwrap_retry_error(exc)
            raise SubmissionIndeterminateError(
                "Azure Batch job lookup outcome is indeterminate for "
                f"executionId={spec.executionId}: "
                f"{batch_error_code(cause)}"
            ) from exc
        except BatchErrorException as exc:
            raise BackendConfigurationError(
                "Azure Batch rejected job lookup " f"({batch_error_code(exc)})"
            ) from exc

        if actual_pool is None:
            # First submission for this executionId (or a genuine
            # concurrent creation race where every racer's read-first
            # lookup above found nothing) — capacity-aware pool selection
            # (v2.1.0) and pool creation only matter for whichever
            # attempt actually creates the job; only the attempt whose
            # job.add() call is accepted by Batch determines this
            # execution's pool — see get_or_create_job_for_execution's
            # first-writer-wins contract for why a *different* selection
            # by a losing racer must not matter.
            preferred_pool = self.batch_cluster.select_pool(
                self.candidate_pool_ids
            )
            if self.manage_pools:
                self.batch_cluster.pool_id = preferred_pool
                self.logger.info(
                    "Creating pool for executionId: %s", spec.executionId
                )
                # Both workload images must be whitelisted on the pool,
                # matching infra/modules/batchPool.bicep.
                registry_images = []
                for candidate in (
                    self.batch_config["registry_image"],
                    self.batch_config["imageprep_docker_image"],
                ):
                    if candidate and candidate not in registry_images:
                        registry_images.append(candidate)
                self.batch_cluster.create_pool_if_not_exists(
                    self.batch_config["vm_size"],
                    self.batch_config["vm_publisher"],
                    self.batch_config["vm_offer"],
                    self.batch_config["vm_sku"],
                    self.batch_config["vm_version"],
                    self.batch_config["target_dedicated_nodes"],
                    self.batch_config["target_low_priority_nodes"],
                    self.batch_config["registry_server"],
                    registry_images,
                    self.batch_config["node_agent_sku_id"],
                )

            try:
                (
                    actual_pool,
                    we_created_job,
                ) = self.batch_cluster.get_or_create_job_for_execution(
                    job_id, preferred_pool
                )
            except RetryError as exc:
                cause = unwrap_retry_error(exc)
                raise SubmissionIndeterminateError(
                    "Azure Batch job creation outcome is indeterminate "
                    f"for executionId={spec.executionId}: "
                    f"{batch_error_code(cause)}"
                ) from exc
            except BatchErrorException as exc:
                raise BackendConfigurationError(
                    "Azure Batch rejected job creation "
                    f"({batch_error_code(exc)})"
                ) from exc
        else:
            # The job already existed before this attempt (read-first
            # reconciliation above) — it isn't ours to clean up if task
            # submission fails below.
            we_created_job = False
        self.batch_cluster.pool_id = actual_pool

        try:
            self.batch_cluster.add_task(
                job_id=job_id,
                task_id=task_id,
                image_name=spec.container.imageReference,
                command=command,
                arguments=None,
                work_dir=spec.container.workingDirectory,
                output_container_url=output_container_url,
                output_prefix=output_prefix,
                resource_files_for_upload=resource_files or None,
                file_pattern=file_patterns,
                env_vars=dict(spec.environment) or None,
                retention_time=self.batch_config["task_retention_time"],
            )
        except BatchErrorException as exc:
            if batch_error_code(exc) == "TaskExists":
                # Idempotent get-or-create: this executionId was already
                # submitted (retry / duplicate queue delivery / two
                # workers racing). job_id/actual_pool above are already
                # reconciled to the execution's real job — just reuse the
                # existing task instead of creating a second one.
                self.logger.info(
                    "Task %s already exists in job %s; reconciling "
                    "instead of resubmitting.",
                    task_id,
                    job_id,
                )
            else:
                if we_created_job:
                    # This attempt just created a job that now has no
                    # task in it (add_task failed deterministically, not
                    # via a race) — clean it up best-effort so it doesn't
                    # sit there consuming active-job quota until manual
                    # intervention. Never let a cleanup failure mask the
                    # original submission error; a job we didn't create
                    # (we_created_job=False) is never touched here, since
                    # it may belong to another in-flight attempt/worker.
                    try:
                        self.batch_cluster.terminate_job(job_id)
                    except Exception:
                        self.logger.warning(
                            "Failed to clean up empty job %s after "
                            "deterministic task submission failure for "
                            "executionId=%s.",
                            job_id,
                            spec.executionId,
                            exc_info=True,
                        )
                raise BackendConfigurationError(
                    "Azure Batch rejected task submission "
                    f"({batch_error_code(exc)})"
                ) from exc
        except RetryError as exc:
            # Indeterminate outcome: the task may or may not actually
            # exist server-side despite the client-visible failure, so
            # the job must never be terminated here even if we created
            # it — doing so on a false negative would destroy a task
            # that actually did get created.
            cause = unwrap_retry_error(exc)
            raise SubmissionIndeterminateError(
                "Azure Batch submission outcome is indeterminate for "
                f"executionId={spec.executionId}: "
                f"{batch_error_code(cause)}"
            ) from exc

        try:
            self.batch_cluster.arm_job_auto_terminate(job_id)
        except (
            RetryError,
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        ) as exc:
            # The task is already accepted. Returning its handle is required
            # so polling and finalize() can terminate the job later.
            self.logger.warning(
                "Could not arm automatic termination for Batch job %s "
                "after task acceptance (%s); finalize will retry cleanup.",
                job_id,
                type(exc).__name__,
            )

        return ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=ComputeBackend.AZURE_BATCH,
            selectedBackend=ComputeBackend.AZURE_BATCH,
            backendProfile="default",
            providerJobId=job_id,
            providerTaskId=task_id,
            targetId=actual_pool,
            outputUri=spec.outputs[0].destinationUri,
            submittedAt=MetadataUtils.get_timestamp(),
            routingReason="adapter-default",
            attempt=1,
            providerDetail=ComputeProviderDetail(
                discriminator="batch",
                batch=BatchProviderDetail(jobId=job_id, taskId=task_id),
            ),
        )

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        try:
            status = self.get_task_status(
                handle.providerJobId, handle.providerTaskId
            )
        except BatchErrorException as exc:
            if batch_error_code(exc) == "TaskNotFound":
                raise JobNotFoundError(
                    f"Azure Batch task {handle.providerTaskId} not found "
                    f"in job {handle.providerJobId}"
                ) from exc
            raise BackendUnavailableError(
                f"Azure Batch status check failed: {batch_error_code(exc)}"
            ) from exc
        status_types = self.config.get_status_types()
        if status == status_types.COMPLETED.value:
            return ComputeJobState.SUCCEEDED
        if status == status_types.FAILED.value:
            return ComputeJobState.FAILED
        if status == status_types.IN_PROGRESS.value:
            return ComputeJobState.RUNNING
        # Log the raw provider status server-side before failing
        # explicitly, matching the AML adapter's unmapped-status
        # diagnostics (design.md's "Unknown provider status" edge case) —
        # never silently report an unrecognized status as "running".
        self.logger.error(
            "Unmapped Azure Batch status %r for task %s (job %s)",
            status,
            handle.providerTaskId,
            handle.providerJobId,
        )
        raise BackendUnavailableError(
            f"unmapped Azure Batch status: {status!r}"
        )

    def read_output(
        self,
        handle: ComputeJobHandle,
        relative_path: str,
        *,
        as_chunks: bool = False,
    ):
        validate_relative_path(relative_path, field_name="relative_path")
        try:
            return self.get_filecontent_from_task(
                handle.providerJobId,
                handle.providerTaskId,
                relative_path,
                as_chunk=as_chunks,
            )
        except BatchErrorException as exc:
            code = batch_error_code(exc)
            if code in ("TaskNotFound", "JobNotFound"):
                raise JobNotFoundError(
                    "Azure Batch job/task not found for "
                    f"{handle.providerJobId}/{handle.providerTaskId}"
                ) from exc
            raise OutputNotAvailableError(
                f"Azure Batch could not read {relative_path!r}: {code}"
            ) from exc

    def cancel(self, handle: ComputeJobHandle) -> None:
        try:
            self.cancel_task(handle.providerJobId, handle.providerTaskId)
        except BatchErrorException as exc:
            raise JobCancellationError(
                f"Azure Batch could not cancel task "
                f"{handle.providerTaskId}: {batch_error_code(exc)}"
            ) from exc

    def finalize(self, handle: ComputeJobHandle) -> None:
        """Clean up this task's node-side files, then release the Batch
        job.

        Per-execution jobs (deterministic ``haste-{executionId}`` job
        id, one task each — see ``_execution_job_id``/
        ``get_or_create_job_for_execution``) are idempotently
        *terminated* rather than merely disabled: Batch already
        auto-terminates them via ``on_all_tasks_complete=terminate_job``
        once their single task completes, but this is the explicit
        backstop that guarantees the job (and its active-job quota slot)
        is released even if that hasn't happened yet (e.g. a cancelled
        task, or finalize racing ahead of Batch's own auto-terminate).
        Legacy shared pool-scoped jobs (multiple tasks/executions per
        job, from before this per-execution design) keep the original
        disable-only-if-no-other-active-task behavior, since terminating
        one would kill every other task still running in it.

        Idempotent either way: a second call finds nothing left to
        delete (tolerated below), and ``terminate_job``/``disable_job``/
        the active-task check are themselves safe to repeat.
        """
        try:
            self.batch_cluster.delete_files_from_task(
                handle.providerJobId, handle.providerTaskId
            )
        except (BatchErrorException, RetryError) as exc:
            cause = unwrap_retry_error(exc)
            code = batch_error_code(cause)
            if code in ("FileNotFound", "PathNotFound"):
                self.logger.debug(
                    "No files to clean up for task %s (job %s); already "
                    "removed.",
                    handle.providerTaskId,
                    handle.providerJobId,
                )
            elif is_node_unavailable_error(cause):
                self.logger.warning(
                    "Node serving task %s (job %s) is unavailable (%s); "
                    "skipping working-directory cleanup.",
                    handle.providerTaskId,
                    handle.providerJobId,
                    code,
                )
            else:
                raise

        if handle.providerJobId == self._execution_job_id(handle.executionId):
            self.batch_cluster.terminate_job(handle.providerJobId)
            return

        if self._job_has_other_active_tasks(
            handle.providerJobId, exclude_task_id=handle.providerTaskId
        ):
            self.logger.info(
                "Job %s still has other active tasks; leaving it enabled "
                "instead of disabling it for task %s.",
                handle.providerJobId,
                handle.providerTaskId,
            )
            return
        self.batch_cluster.disable_job(handle.providerJobId)

    def _job_has_other_active_tasks(self, job_id, *, exclude_task_id):
        try:
            tasks = self.batch_cluster.list_tasks(job_id)
        except BatchErrorException as exc:
            if batch_error_code(exc) == "JobNotFound":
                return False
            raise
        return any(
            task.id != exclude_task_id and task.state != TaskState.completed
            for task in tasks
        )

    def get_capacity(
        self, workload: ComputeWorkload, resources: ComputeResources
    ) -> CapacitySnapshot:
        try:
            for pool_id in self.candidate_pool_ids:
                if self.batch_cluster._pool_has_idle_node(pool_id):
                    return CapacitySnapshot(
                        backend=ComputeBackend.AZURE_BATCH,
                        workload=workload,
                        state=CapacityState.AVAILABLE,
                        detail=f"pool {pool_id} has an idle node",
                    )
        except BatchErrorException as exc:
            return CapacitySnapshot(
                backend=ComputeBackend.AZURE_BATCH,
                workload=workload,
                state=CapacityState.UNKNOWN,
                detail=f"capacity check failed: {batch_error_code(exc)}",
            )
        return CapacitySnapshot(
            backend=ComputeBackend.AZURE_BATCH,
            workload=workload,
            state=CapacityState.QUEUEABLE,
            detail=(
                "no candidate pool has an idle node; task will queue/"
                "scale up"
            ),
        )


def is_server_error(exception):
    if isinstance(exception, BatchErrorException):
        # Check if the status code is in the 5xx range
        status_code = exception.response.status_code
        return 500 <= status_code < 600
    return False


def batch_error_code(exception):
    """Return the Batch error code of ``exception``, or None."""
    if not isinstance(exception, BatchErrorException):
        return None
    return getattr(getattr(exception, "error", None), "code", None)


def is_transient_node_error(exception):
    """True when the node may still recover and serve the request.

    The node-scoped file APIs are answered by the compute node itself, so a
    node that is starting, rebooting or otherwise mid-transition rejects them
    with a 409 rather than a 5xx. Those are worth another attempt.
    """
    return batch_error_code(exception) in TRANSIENT_NODE_ERROR_CODES


def is_terminal_node_error(exception):
    """True when the node is gone for good and retrying cannot help."""
    return batch_error_code(exception) in TERMINAL_NODE_ERROR_CODES


def is_node_unavailable_error(exception):
    """True for any node-loss error, transient or terminal."""
    return is_transient_node_error(exception) or is_terminal_node_error(
        exception
    )


def unwrap_retry_error(exception):
    """Return the exception tenacity was retrying, or ``exception`` itself.

    ``retry_on_server_error`` leaves ``reraise`` at its default, so an exhausted
    budget surfaces as ``RetryError``. Unwrapping it at the runner boundary lets
    callers classify the underlying Batch error without making an exhausted
    error look retryable to an *outer* wrapper — ``apply_retry_to_methods``
    decorates every ``AzureBatchJob`` method, and several of them call one
    another, so a re-raised retryable error would multiply the budget (five
    outer attempts each spending a five-attempt inner budget).
    """
    if isinstance(exception, RetryError):
        last_attempt = exception.last_attempt
        if last_attempt is not None and last_attempt.failed:
            return last_attempt.exception()
    return exception


def is_retryable_batch_error(exception):
    return is_server_error(exception) or is_transient_node_error(exception)


def retry_on_server_error():
    return retry(
        retry=retry_if_exception(is_retryable_batch_error),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        stop=stop_after_attempt(5),
    )


def apply_retry_to_methods(cls):
    for attr_name, attr_value in cls.__dict__.items():
        if callable(attr_value) and not attr_name.startswith("__"):
            setattr(cls, attr_name, retry_on_server_error()(attr_value))
    return cls


@apply_retry_to_methods
class AzureBatchJob:
    def __init__(
        self,
        account_name: str,
        account_key: str,
        batch_url: str,
        pool_id: str,
        user_assigned_identity_resource_id: str,
        use_sas: bool = False,
        manage_pools: bool = True,
    ):
        self.logger = Logger.get_logger(__name__)
        if account_name and account_key:
            self.credentials = SharedKeyCredentials(account_name, account_key)
        else:
            self.credentials = DefaultAzureCredential()
        self.batch_client = BatchServiceClient(
            self.credentials, batch_url=batch_url
        )
        self.pool_id = pool_id
        self.user_assigned_identity = user_assigned_identity_resource_id
        # v2.1.0: per-job user-delegation SAS for blob I/O on multi-tenant shared
        # pools (instead of the pool's managed identity); and whether the runner
        # manages (creates/resizes) its own pool.
        self.use_sas = use_sas
        self.manage_pools = manage_pools
        self._sas_credential = None
        # Cache user-delegation keys per storage account (valid for hours).
        self._udk_cache = {}

    def select_pool(self, candidate_pool_ids):
        # Capacity-aware routing (v2.1.0): return the first candidate with an
        # idle node (spillover to a free tier). If none has an idle node, return
        # the preferred (first) candidate and let it scale up / queue. A single
        # candidate is returned as-is (no API calls).
        if not candidate_pool_ids:
            return self.pool_id
        if len(candidate_pool_ids) == 1:
            return candidate_pool_ids[0]
        for pid in candidate_pool_ids:
            try:
                if self._pool_has_idle_node(pid):
                    return pid
            except BatchErrorException as e:
                self.logger.warning(
                    "Capacity check failed for pool %s (%s); trying next.",
                    pid,
                    getattr(e.error, "code", e),
                )
        return candidate_pool_ids[0]

    def _pool_has_idle_node(self, pool_id):
        pool = self.batch_client.pool.get(pool_id)
        if (pool.current_dedicated_nodes or 0) + (
            pool.current_low_priority_nodes or 0
        ) == 0:
            return False
        nodes = self.batch_client.compute_node.list(pool_id)
        return any(n.state == ComputeNodeState.idle for n in nodes)

    def _sas_url(self, url, permissions):
        # Append a user-delegation SAS scoped to the URL's container so a Batch
        # ResourceFile/OutputFile can read/write WITHOUT the pool holding any
        # standing data access — the isolation boundary for multi-tenant shared
        # pools. The submitting identity needs `Storage Blob Delegator` on the
        # account. User-delegation keys are cached per account.
        parsed = urlparse(url)
        account_url = f"{parsed.scheme}://{parsed.netloc}"
        account_name = parsed.netloc.split(".")[0]
        container = parsed.path.lstrip("/").split("/", 1)[0]
        if self._sas_credential is None:
            self._sas_credential = DefaultAzureCredential()
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=5)
        entry = self._udk_cache.get(account_url)
        if entry is None or entry[1] <= now + timedelta(hours=1):
            expiry = now + timedelta(hours=24)
            bsc = BlobServiceClient(
                account_url, credential=self._sas_credential
            )
            udk = bsc.get_user_delegation_key(start, expiry)
            entry = (udk, expiry)
            self._udk_cache[account_url] = entry
        udk, expiry = entry
        sas = generate_container_sas(
            account_name=account_name,
            container_name=container,
            user_delegation_key=udk,
            permission=ContainerSasPermissions.from_string(permissions),
            expiry=expiry,
            start=start,
        )
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{sas}"

    def _maybe_sas(self, url, permissions):
        # SAS-augment the URL when per-job SAS is enabled; else return as-is
        # (paired with identity_reference from _blob_identity()).
        if url and self.use_sas:
            return self._sas_url(url, permissions)
        return url

    def _blob_identity(self):
        # No pool identity on the blob transfer when using SAS (the SAS IS the
        # credential); otherwise the pool's user-assigned identity.
        if self.use_sas:
            return None
        return ComputeNodeIdentityReference(
            resource_id=self.user_assigned_identity
        )

    def create_pool_if_not_exists(
        self,
        vm_size: str,
        vm_publisher: str,
        vm_offer: str,
        vm_sku: str,
        vm_version: str,
        target_dedicated_nodes: int,
        target_low_priority_nodes: int,
        registry_server: str,
        registry_images: list,
        node_agent_sku_id: str,
        storage_account_name: str = None,
    ):
        # NOTE: Managed Identity for Pool not supported on python sdk, ARM logic with azure.mgmt.batch is needed.

        try:
            pool = self.batch_client.pool.get(self.pool_id)
            self.logger.info(f"Pool {self.pool_id} already exists.")
            if (
                pool.current_dedicated_nodes == 0
                and pool.current_low_priority_nodes == 0
            ):
                self.logger.info(
                    f"Pool {self.pool_id} has no nodes. Resizing..."
                )
                resize_parameters = PoolResizeParameter(
                    target_dedicated_nodes=target_dedicated_nodes,
                    target_low_priority_nodes=target_low_priority_nodes,
                )
                self.batch_client.pool.resize(
                    pool_id=self.pool_id,
                    pool_resize_parameter=resize_parameters,
                )
                self.logger.info(
                    f"Waiting for pool {self.pool_id} to be resized..."
                )
                self.wait_for_pool_to_be_ready()
                self.logger.info(f"Pool {self.pool_id} resized.")
        except BatchErrorException as e:
            if e.error.code == "PoolNotFound":
                self.logger.info(f"Creating pool {self.pool_id}...")

                image_ref_to_use = ImageReference(
                    publisher=vm_publisher,
                    offer=vm_offer,
                    sku=vm_sku,
                    version=vm_version,
                )

                container_registry = ContainerRegistry(
                    registry_server=registry_server,
                    identity_reference=ComputeNodeIdentityReference(
                        resource_id=self.user_assigned_identity
                    ),
                )

                container_conf = ContainerConfiguration(
                    container_image_names=registry_images,
                    container_registries=[container_registry],
                    type="dockerCompatible",
                )

                new_pool = PoolAddParameter(
                    id=self.pool_id,
                    virtual_machine_configuration=VirtualMachineConfiguration(
                        image_reference=image_ref_to_use,
                        container_configuration=container_conf,
                        node_agent_sku_id=node_agent_sku_id,
                        os_disk=OSDisk(
                            caching=CachingType.read_write, disk_size_gb=1023
                        ),
                    ),
                    vm_size=vm_size,
                    target_dedicated_nodes=target_dedicated_nodes,
                    target_low_priority_nodes=target_low_priority_nodes,
                )

                if storage_account_name:
                    new_pool.mount_configuration = [
                        {
                            "azureBlobFileSystemConfiguration": {
                                "accountName": storage_account_name,
                                "containerName": "models",
                                "relativeMountPath": "/mnt",
                                "identityReference": ComputeNodeIdentityReference(
                                    resource_id=self.user_assigned_identity
                                ),
                            }
                        }
                    ]
                self.batch_client.pool.add(new_pool)
            else:
                raise

    def create_job(self, job_id):
        """Ensure an active job bound to ``self.pool_id``.

        Returns the job id that was actually used, which may differ from the
        requested one when an existing job is pinned to another pool and cannot
        be re-pointed.
        """
        # Fixed pools we manage need a ready node before the job is created;
        # autoscale / pre-created pools scale up in response to queued tasks, so
        # waiting here would deadlock (0 nodes until tasks exist).
        if self.manage_pools:
            self.wait_for_pool_to_be_ready()
        try:
            job = self.batch_client.job.get(job_id)
        except BatchErrorException as e:
            if e.error.code == "JobNotFound":
                self._add_job(job_id)
                return job_id
            raise

        bound_pool = getattr(job.pool_info, "pool_id", None)
        if not bound_pool or bound_pool == self.pool_id:
            if job.state != JobState.active:
                self.batch_client.job.enable(job_id)
                self.logger.info(f"Job {job_id} activated.")
            return job_id

        # The job belongs to a different pool. Re-pointing it only works while
        # it has no active tasks, so fall back to a pool-scoped job rather than
        # failing the submission.
        self.logger.info(
            "Job %s is bound to pool %s; rebinding to selected pool %s.",
            job_id,
            bound_pool,
            self.pool_id,
        )
        try:
            self.batch_client.job.patch(
                job_id,
                JobPatchParameter(
                    pool_info=PoolInformation(pool_id=self.pool_id)
                ),
            )
            if job.state != JobState.active:
                self.batch_client.job.enable(job_id)
            return job_id
        except BatchErrorException as e:
            fallback_id = resolve_job_id(
                job_id, self.pool_id, [job_id, self.pool_id]
            )
            self.logger.info(
                "Rebinding job %s failed (%s); using pool-scoped job %s.",
                job_id,
                getattr(e.error, "code", e),
                fallback_id,
            )
            return self._ensure_job_on_pool(fallback_id)

    def _ensure_job_on_pool(self, job_id):
        # Last step of the fallback: the id is derived from the pool, so it can
        # only be missing or already bound to that same pool.
        try:
            job = self.batch_client.job.get(job_id)
        except BatchErrorException as e:
            if e.error.code == "JobNotFound":
                self._add_job(job_id)
                return job_id
            raise
        if job.state != JobState.active:
            self.batch_client.job.enable(job_id)
        return job_id

    def _add_job(self, job_id):
        job = JobAddParameter(
            id=job_id, pool_info=PoolInformation(pool_id=self.pool_id)
        )
        self.batch_client.job.add(job)
        self.logger.info(f"Job {job_id} created on pool {self.pool_id}.")

    def _bound_pool_for_job(self, job_id: str, job) -> Optional[str]:
        """Shared reconciliation step for an already-fetched job: ensure
        it is usable and return the pool it is actually bound to.

        A ``completed`` job is treated as already reconciled and is
        never re-enabled: per-execution jobs are created with
        ``on_all_tasks_complete=terminate_job`` (see
        ``get_or_create_job_for_execution``) specifically so Batch
        auto-terminates them once their single task finishes and they
        stop counting against the account's active-job quota —
        re-enabling a completed job here would defeat that and leak the
        quota right back. Any other non-active state (disabled, etc.) is
        still re-enabled so the task can be added/read normally.
        """
        if job.state not in (JobState.active, JobState.completed):
            self.batch_client.job.enable(job_id)
        return getattr(job.pool_info, "pool_id", None)

    def get_execution_job_pool(self, job_id: str) -> Optional[str]:
        """Read-first reconciliation lookup for a deterministic
        per-execution ``job_id``: if the job already exists, re-enable it
        if needed and return its actual bound pool *without* ever calling
        ``job.add()`` or touching pool selection/creation. Returns
        ``None`` if the job does not exist yet, in which case the caller
        must fall through to pool selection + creation and
        ``get_or_create_job_for_execution``.

        This must run *before* ``select_pool``/``create_pool_if_not_
        exists`` on every submit attempt: unconditionally re-running pool
        selection first (as an earlier version of this fix did) means a
        retry can pick a pool that has since been deleted/is unavailable
        — Batch's own ``job.add()`` can then reject the add for an
        invalid pool *before* it has a chance to return ``JobExists``,
        breaking reconciliation — and ``manage_pools`` could needlessly
        create/resize a different pool this execution doesn't need at
        all, since the job (and its real pool) already exists.
        """
        try:
            job = self.batch_client.job.get(job_id)
        except BatchErrorException as exc:
            if exc.error.code == "JobNotFound":
                return None
            raise
        return self._bound_pool_for_job(job_id, job)

    def get_or_create_job_for_execution(
        self, job_id: str, preferred_pool_id: str
    ) -> "tuple[str, bool]":
        """Atomically create (or reconcile) the Batch job for a
        deterministic per-execution ``job_id``, and return
        ``(actual_pool_id, created)`` — the pool it is actually bound to,
        and whether *this call* is the one that created it (``False``
        when it instead reconciled to a job another attempt/worker
        already created). Callers use ``created`` to know whether they
        own best-effort cleanup if task submission subsequently fails
        (see ``AzureBatchRunner.submit``'s deterministic-add-failure
        cleanup) — reconciled jobs are never this call's responsibility
        to clean up.

        The job is initially created with ``on_all_tasks_complete=no_action``.
        The caller adds the single task and then patches the job to
        ``terminate_job``. Batch considers an empty job to have completed all
        tasks, so setting ``terminate_job`` at creation time can terminate the
        job before the task is added.

        Only reached when ``get_execution_job_pool`` has already
        confirmed the job doesn't exist yet — so the ``JobExists`` branch
        below only fires for a genuine concurrent creation race (two
        workers/attempts both finding "not found" and racing to create
        it), not for the common retry-with-existing-job case.
        First-writer-wins: whichever attempt's ``job.add()`` call is
        accepted by the Batch service fixes this execution's pool for its
        entire lifetime. Unlike ``create_job``/``resolve_job_id`` (the
        legacy pool-*scoped* job id path, where a retry that lands on a
        different candidate pool computes a different job id and can
        silently create a second, duplicate task under the same
        executionId in a different job), this method never rebinds an
        existing job to a different pool and never falls back to a
        second, differently-named job for the same execution — a losing
        attempt in the concurrent-race case always reconciles to
        whichever pool the winning ``job.add()`` call actually bound.
        """
        try:
            self.batch_client.job.add(
                JobAddParameter(
                    id=job_id,
                    pool_info=PoolInformation(pool_id=preferred_pool_id),
                    on_all_tasks_complete=OnAllTasksComplete.no_action,
                )
            )
            self.logger.info(
                f"Job {job_id} created on pool {preferred_pool_id}."
            )
            return preferred_pool_id, True
        except BatchErrorException as exc:
            if exc.error.code != "JobExists":
                raise

        # Lost the create race to a genuinely concurrent attempt/worker —
        # reconcile to the job's actual bound pool rather than assuming
        # it matches preferred_pool_id.
        job = self.batch_client.job.get(job_id)
        return (
            self._bound_pool_for_job(job_id, job) or preferred_pool_id,
            False,
        )

    def arm_job_auto_terminate(self, job_id: str) -> None:
        """Best-effort arm a populated per-execution job to terminate.

        This runs only after the task exists. Failure is logged rather than
        raised because the task has already been accepted and ``finalize()``
        remains the explicit termination backstop.
        """
        try:
            self.batch_client.job.patch(
                job_id,
                JobPatchParameter(
                    on_all_tasks_complete=OnAllTasksComplete.terminate_job
                ),
            )
        except BatchErrorException as exc:
            if exc.error.code in ("JobNotFound", "JobCompleted"):
                return
            self.logger.warning(
                "Could not arm Batch job %s for automatic termination: %s",
                job_id,
                exc.error.code,
            )

    def terminate_job(self, job_id: str) -> None:
        """Idempotently terminate a Batch job so it stops counting
        against the account's active-job quota.

        Used to finalize per-execution jobs (one task each, see
        ``get_or_create_job_for_execution``): Batch already
        auto-terminates them via ``on_all_tasks_complete=terminate_job``
        once their task completes, but this is the explicit backstop for
        ``AzureBatchRunner.finalize`` and for best-effort cleanup of a
        job left empty by a deterministic task-submission failure. A job
        that no longer exists or has already completed/terminated is
        treated as already terminated rather than an error.
        """
        try:
            self.batch_client.job.terminate(job_id)
            self.logger.info(f"Job {job_id} terminated.")
        except BatchErrorException as exc:
            if exc.error.code in ("JobNotFound", "JobCompleted"):
                return
            raise

    def add_task(
        self,
        job_id,
        task_id,
        image_name,
        command,
        arguments,
        work_dir="/app",
        output_container_url=None,
        output_prefix=None,
        resource_files_for_upload=None,
        file_pattern=None,
        env_vars=None,
        retention_time=None,
    ):
        task_container_settings = TaskContainerSettings(
            image_name=image_name,
            # Run the container as root (0:0) so it can write to the
            # Batch task working directory, which is created on the node by the
            # admin auto-user (see user_identity below). The image otherwise
            # runs as non-root `appuser`, which cannot write under the
            # root-owned /mnt/batch/tasks tree.
            container_run_options="--rm --shm-size=32g --user 0:0",
        )
        if output_prefix is None:
            output_prefix = "output"
        if file_pattern is None:
            file_pattern = "$AZ_BATCH_TASK_WORKING_DIR/**/*"
        # A pattern only ever matches one directory level, so a workload whose
        # outputs live in more than one directory (e.g. imagery writes results
        # to outputs/ and its progress log to logs/) has to supply several.
        if isinstance(file_pattern, str):
            file_patterns = [file_pattern]
        else:
            file_patterns = [p for p in file_pattern if p]

        if resource_files_for_upload is not None:
            resource_files = [
                ResourceFile(
                    http_url=self._maybe_sas(
                        resource_file.get("http_url"), "rl"
                    ),
                    storage_container_url=self._maybe_sas(
                        resource_file.get("storage_container_url"), "rl"
                    ),
                    blob_prefix=resource_file.get("blob_prefix"),
                    file_path=resource_file.get("file_path"),
                    identity_reference=self._blob_identity(),
                )
                for resource_file in resource_files_for_upload.values()
            ]
        else:
            resource_files = []
        if env_vars is None:
            env_vars = []
        else:
            env_vars = [
                EnvironmentSetting(name=key, value=value)
                for key, value in env_vars.items()
            ]
        task_constraints = TaskConstraints(
            retention_time=retention_time,
        )

        # Blob transfer credential: per-job SAS (multi-tenant shared pools) or
        # the pool's managed identity (legacy). Output needs write/create/list.
        output_sas_url = self._maybe_sas(output_container_url, "racwl")
        output_identity = self._blob_identity()

        def _output_file(pattern):
            return OutputFile(
                file_pattern=pattern,
                destination=OutputFileDestination(
                    container=OutputFileBlobContainerDestination(
                        container_url=output_sas_url,
                        path=output_prefix,
                        identity_reference=output_identity,
                    )
                ),
                upload_options=OutputFileUploadOptions(
                    upload_condition=OutputFileUploadCondition.task_completion
                ),
            )

        # Data files, then stdout, stderr, fileuploadout and fileuploaderr.
        output_files = [_output_file(p) for p in file_patterns]
        output_files.append(_output_file("../*.txt"))

        task = TaskAddParameter(
            id=task_id,
            constraints=task_constraints,
            command_line=command,
            container_settings=task_container_settings,
            environment_settings=env_vars,
            resource_files=resource_files,
            user_identity=UserIdentity(
                auto_user=AutoUserSpecification(
                    scope=AutoUserScope.pool,
                    elevation_level=ElevationLevel.admin,
                )
            ),
            output_files=output_files,
        )
        self.batch_client.task.add(job_id, task)

    def is_job_active(self, job_id):
        job = self.batch_client.job.get(job_id)
        return job.state == JobState.active

    def list_jobs(self):
        jobs = self.batch_client.job.list()
        return jobs

    def disable_job(self, job_id):
        try:
            self.batch_client.job.disable(job_id, disable_tasks="wait")
            self.logger.info(f"Job {job_id} disabled.")
        except BatchErrorException as e:
            if e.error.code == "JobNotFound":
                self.logger.warning(
                    f"Job {job_id} not found. It may have already been deleted."
                )
            else:
                raise e

    def is_task_completed(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return task.state == TaskState.completed

    def is_task_succeeded(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return (
            task.state == TaskState.completed
            and task.execution_info.failure_info is None
        )

    def is_task_failed(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return (
            task.state == TaskState.completed
            and task.execution_info.failure_info is not None
        )

    def is_task_running(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return task.state == TaskState.running

    def list_tasks(self, job_id):
        tasks = self.batch_client.task.list(job_id)
        return tasks

    def get_file_from_task(self, job_id, task_id, file_relative_path_name):
        data = self.batch_client.file.get_from_task(
            job_id, task_id, file_relative_path_name
        )
        return data

    def get_file_by_match_from_task(
        self, job_id, task_id, name_filter, recursive=True
    ):
        if not self.is_task_running(
            job_id, task_id
        ) and not self.is_task_completed(job_id, task_id):
            self.logger.warning(
                f"Task {task_id} is not running. Unable to get file list. Try again later."
            )
            return None
        file_list = self.batch_client.file.list_from_task(
            job_id, task_id, recursive=recursive
        )
        if not file_list:
            self.logger.warning(f"No files found for task {task_id}.")
            return None
        for file in file_list:
            # where file contains the filter value
            if name_filter in file.name:
                return str(file.name)
        return None

    def get_task_output(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return task.output_files

    def get_task_logs(self, job_id, task_id):
        task = self.batch_client.task.get(job_id, task_id)
        return task.execution_info

    def get_pool_status(self):
        pool = self.batch_client.pool.get(self.pool_id)
        return pool.state

    def wait_for_pool_to_be_ready(self):
        while True:
            pool = self.batch_client.pool.get(self.pool_id)
            self.logger.info(
                f"Pool {self.pool_id} allocation state: {pool.allocation_state}"
            )
            if pool.allocation_state == AllocationState.steady and (
                pool.current_dedicated_nodes > 0
                or pool.current_low_priority_nodes > 0
            ):
                nodes = self.batch_client.compute_node.list(self.pool_id)
                if all(
                    node.state == ComputeNodeState.unusable for node in nodes
                ):
                    raise RuntimeError(
                        f"All nodes in pool {self.pool_id} are in an unusable state."
                    )
                elif any(
                    node.state == ComputeNodeState.unusable for node in nodes
                ):
                    self.logger.warning(
                        f"Some nodes in pool {self.pool_id} are in an unusable state."
                    )
                nodes = self.batch_client.compute_node.list(self.pool_id)
                any_nodes_ready = any(
                    node.state
                    in (ComputeNodeState.idle, ComputeNodeState.running)
                    for node in nodes
                )
                if any_nodes_ready:
                    self.logger.info(
                        f"Pool {self.pool_id} is ready with atleast one node in idle or running state."
                    )
                    break
                else:
                    self.logger.info(
                        f"Waiting for at least one node in pool {self.pool_id} to be in idle state..."
                    )
            elif pool.allocation_state == AllocationState.resizing:
                self.logger.info(
                    f"Pool {self.pool_id} is resizing. Waiting for nodes to become available..."
                )
            else:
                raise RuntimeError(
                    f"Pool {self.pool_id} is in a {pool.allocation_state} state."
                )
            time.sleep(10)
        self.logger.info(f"Pool {self.pool_id} is ready.")

    def delete_pool(self):
        self.batch_client.pool.delete(self.pool_id)
        self.logger.info(f"Pool {self.pool_id} deleted.")

    def delete_job(self, job_id):
        self.batch_client.job.delete(job_id)
        self.logger.info(f"Job {job_id} deleted.")

    def delete_task(self, job_id, task_id):
        self.batch_client.task.delete(job_id, task_id)
        self.logger.info(f"Task {task_id} deleted.")

    def delete_all_tasks(self, job_id):
        tasks = self.batch_client.task.list(job_id)
        for task in tasks:
            self.batch_client.task.delete(job_id, task.id)
        self.logger.info(f"All tasks for job {job_id} deleted.")

    def delete_all_jobs(self):
        jobs = self.batch_client.job.list()
        for job in jobs:
            self.batch_client.job.delete(job.id)
        self.logger.info("All jobs deleted.")

    def delete_all_pools(self):
        pools = self.batch_client.pool.list()
        for pool in pools:
            self.batch_client.pool.delete(pool.id)
        self.logger.info("All pools deleted.")

    def delete_all_resources(self):
        self.delete_all_tasks()
        self.delete_all_jobs()
        self.delete_all_pools()
        self.logger.info("All resources deleted.")

    def delete_all_resources_except_pool(self):
        self.delete_all_tasks()
        self.delete_all_jobs()
        self.logger.info("All resources except pool deleted.")

    def delete_files_from_task(
        self, job_id, task_id, file_paths=None, recursive=False
    ):
        file_paths = file_paths or ["wd/"]
        if isinstance(file_paths, str):
            file_paths = [file_paths]
        for file_path in file_paths:
            recursive = True if file_path.endswith("/") else False
            self.batch_client.file.delete_from_task(
                job_id, task_id, file_path=file_path, recursive=recursive
            )
            self.logger.info(
                f"{file_path} deleted for task {task_id} with recursive set to {recursive}."
            )

    def cancel_task(self, job_id, task_id):
        message = None
        try:
            self.batch_client.task.terminate(job_id, task_id)
            message = f"Task {task_id} cancelled successfully."
            self.logger.info(message)
        except BatchErrorException as e:
            if e.error.code == "TaskNotFound":
                message = f"Task {task_id} not found. It may have already been completed or deleted."
                self.logger.error(message)
            elif e.error.code == "TaskCompleted":
                message = (
                    f"Task {task_id} has already completed. No action taken."
                )
                self.logger.info(message)
            else:
                raise e
        return message
