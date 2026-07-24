# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import io
import time
from datetime import datetime, timedelta, timezone
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
    JobState,
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
from azure.identity import DefaultAzureCredential
from azure.storage.blob import (
    BlobServiceClient,
    ContainerSasPermissions,
    generate_container_sas,
)
from hastegeo.core.config import Config
from hastegeo.core.utils.logs import Logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import BaseRunner


class AzureBatchRunner(BaseRunner):
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
        full_file_name = self.batch_cluster.get_file_by_match_from_task(
            job_id, task_id, filename
        )
        if full_file_name is None:
            return None
        output = self.batch_cluster.get_file_from_task(
            job_id, task_id, full_file_name
        )
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

        # Pre-created IaC/autoscale pools manage their own lifecycle; only
        # auto-create/resize for legacy single-pool envs (manage_pools=True).
        if self.manage_pools:
            self.logger.info(
                "Creating pool for job_id: %s and task_id: %s", job_id, task_id
            )
            self.batch_cluster.create_pool_if_not_exists(
                self.batch_config["vm_size"],
                self.batch_config["vm_publisher"],
                self.batch_config["vm_offer"],
                self.batch_config["vm_sku"],
                self.batch_config["vm_version"],
                self.batch_config["target_dedicated_nodes"],
                self.batch_config["target_low_priority_nodes"],
                self.batch_config["registry_server"],
                [self.batch_config["registry_image"]],
                self.batch_config["node_agent_sku_id"],
            )
        self.logger.info(
            "Creating job for job_id: %s and task_id: %s", job_id, task_id
        )
        self.batch_cluster.create_job(job_id)

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
        self.batch_cluster.delete_files_from_task(job_id, task_id)
        self.batch_cluster.disable_job(job_id)

    def cancel_task(self, job_id, task_id):
        return self.batch_cluster.cancel_task(job_id, task_id)


def is_server_error(exception):
    if isinstance(exception, BatchErrorException):
        # Check if the status code is in the 5xx range
        status_code = exception.response.status_code
        return 500 <= status_code < 600
    return False


def retry_on_server_error():
    return retry(
        retry=retry_if_exception(is_server_error),
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
        # Fixed pools we manage need a ready node before the job is created;
        # autoscale / pre-created pools scale up in response to queued tasks, so
        # waiting here would deadlock (0 nodes until tasks exist).
        if self.manage_pools:
            self.wait_for_pool_to_be_ready()
        try:
            job = self.batch_client.job.get(job_id)
            if job.state != JobState.active:
                self.batch_client.job.enable(job_id)
                self.logger.info(f"Job {job_id} activated.")
        except BatchErrorException as e:
            if e.error.code == "JobNotFound":
                job = JobAddParameter(
                    id=job_id, pool_info=PoolInformation(pool_id=self.pool_id)
                )
                self.batch_client.job.add(job)
                self.logger.info(f"Job {job_id} created.")

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
            output_files=[
                # Data files
                OutputFile(
                    file_pattern=file_pattern,
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
                ),
                # grabs stdout, stderr, fileuploadout and fileuploaderr
                OutputFile(
                    file_pattern="../*.txt",
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
                ),
            ],
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
