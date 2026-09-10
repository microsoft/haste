# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from docker.models.containers import Container
from docker.types import DeviceRequest

import docker

from ..config import Config
from ..models.compute import (
    BackendConfigurationError,
    BackendUnavailableError,
    CapacitySnapshot,
    CapacityState,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeProviderDetail,
    ComputeResources,
    ComputeWorkload,
    LocalProviderDetail,
    validate_relative_path,
)
from ..utils.atomic_files import LockUnavailableError, atomic_write
from ..utils.local_permissions import LOCAL_TASK_ROOT
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.output_files import AmbiguousTaskOutputError, resolve_task_output
from .base import (
    BaseRunner,
    ComputeRunner,
    require_single_output_destination,
    require_supported_uri_schemes,
)
from .base import resource_files_from_inputs as _resource_files_from_inputs
from .local_lifecycle import (
    LIMIT_LABEL,
    OWNER_LABEL,
    POLICY_LABEL,
    SLOT_LABEL,
    TERMINAL_PHASES,
    VOLUME_LABEL,
    LocalReceipt,
    LocalTaskRequest,
    Phase,
    ReceiptStore,
    ResourceDescriptor,
    blob_descriptor,
    execution_key,
    safe_relative_path,
    task_path,
)

TASK_WORK_DIR = LOCAL_TASK_ROOT
ACTIVE_CONTAINER_STATES = {"running", "restarting", "paused"}
_LOCAL_SUPPORTED_URI_SCHEMES = frozenset({"http", "https"})


def _normalize_azurite_url(url: Optional[str]) -> Optional[str]:
    """Replace localhost-style emulator hosts with the azurite service name."""
    if not url:
        return url
    for host in ("localhost", "127.0.0.1"):
        url = url.replace(f"http://{host}", "http://azurite")
    return url


class LocalRunner(BaseRunner, ComputeRunner):
    """Accept local work durably; Docker and periodic reconciliation own it."""

    def __init__(
        self,
        config: Config = None,
        pool_id: str = None,
        candidate_pool_ids: list[str] = None,
    ) -> None:
        super().__init__(config)
        self.pool_id = pool_id or "local-pool"
        self.logger = Logger.get_logger(__name__)
        self.docker_client = docker.from_env()
        storage = self.config.local_storage_config
        if storage["connection_string"]:
            self.blob_client = BlobServiceClient.from_connection_string(
                storage["connection_string"]
            )
        elif storage["account_url"]:
            self.blob_client = BlobServiceClient(
                storage["account_url"], credential=DefaultAzureCredential()
            )
        else:
            raise ValueError(
                "Local tasks require Blob storage configured through Config"
            )
        self.work_dir = TASK_WORK_DIR
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.receipts = ReceiptStore(self.work_dir)
        self.volume = os.getenv(
            "HASTE_DOCKER_AZURITE_VOLUME", "docker_azurite-data"
        )
        self.fail_on_empty_logs = (
            os.getenv("FAIL_ON_EMPTY_OUTPUT_LOG", "0") == "1"
        )
        self.container_images = {
            "imageryprep": "haste-imageryprep",
            "training": "haste-training",
            "inference": "haste-training",
        }

    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        """Read a live or completed output from this task's workspace."""
        execution_key(job_id, task_id)
        job_dir = self.work_dir / job_id / task_id
        try:
            file_path = resolve_task_output(job_dir, filename)
        except AmbiguousTaskOutputError:
            self.logger.warning(
                "Output %s is ambiguous for job %s task %s; unavailable",
                filename,
                job_id,
                task_id,
            )
            return None
        if file_path is not None:
            if as_chunk:
                # Return file content in chunks
                def read_chunks():
                    with open(file_path, "rb") as f:
                        while True:
                            chunk = f.read(8192)
                            if not chunk:
                                break
                            yield chunk

                return read_chunks()
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read()
        else:
            self.logger.warning(
                f"File {filename} not found for job {job_id}, task {task_id}"
            )
            return None

    def get_task_receipt(self, job_id: str, task_id: str) -> dict:
        return self.receipts.load(execution_key(job_id, task_id)).model_dump(
            mode="json"
        )

    def get_task_status(self, job_id: str, task_id: str) -> str:
        statuses = self.config.get_status_types()
        try:
            receipt = self.receipts.load(execution_key(job_id, task_id))
        except FileNotFoundError:
            status_file = self.work_dir / job_id / task_id / "status.json"
            if status_file.exists():
                legacy = json.loads(status_file.read_bytes())
                if (
                    legacy.get("state") == "completed"
                    and legacy.get("exit_code") == 0
                    and legacy.get("outputs_persisted") is True
                ):
                    return statuses.COMPLETED.value
            self.logger.error(
                "No durable execution/persistence evidence for %s/%s",
                job_id,
                task_id,
            )
            return statuses.FAILED.value
        if receipt.phase == "completed":
            if not receipt.outputs_persisted or receipt.exit_code != 0:
                raise RuntimeError("Invalid local completion evidence")
            return statuses.COMPLETED.value
        if receipt.phase == "failed":
            return statuses.FAILED.value
        if receipt.phase == "cancelled":
            return statuses.CANCELLED.value
        return statuses.IN_PROGRESS.value

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
        **kwargs,
    ) -> tuple[str, str]:
        job_id = job_id or f"job-{MetadataUtils.generate_id()}"
        task_id = task_id or f"task-{MetadataUtils.generate_id()}"
        key = execution_key(job_id, task_id)
        request = self._request(
            image_name,
            command,
            arguments,
            output_container_url,
            output_prefix,
            resource_files_for_upload,
            env_vars,
            self._output_patterns(file_pattern, job_id, task_id),
        )
        with self.receipts.lock(key):
            try:
                existing = self.receipts.load(key)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if (
                    existing.request is not None
                    and existing.request.fingerprint() != request.fingerprint()
                ):
                    raise ValueError(
                        "Local execution identity already has another request"
                    )
                return job_id, task_id
            if (self.work_dir / job_id / task_id).exists():
                raise RuntimeError(
                    "Legacy local task files exist without a durable receipt; "
                    "refusing to repeat unknown compute"
                )
            receipt = LocalReceipt(
                job_id=job_id,
                task_id=task_id,
                accepted_at=time.time(),
                request=request,
            )
            self.receipts.save(receipt)
            self._phase_log(
                receipt, "Local task accepted; waiting for capacity"
            )
        return job_id, task_id

    def _request(
        self,
        image_name: str | None,
        command: str | list[str] | None,
        arguments: str | list[str] | None,
        output_container_url: str | None,
        output_prefix: str | None,
        resource_files: dict | None,
        env_vars: dict[str, str] | None,
        output_patterns: list[str],
    ) -> LocalTaskRequest:
        account = self.blob_client.account_name
        account_url = self.blob_client.url
        destination = output_container_url or (
            self.config.artifact_storage_config.get("container")
            or self.config.local_storage_config["container"]
        )
        container, _ = blob_descriptor(
            destination, account, account_url, container_only=True
        )
        resources = []
        for resource in (resource_files or {}).values():
            if "http_url" in resource:
                source_container, blob = blob_descriptor(
                    resource["http_url"],
                    account,
                    account_url,
                    container_only=False,
                )
                prefix = False
            elif "storage_container_url" in resource:
                source_container, _ = blob_descriptor(
                    resource["storage_container_url"],
                    account,
                    account_url,
                    container_only=True,
                )
                blob = safe_relative_path(resource["blob_prefix"])
                prefix = True
            else:
                raise ValueError("Unsupported local task resource")
            resources.append(
                ResourceDescriptor(
                    container=source_container,
                    blob=blob,
                    file_path=resource["file_path"],
                    prefix=prefix,
                )
            )
        return LocalTaskRequest(
            image=self.container_images.get(
                image_name, image_name or "haste-training"
            ),
            command=command,
            arguments=arguments,
            environment=env_vars or {},
            resources=resources,
            output_container=container,
            output_prefix=output_prefix,
            output_patterns=output_patterns,
        )

    def _output_patterns(
        self, patterns: str | list[str] | None, job_id: str, task_id: str
    ) -> list[str]:
        if patterns is None:
            return ["**/*"]
        prefixes = [
            str(self.work_dir / job_id / task_id).replace("\\", "/"),
            *(
                prefix
                for name in (
                    "HASTE_JOB_WORKDIR",
                    "AZ_BATCH_TASK_WORKING_DIR",
                    "BATCH_JOB_WORKDIR",
                )
                for prefix in ("$" + name, "${" + name + "}")
            ),
        ]
        normalized = []
        for pattern in [patterns] if isinstance(patterns, str) else patterns:
            relative = pattern.replace("\\", "/")
            for prefix in prefixes:
                if relative.startswith(prefix + "/"):
                    relative = relative[len(prefix) + 1 :]
                    break
            normalized.append(safe_relative_path(relative))
        return normalized

    def reconcile_tasks(self) -> int:
        reconciled = 0
        errors = 0
        for receipt in self.receipts.list_receipts():
            try:
                self.reconcile_task(receipt.job_id, receipt.task_id)
                reconciled += 1
            except LockUnavailableError:
                self.logger.debug(
                    "Local task %s is being reconciled", receipt.key
                )
            except Exception as error:
                errors += 1
                self.logger.error(
                    "Local reconciliation failed for %s (%s)",
                    receipt.key,
                    type(error).__name__,
                )
                with self.receipts.lock(receipt.key):
                    current = self.receipts.load(receipt.key)
                    current.error = (
                        f"Local reconciliation interrupted ({type(error).__name__}); "
                        "the next timer invocation will retry"
                    )
                    self.receipts.save(current)
        if errors:
            raise RuntimeError(
                f"Local reconciliation failed for {errors} tasks"
            )
        return reconciled

    def reconcile_task(self, job_id: str, task_id: str) -> None:
        key = execution_key(job_id, task_id)
        with self.receipts.lock(key, operation=True, timeout=0):
            pending = self.receipts.load(key)
            if (
                pending.cancel_requested
                and pending.phase not in TERMINAL_PHASES | {"uploading"}
            ):
                self.cancel_task(job_id, task_id)
            with self.receipts.lock(key):
                receipt = self.receipts.load(key)
                if receipt.phase == "queued":
                    if receipt.cancel_requested:
                        self._set_phase(receipt, "uploading")
                    elif not self._reserve_capacity(receipt):
                        return
                    else:
                        self._set_phase(receipt, "preparing")
            if receipt.phase == "preparing":
                self._prepare(receipt)
            receipt = self.receipts.load(key)
            if receipt.phase == "running":
                self._inspect(receipt)
            receipt = self.receipts.load(key)
            if receipt.phase == "uploading":
                self._persist_outputs(receipt)
            with self.receipts.lock(key):
                receipt = self.receipts.load(key)
                if receipt.phase in TERMINAL_PHASES:
                    self._release_capacity(receipt)
                    self._cleanup_if_safe(receipt)

    def _set_phase(self, receipt: LocalReceipt, phase: Phase) -> None:
        receipt.phase = phase
        receipt.error = None
        self.receipts.save(receipt)
        self._phase_log(receipt, f"Local task {phase}")

    def _phase_log(self, receipt: LocalReceipt, message: str) -> None:
        task_dir = self.work_dir / receipt.job_id / receipt.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        task_dir.chmod(0o777)
        log_dir = task_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        log_dir.chmod(0o777)
        log_path = log_dir / "workflow_progress.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"{MetadataUtils.get_timestamp()}|{message}\n")
            log.flush()
        log_path.chmod(0o666)

    def _owned_container(
        self, receipt: LocalReceipt, *, slot: int | None = None
    ) -> Container | None:
        name = (
            f"haste-local-slot-{slot}"
            if slot is not None
            else receipt.container_id or receipt.container_name
        )
        try:
            container = self.docker_client.containers.get(name)
        except docker.errors.NotFound:
            return None
        if (
            container.labels.get(OWNER_LABEL) != receipt.key
            or container.labels.get(VOLUME_LABEL) != self.volume
        ):
            raise RuntimeError("Docker execution ownership mismatch")
        return container

    def _reserve_capacity(self, receipt: LocalReceipt) -> bool:
        if receipt.request is None:
            raise RuntimeError("Queued local receipt has no launch request")
        limit = self.config.local_max_active_tasks
        self._ensure_capacity_policy(receipt.request.image, limit)
        for slot in range(limit):
            name = f"haste-local-slot-{slot}"
            try:
                reservation = self.docker_client.containers.create(
                    receipt.request.image,
                    name=name,
                    command="/bin/true",
                    network_disabled=True,
                    mem_limit="16m",
                    cpu_period=100000,
                    cpu_quota=1000,
                    labels={
                        OWNER_LABEL: receipt.key,
                        VOLUME_LABEL: self.volume,
                        SLOT_LABEL: str(slot),
                        LIMIT_LABEL: str(limit),
                    },
                )
            except docker.errors.APIError as error:
                if error.status_code != 409:
                    raise
                try:
                    reservation = self.docker_client.containers.get(name)
                except docker.errors.NotFound:
                    # A competing completion released the slot; retry next tick.
                    return False
                if reservation.labels.get(LIMIT_LABEL) != str(limit):
                    raise RuntimeError(
                        "Conflicting local admission limits; drain active work "
                        "before changing HASTE_LOCAL_MAX_ACTIVE_TASKS"
                    ) from error
                if (
                    reservation.labels.get(OWNER_LABEL) != receipt.key
                    or reservation.labels.get(VOLUME_LABEL) != self.volume
                ):
                    continue
            receipt.slot = slot
            self.receipts.save(receipt)
            return True
        return False

    def _ensure_capacity_policy(self, image: str, limit: int) -> None:
        name = "haste-local-capacity"
        try:
            policy = self.docker_client.containers.get(name)
        except docker.errors.NotFound:
            try:
                policy = self.docker_client.containers.create(
                    image,
                    name=name,
                    command="/bin/true",
                    network_disabled=True,
                    mem_limit="16m",
                    labels={POLICY_LABEL: "1", LIMIT_LABEL: str(limit)},
                )
            except docker.errors.APIError as error:
                if error.status_code != 409:
                    raise
                policy = self.docker_client.containers.get(name)
        if policy.labels.get(POLICY_LABEL) != "1" or policy.labels.get(
            LIMIT_LABEL
        ) != str(limit):
            raise RuntimeError(
                "Local host capacity policy differs from Config; drain all "
                "local work and remove haste-local-capacity before changing "
                "HASTE_LOCAL_MAX_ACTIVE_TASKS on every controller"
            )

    def _release_capacity(self, receipt: LocalReceipt) -> None:
        if receipt.slot is not None:
            execution = self._owned_container(receipt)
            if (
                execution is not None
                and execution.status in ACTIVE_CONTAINER_STATES
            ):
                raise RuntimeError(
                    "Cannot release capacity for active compute"
                )
            container = self._owned_container(receipt, slot=receipt.slot)
            if container is not None:
                container.remove()
            receipt.slot = None
            self.receipts.save(receipt)

    def _prepare(self, receipt: LocalReceipt) -> None:
        container = self._owned_container(receipt)
        if container is None and receipt.start_requested:
            self._fail(
                receipt.key, "Previously started Docker execution is missing"
            )
            return
        if container is None:
            try:
                self._download_resource_files(receipt)
            except Exception as error:
                self.logger.error(
                    "Input staging failed for %s (%s)",
                    receipt.key,
                    type(error).__name__,
                )
                self._fail(
                    receipt.key,
                    f"Input staging failed ({type(error).__name__})",
                )
                return
        with self.receipts.lock(receipt.key):
            current = self.receipts.load(receipt.key)
            if current.cancel_requested:
                return
            if container is None:
                try:
                    container = self.docker_client.containers.create(
                        **self._launch_options(current)
                    )
                except docker.errors.APIError as error:
                    if error.status_code != 409:
                        raise
                    container = self._owned_container(current)
                    if container is None:
                        raise
            current.container_id = container.id
            current.start_requested = True
            self.receipts.save(current)
            if container.status == "created":
                container.start()
            self._set_phase(current, "running")

    def _download_resource_files(self, receipt: LocalReceipt) -> None:
        if receipt.request is None:
            raise RuntimeError("Local task has no resource descriptors")
        root = self.work_dir / receipt.job_id / receipt.task_id
        for resource in receipt.request.resources:
            if self.receipts.load(receipt.key).cancel_requested:
                return
            self.logger.info(
                "Staging local input %s for %s",
                resource.file_path,
                receipt.key,
            )
            if resource.prefix:
                client = self.blob_client.get_container_client(
                    resource.container
                )
                names = [
                    blob.name
                    for blob in client.list_blobs(
                        name_starts_with=resource.blob.rstrip("/") + "/"
                    )
                ]
                if not names:
                    raise FileNotFoundError(
                        "Required resource prefix is empty"
                    )
            else:
                names = [resource.blob]
            for name in names:
                if self.receipts.load(receipt.key).cancel_requested:
                    return
                relative = (
                    f"{resource.file_path.rstrip('/')}/{name}"
                    if resource.prefix
                    else resource.file_path
                )
                target = task_path(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.staging")
                try:
                    client = self.blob_client.get_blob_client(
                        resource.container, name
                    )
                    with temporary.open("wb") as output:
                        client.download_blob().readinto(output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, target)
                    target.chmod(0o666)
                finally:
                    temporary.unlink(missing_ok=True)
        for directory in root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o777)

    def _launch_options(self, receipt: LocalReceipt) -> dict[str, Any]:
        request = receipt.request
        if request is None:
            raise RuntimeError("Local task has no launch request")
        working_dir = (
            f"/shared/azurite/task_work/{receipt.job_id}/{receipt.task_id}"
        )
        task_env = self._task_environment(receipt, working_dir)
        command = request.command
        if request.arguments:
            if isinstance(request.arguments, list):
                if command is not None and not isinstance(command, list):
                    raise ValueError("List arguments require a list command")
                command = (command or []) + request.arguments
            else:
                command = (
                    f"{command} {request.arguments}"
                    if command
                    else request.arguments
                )
        replacements = {
            "HASTE_JOB_WORKDIR": working_dir,
            "AZ_BATCH_TASK_WORKING_DIR": working_dir,
            "BATCH_JOB_WORKDIR": working_dir,
            "AZ_BATCH_JOB_ID": receipt.job_id,
            "AZ_BATCH_TASK_ID": receipt.task_id,
        }

        def replace(value: str) -> str:
            for variable, replacement in replacements.items():
                value = value.replace("${" + variable + "}", replacement)
                value = value.replace("$" + variable, replacement)
            return value

        if isinstance(command, str):
            command = replace(command)
        elif isinstance(command, list):
            command = [replace(arg) for arg in command]
        if request.image.startswith("haste-") and isinstance(command, list):
            command = (
                command[2]
                if len(command) == 3 and command[:2] == ["/bin/bash", "-c"]
                else " ".join(command)
            )
        elif (
            not request.image.startswith("haste-")
            and isinstance(command, str)
            and any(token in command for token in ("&&", "$", "|"))
        ):
            command = ["/bin/bash", "-c", command]
        devices = None
        if os.getenv("HASTE_ENABLE_GPU", "0").lower() in {"1", "true", "yes"}:
            gpu_devices = os.getenv("HASTE_GPU_DEVICES", "all").strip().lower()
            if gpu_devices == "all":
                devices = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
            else:
                ids = [
                    item.strip()
                    for item in gpu_devices.split(",")
                    if item.strip()
                ]
                if not ids:
                    raise ValueError(
                        "HASTE_GPU_DEVICES must name devices or all"
                    )
                devices = [
                    DeviceRequest(device_ids=ids, capabilities=[["gpu"]])
                ]
                task_env["CUDA_VISIBLE_DEVICES"] = ",".join(ids)
                task_env["NVIDIA_VISIBLE_DEVICES"] = ",".join(ids)
        return {
            "image": request.image,
            "name": receipt.container_name,
            "command": command,
            "environment": task_env,
            "volumes": {
                self.volume: {"bind": "/shared/azurite", "mode": "rw"}
            },
            "working_dir": working_dir,
            "device_requests": devices,
            "shm_size": os.getenv("HASTE_DOCKER_SHM_SIZE", "8g"),
            "mem_limit": os.getenv("HASTE_DOCKER_MEM_LIMIT", "32g"),
            "network": os.getenv("HASTE_DOCKER_NETWORK", "docker_default"),
            "auto_remove": False,
            "labels": {OWNER_LABEL: receipt.key, VOLUME_LABEL: self.volume},
        }

    def _task_environment(
        self, receipt: LocalReceipt, working_dir: str
    ) -> dict[str, str]:
        environment = {
            "HASTE_LOCAL_SHARED_WORKSPACE": "1",
            "HASTE_JOB_WORKDIR": working_dir,
            "BATCH_JOB_WORKDIR": working_dir,
            "AZ_BATCH_TASK_WORKING_DIR": working_dir,
            "AZ_BATCH_JOB_ID": receipt.job_id,
            "AZ_BATCH_TASK_ID": receipt.task_id,
            "DATA_PATH": working_dir,
            "METADATA_STORAGE_TYPE": self.config.storage_type,
            "ARTIFACT_STORAGE_TYPE": self.config.artifact_storage_type,
            "IMAGERY_STORAGE_TYPE": os.getenv(
                "IMAGERY_STORAGE_TYPE", self.config.artifact_storage_type
            ),
            "BLOB_CONTAINER": self.config.local_storage_config["container"],
        }
        connection = self.config.local_storage_config["connection_string"]
        if connection:
            environment.update(
                {
                    "AZURE_STORAGE_CONNECTION_STRING": connection,
                    "BLOB_CONNECTION_STRING": connection,
                    "AzureWebJobsStorage": (
                        self.config.queue_config["queue_connection_string"]
                        or connection
                    ),
                }
            )
        credential = getattr(self.blob_client, "credential", None)
        if credential is not None and hasattr(credential, "account_key"):
            environment["STORAGE_ACCOUNT_KEY"] = credential.account_key
        environment["STORAGE_ACCOUNT_NAME"] = self.blob_client.account_name
        account_url = _normalize_azurite_url(self.blob_client.url)
        environment["STORAGE_ACCOUNT_URL"] = account_url
        environment["BLOB_ACCOUNT_URL"] = account_url
        queue_url = _normalize_azurite_url(
            self.config.queue_config.get("queue_account_url")
        )
        if queue_url:
            environment["QUEUE_ACCOUNT_URL"] = queue_url
        for key, value in self.config.queue_config.items():
            if key.endswith("_queue_name") and value:
                environment[key.upper()] = value
        for key in ("HASTE_DEBUG_VERBOSE", "HASTE_DATALOADER_WORKERS"):
            if os.getenv(key):
                environment[key] = os.environ[key]
        if receipt.request:
            environment.update(receipt.request.environment)
        return environment

    def _snapshot_logs(
        self, container: Container, receipt: LocalReceipt
    ) -> None:
        output = (
            self.work_dir / receipt.job_id / receipt.task_id / "output.log"
        )
        temporary = output.with_name(".output.log.snapshot")
        try:
            with temporary.open("wb") as log:
                for chunk in container.logs(
                    stream=True, follow=False, stdout=True, stderr=True
                ):
                    log.write(chunk)
                log.flush()
                os.fsync(log.fileno())
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)

    def _inspect(self, receipt: LocalReceipt) -> None:
        container = self._owned_container(receipt)
        if container is None:
            self._fail(
                receipt.key,
                "Docker execution is missing; compute will not be repeated",
            )
            return
        self._snapshot_logs(container, receipt)
        if container.status in ACTIVE_CONTAINER_STATES:
            return
        if container.status not in {"exited", "dead"}:
            raise RuntimeError(
                "Docker execution has no terminal exit evidence"
            )
        exit_code = container.attrs["State"]["ExitCode"]
        if not isinstance(exit_code, int):
            raise RuntimeError("Docker execution has no exit code")
        with self.receipts.lock(receipt.key):
            current = self.receipts.load(receipt.key)
            current.exit_code = exit_code
            self._set_phase(current, "uploading")

    def _persist_outputs(self, receipt: LocalReceipt) -> None:
        task_dir = self.work_dir / receipt.job_id / receipt.task_id
        request = receipt.request
        if request is None:
            raise RuntimeError("Local task has no output descriptor")
        try:
            container = self._owned_container(receipt)
            if container is not None:
                if container.status in ACTIVE_CONTAINER_STATES:
                    raise RuntimeError(
                        "Cannot persist a running task as terminal"
                    )
                self._snapshot_logs(container, receipt)
            self._prepare_output_permissions(receipt)
            if receipt.exit_code == 0 and not receipt.cancel_requested:
                command = str(request.command or "")
                if (
                    "prepare-imagery" in command
                    or "prepare_imagery" in command
                ) and not (
                    task_dir / "outputs" / "imagery_manifest.json"
                ).is_file():
                    raise FileNotFoundError(
                        "Required imagery manifest is missing"
                    )
                if self.fail_on_empty_logs and (
                    not (task_dir / "output.log").is_file()
                    or (task_dir / "output.log").stat().st_size == 0
                ):
                    raise ValueError("Task output.log is empty")
            self._upload_all_task_files(
                task_dir,
                request.output_container,
                request.output_prefix,
                request.output_patterns,
            )
            with self.receipts.lock(receipt.key):
                current = self.receipts.load(receipt.key)
                phase = (
                    "cancelled"
                    if current.cancel_requested
                    else "completed"
                    if current.exit_code == 0
                    else "failed"
                )
                status = {
                    "state": phase,
                    "exit_code": current.exit_code,
                    "outputs_persisted": True,
                    "job_id": current.job_id,
                    "task_id": current.task_id,
                }
                status_path = task_dir / "status.json"
                atomic_write(status_path, json.dumps(status).encode())
                self._upload_single_file(
                    status_path,
                    request.output_container,
                    "/".join(
                        filter(None, [request.output_prefix, "status.json"])
                    ),
                )
                current.phase = phase
                current.outputs_persisted = True
                current.error = None
                self.receipts.save(current)
        except Exception as error:
            self.logger.error(
                "Output persistence failed for %s (%s)",
                receipt.key,
                type(error).__name__,
            )
            self._fail(
                receipt.key,
                f"Output persistence failed ({type(error).__name__}); task files retained",
            )

    def _permissions_needed(self, task_dir: Path) -> bool:
        def on_error(error: OSError) -> None:
            raise error

        try:
            for directory, _, files in os.walk(
                task_dir, followlinks=False, onerror=on_error
            ):
                if not os.access(directory, os.R_OK | os.W_OK | os.X_OK):
                    return True
                for filename in files:
                    path = Path(directory) / filename
                    if not path.is_symlink() and not os.access(path, os.R_OK):
                        return True
        except PermissionError:
            return True
        return False

    def _prepare_output_permissions(self, receipt: LocalReceipt) -> None:
        task_dir = self.work_dir / receipt.job_id / receipt.task_id
        if not self._permissions_needed(task_dir):
            return
        if receipt.request is None:
            raise RuntimeError(
                "Permission repair requires the original task image"
            )
        self.logger.info(
            "Preparing task output permissions using its image user: %s",
            receipt.key,
        )
        self.docker_client.containers.run(
            receipt.request.image,
            entrypoint=[
                "python",
                "-m",
                "hastegeo.core.utils.local_permissions",
            ],
            command=[
                self._resolved_container_working_dir(
                    receipt.job_id, receipt.task_id
                )
            ],
            environment={
                "PYTHONPATH": "/app",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            working_dir="/app",
            volumes={self.volume: {"bind": "/shared/azurite", "mode": "rw"}},
            network_disabled=True,
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit="256m",
            nano_cpus=500_000_000,
            pids_limit=64,
            remove=True,
            labels={
                OWNER_LABEL: receipt.key,
                VOLUME_LABEL: self.volume,
                "org.haste.local.helper": "permissions",
            },
        )
        if self._permissions_needed(task_dir):
            raise PermissionError("Local task outputs remain inaccessible")

    def _upload_all_task_files(
        self,
        task_dir: Path,
        output_container_url: str,
        output_prefix: str | None,
        patterns: list[str] | None = None,
    ) -> None:
        if self.blob_client is None:
            raise RuntimeError("No storage client for local task outputs")
        selected = {
            path
            for pattern in patterns or ["**/*"]
            for path in task_dir.glob(pattern)
        }
        selected.update(task_dir.glob("logs/**/*"))
        if (task_dir / "output.log").exists():
            selected.add(task_dir / "output.log")
        for path in sorted(selected):
            if path.is_symlink():
                raise ValueError("Task output symlinks cannot be persisted")
            if not path.resolve().is_relative_to(task_dir.resolve()):
                raise ValueError("Task output escapes its workspace")
            if not path.is_file() or path == task_dir / "status.json":
                continue
            relative = path.relative_to(task_dir)
            if relative.parts[0] == "outputs" and len(relative.parts) > 1:
                relative = Path(*relative.parts[1:])
            blob_name = "/".join(
                filter(None, [output_prefix, relative.as_posix()])
            )
            self._upload_single_file(path, output_container_url, blob_name)

    def _upload_single_file(
        self, file_path: Path, container_url: str, blob_name: str
    ) -> None:
        try:
            client = self.blob_client.get_blob_client(container_url, blob_name)
            with file_path.open("rb") as contents:
                client.upload_blob(contents, overwrite=True)
        except Exception as error:
            self.logger.error(
                "Local task output upload failed (%s)", type(error).__name__
            )
            raise RuntimeError("Failed to persist local task file") from error

    def _fail(self, key: str, message: str) -> None:
        self.logger.error("%s: %s", key, message)
        with self.receipts.lock(key):
            current = self.receipts.load(key)
            current.phase = (
                "cancelled" if current.cancel_requested else "failed"
            )
            current.outputs_persisted = False
            current.error = message
            self.receipts.save(current)
            self._phase_log(current, message)
            atomic_write(
                self.work_dir
                / current.job_id
                / current.task_id
                / "status.json",
                json.dumps(
                    {
                        "state": current.phase,
                        "exit_code": current.exit_code,
                        "outputs_persisted": False,
                        "error": message,
                    }
                ).encode(),
            )

    def cancel_task(self, job_id: str, task_id: str) -> bool:
        key = execution_key(job_id, task_id)
        with self.receipts.lock(key):
            try:
                receipt = self.receipts.load(key)
            except FileNotFoundError:
                if (self.work_dir / job_id / task_id).exists():
                    raise RuntimeError(
                        "Cannot safely cancel a legacy local task without "
                        "an owned Docker execution identity"
                    )
                receipt = LocalReceipt(
                    job_id=job_id,
                    task_id=task_id,
                    accepted_at=time.time(),
                    phase="cancelled",
                    cancel_requested=True,
                )
                self.receipts.save(receipt)
                return True
            if receipt.phase in TERMINAL_PHASES:
                return True
            receipt.cancel_requested = True
            self.receipts.save(receipt)
            container = self._owned_container(receipt)
            if (
                container is not None
                and container.status in ACTIVE_CONTAINER_STATES
            ):
                if container.status == "paused":
                    container.unpause()
                try:
                    container.stop(timeout=5)
                except docker.errors.APIError:
                    container.reload()
                    if container.status in ACTIVE_CONTAINER_STATES:
                        raise
                container.reload()
                if container.status in ACTIVE_CONTAINER_STATES:
                    raise RuntimeError("Docker execution did not stop")
                receipt.exit_code = container.attrs["State"]["ExitCode"]
            self._set_phase(receipt, "uploading")
        return True

    def cleanup_task(self, job_id: str, task_id: str) -> None:
        key = execution_key(job_id, task_id)
        with self.receipts.lock(key):
            try:
                receipt = self.receipts.load(key)
            except FileNotFoundError:
                self.logger.warning(
                    "Retaining task files without a durable receipt"
                )
                return
            receipt.cleanup_requested = True
            self.receipts.save(receipt)
        try:
            with self.receipts.lock(key, operation=True, timeout=0):
                with self.receipts.lock(key):
                    self._cleanup_if_safe(self.receipts.load(key))
        except LockUnavailableError:
            self.logger.info("Task cleanup deferred to reconciliation")

    def _cleanup_if_safe(self, receipt: LocalReceipt) -> None:
        if (
            receipt.phase not in TERMINAL_PHASES
            or not receipt.outputs_persisted
        ):
            return
        if os.getenv("CLEANUP_CONTAINERS", "1") == "1":
            container = self._owned_container(receipt)
            if container is not None:
                if container.status in ACTIVE_CONTAINER_STATES:
                    raise RuntimeError(
                        "Refusing to remove an active execution"
                    )
                container.remove()
        if (
            not receipt.cleanup_requested
            or receipt.files_cleaned
            or os.getenv("PRESERVE_LOCAL_TASK_DIRS", "0") == "1"
        ):
            return
        task_dir = self.work_dir / receipt.job_id / receipt.task_id
        if task_dir.exists():
            self._prepare_output_permissions(receipt)
            shutil.rmtree(task_dir)
        receipt.files_cleaned = True
        self.receipts.save(receipt)

    def ensure_docker_images(self) -> bool:
        missing = []
        for image in set(self.container_images.values()):
            try:
                self.docker_client.images.get(image)
            except docker.errors.ImageNotFound:
                missing.append(image)
        if missing:
            self.logger.error(
                "Required local Docker images are missing: %s", missing
            )
        return not missing

    def validate(self, spec: ComputeJobSpec) -> None:
        if self.docker_client is None:
            raise BackendConfigurationError(
                "local Docker client is not available"
            )
        try:
            self.docker_client.ping()
        except docker.errors.DockerException as exc:
            raise BackendUnavailableError(
                f"local Docker daemon is unreachable: {exc}"
            ) from exc
        if not spec.outputs:
            raise BackendConfigurationError(
                "local runner requires at least one output so the task's "
                "artifacts land at a known path"
            )
        try:
            require_supported_uri_schemes(
                inputs=spec.inputs,
                outputs=spec.outputs,
                allowed_schemes=_LOCAL_SUPPORTED_URI_SCHEMES,
                backend_name="the local runner",
            )
            if any(
                "<" in output.destinationUri or ">" in output.destinationUri
                for output in spec.outputs
            ):
                raise ValueError(
                    "COMPUTE_OUTPUT_CONTAINER_URL must point to the "
                    "configured storage container, not a placeholder"
                )
            require_single_output_destination(
                spec.outputs, account_url=self._storage_account_url()
            )
            _resource_files_from_inputs(
                spec.inputs, account_url=self._storage_account_url()
            )
        except ValueError as exc:
            raise BackendConfigurationError(str(exc)) from exc

    def _storage_account_url(self) -> Optional[str]:
        return self.blob_client.url if self.blob_client is not None else None

    def _resolved_container_working_dir(
        self, job_id: str, task_id: str
    ) -> str:
        execution_key(job_id, task_id)
        return f"/shared/azurite/task_work/{job_id}/{task_id}"

    def submit(self, spec: ComputeJobSpec) -> ComputeJobHandle:
        self.validate(spec)
        job_id = f"job-{spec.executionId}"
        task_id = spec.executionId
        task_dir = self.work_dir / job_id / task_id

        account_url = self._storage_account_url()
        resource_files = _resource_files_from_inputs(
            spec.inputs, account_url=account_url
        )
        (
            _,
            container_name,
            output_prefix,
            patterns,
        ) = require_single_output_destination(
            spec.outputs, account_url=account_url
        )
        self.add_task(
            job_id=job_id,
            task_id=task_id,
            image_name=spec.container.imageReference,
            command=spec.command,
            work_dir=spec.container.workingDirectory,
            output_container_url=container_name,
            output_prefix=output_prefix,
            resource_files_for_upload=resource_files or None,
            file_pattern=patterns,
            env_vars=dict(spec.environment),
        )

        return ComputeJobHandle(
            executionId=spec.executionId,
            requestedBackend=ComputeBackend.LOCAL,
            selectedBackend=ComputeBackend.LOCAL,
            backendProfile="default",
            providerJobId=job_id,
            providerTaskId=task_id,
            targetId=self.pool_id,
            outputUri=spec.outputs[0].destinationUri,
            submittedAt=MetadataUtils.get_timestamp(),
            routingReason="adapter-default",
            attempt=1,
            providerDetail=ComputeProviderDetail(
                discriminator="local",
                local=LocalProviderDetail(executionDirectory=str(task_dir)),
            ),
        )

    def get_status(self, handle: ComputeJobHandle) -> ComputeJobState:
        try:
            receipt = self.receipts.load(
                execution_key(handle.providerJobId, handle.providerTaskId)
            )
        except FileNotFoundError:
            receipt = None
        if receipt is not None and receipt.phase not in TERMINAL_PHASES:
            return {
                "queued": ComputeJobState.QUEUED,
                "preparing": ComputeJobState.PREPARING,
                "running": ComputeJobState.RUNNING,
                "uploading": ComputeJobState.RUNNING,
            }[receipt.phase]
        status = self.get_task_status(
            handle.providerJobId, handle.providerTaskId
        )
        status_types = self.config.get_status_types()
        if status == status_types.COMPLETED.value:
            return ComputeJobState.SUCCEEDED
        if status == status_types.FAILED.value:
            return ComputeJobState.FAILED
        if status == status_types.CANCELLED.value:
            return ComputeJobState.CANCELLED
        if status == status_types.IN_PROGRESS.value:
            return ComputeJobState.RUNNING
        # Log the raw provider status server-side before failing
        # explicitly, matching the AML adapter's unmapped-status
        # diagnostics (design.md's "Unknown provider status" edge case) —
        # never silently report an unrecognized status as "running".
        self.logger.error(
            "Unmapped local task status %r for task %s (job %s)",
            status,
            handle.providerTaskId,
            handle.providerJobId,
        )
        raise BackendUnavailableError(
            f"unmapped local task status: {status!r}"
        )

    def read_output(
        self,
        handle: ComputeJobHandle,
        relative_path: str,
        *,
        as_chunks: bool = False,
    ):
        validate_relative_path(relative_path, field_name="relative_path")
        return self.get_filecontent_from_task(
            handle.providerJobId,
            handle.providerTaskId,
            relative_path,
            as_chunk=as_chunks,
        )

    def cancel(self, handle: ComputeJobHandle) -> None:
        self.cancel_task(handle.providerJobId, handle.providerTaskId)

    def finalize(self, handle: ComputeJobHandle) -> None:
        self.cleanup_task(handle.providerJobId, handle.providerTaskId)

    def get_capacity(
        self, workload: ComputeWorkload, resources: ComputeResources
    ) -> CapacitySnapshot:
        try:
            self.docker_client.ping()
        except docker.errors.DockerException as exc:
            return CapacitySnapshot(
                backend=ComputeBackend.LOCAL,
                workload=workload,
                state=CapacityState.UNAVAILABLE,
                detail=f"local Docker daemon unreachable: {exc}",
            )
        occupied = 0
        for slot in range(self.config.local_max_active_tasks):
            try:
                self.docker_client.containers.get(f"haste-local-slot-{slot}")
            except docker.errors.NotFound:
                continue
            occupied += 1
        return CapacitySnapshot(
            backend=ComputeBackend.LOCAL,
            workload=workload,
            state=(
                CapacityState.QUEUEABLE
                if occupied >= self.config.local_max_active_tasks
                else CapacityState.AVAILABLE
            ),
            detail=(
                f"{occupied}/{self.config.local_max_active_tasks} "
                "local execution slots reserved"
            ),
        )
