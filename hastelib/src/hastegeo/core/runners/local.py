# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import glob
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from azure.storage.blob import BlobClient, BlobServiceClient
from azure.storage.queue import QueueServiceClient
from docker.types import DeviceRequest
from hastegeo.core.config import Config
from hastegeo.core.utils.logs import Logger

import docker

from .base import BaseRunner


def _normalize_azurite_url(url: Optional[str]) -> Optional[str]:
    """Replace localhost-style emulator hosts with the azurite service name."""

    if not url:
        return url

    normalized = url
    for host in ("localhost", "127.0.0.1"):
        normalized = normalized.replace(f"http://{host}", "http://azurite")
    return normalized


class LocalRunner(BaseRunner):
    """Local runner that executes containers using Docker instead of Azure Batch."""

    def __init__(self, config: Config = None, pool_id=None):
        super().__init__(config)
        self.config = config or Config()
        self.pool_id = pool_id or "local-pool"
        self.logger = Logger.get_logger(__name__)
        self.verbose = os.getenv("HASTE_DEBUG_VERBOSE", "0") == "1"

        self.fail_on_empty_logs = (
            os.getenv("FAIL_ON_EMPTY_OUTPUT_LOG", "0") == "1"
        )

        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            self.logger.error(f"Failed to connect to Docker: {e}")
            raise

        # Storage clients - using environment variables for local development
        connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if connection_string:
            try:
                self.blob_client = BlobServiceClient.from_connection_string(
                    connection_string
                )
                self.queue_client = QueueServiceClient.from_connection_string(
                    connection_string
                )
            except Exception as e:
                self.logger.error(f"Failed to connect to storage: {e}")
                raise
        else:
            self.logger.warning("No AZURE_STORAGE_CONNECTION_STRING found")
            self.blob_client = None
            self.queue_client = None

        # Local work directory for tasks
        # Use a directory inside the azurite volume (but not __blobstorage__)
        # This way spawned containers can access it, and it's separate from blob storage
        self.work_dir = Path("/shared/azurite/task_work")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Container images mapping - map ACR images to local ones
        self.container_images = {
            "imageryprep": "haste-imageryprep",
            "training": "haste-training",
            "inference": "haste-training",  # Same container, different command
        }

    def get_filecontent_from_task(
        self, job_id, task_id, filename, as_chunk=False
    ):
        """Get file content from a completed local task."""
        # For local runner, we can read directly from the work directory
        job_dir = self.work_dir / job_id / task_id
        file_path = job_dir / filename

        # Also check outputs/ subdirectory where prepare_imagery writes files
        if not file_path.exists():
            outputs_file_path = job_dir / "outputs" / filename
            if outputs_file_path.exists():
                file_path = outputs_file_path

        if file_path.exists():
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
                with open(file_path, "r") as f:
                    return f.read()
        else:
            self.logger.warning(
                f"File {filename} not found for job {job_id}, task {task_id}"
            )
            return None

    def get_task_status(self, job_id, task_id):
        """Get the status of a task."""
        # For local runner, tasks are synchronous, so they're either running or completed
        job_dir = self.work_dir / job_id / task_id
        if job_dir.exists():
            status_file = job_dir / "status.json"
            if status_file.exists():
                with open(status_file, "r") as f:
                    status_data = json.load(f)
                    # Map internal state to expected status format
                    if (
                        status_data.get("state") == "completed"
                        and status_data.get("exit_code") == 0
                    ):
                        return self.config.get_status_types().COMPLETED.value
                    elif (
                        status_data.get("state") == "failed"
                        or status_data.get("exit_code", 0) != 0
                    ):
                        return self.config.get_status_types().FAILED.value
                    elif status_data.get("state") == "cancelled":
                        return self.config.get_status_types().FAILED.value
                    else:
                        return self.config.get_status_types().IN_PROGRESS.value
            else:
                # No status file means completed successfully (old behavior)
                return self.config.get_status_types().COMPLETED.value
        else:
            # Task directory doesn't exist - task not found or not started
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
        **kwargs,
    ):
        """Add and execute a task locally using Docker."""

        self.logger.info(
            "[PIPELINE-TRACE] ========== LocalRunner.add_task ENTRY =========="
        )
        self.logger.info(
            f"[PIPELINE-TRACE] Input params: image_name={image_name}, command={command}"
        )
        self.logger.info(f"[PIPELINE-TRACE] Arguments: {arguments}")
        self.logger.info(
            f"[PIPELINE-TRACE] Resource files: {list(resource_files_for_upload.keys()) if resource_files_for_upload else 'None'}"
        )

        if job_id is None:
            job_id = f"job-{uuid.uuid4().hex[:8]}"
        if task_id is None:
            task_id = f"task-{uuid.uuid4().hex[:8]}"

        self.logger.info(
            f"[PIPELINE-TRACE] Generated job_id={job_id}, task_id={task_id}"
        )

        # Create task directory
        task_dir = self.work_dir / job_id / task_id
        self.logger.info(
            f"[PIPELINE-TRACE] Creating task directory: {task_dir}"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        task_dir.chmod(0o777)
        self.logger.info(
            "[PIPELINE-TRACE] Task directory created successfully"
        )

        if output_container_url is None:
            container_name = None
            if getattr(self.config, "artifact_storage_config", None):
                container_name = self.config.artifact_storage_config.get(
                    "container"
                )
            if not container_name and getattr(
                self.config, "storage_config", None
            ):
                container_name = self.config.storage_config.get("container")
            if not container_name:
                container_name = "data"
            output_container_url = container_name
            self.logger.info(
                f"[PIPELINE-TRACE] Derived output_container_url={output_container_url}"
            )

        # Download resource files if specified
        if resource_files_for_upload:
            self.logger.info(
                "[PIPELINE-TRACE] Starting resource file download..."
            )
            self.logger.info(
                f"[PIPELINE-TRACE] Resource files to download: {resource_files_for_upload}"
            )
            self._download_resource_files(task_dir, resource_files_for_upload)
            self.logger.info(
                "[PIPELINE-TRACE] Resource file download completed"
            )

            # Make all downloaded files writable by the training container user
            for _p in task_dir.rglob("*"):
                try:
                    _p.chmod(0o777)
                except Exception as chmod_err:
                    self.logger.debug(
                        f"chmod failed for {_p}: {chmod_err}"
                    )

            # Force filesystem sync and verify files exist before starting container
            os.sync()
            time.sleep(1)  # Brief pause to ensure filesystem is consistent

            # Verify downloaded files are visible
            inputs_dir = task_dir / "inputs"
            if inputs_dir.exists():
                all_files = list(inputs_dir.rglob("*"))
                self.logger.info(
                    f"[ZIP-DEBUG] After download sync: {len(all_files)} items in {inputs_dir}"
                )
                # Show first few items
                for f in all_files[:5]:
                    self.logger.info(f"[ZIP-DEBUG] Found: {f}")
            else:
                self.logger.warning(
                    "[ZIP-DEBUG] inputs directory does not exist after download!"
                )
        else:
            self.logger.info("[PIPELINE-TRACE] No resource files to download")

        try:
            self.logger.info(
                "[PIPELINE-TRACE] ========== DOCKER CONTAINER SETUP =========="
            )

            # Set up task environment and working directory
            container_working_dir = work_dir or "/app/data"
            self.logger.info(
                f"[PIPELINE-TRACE] Initial container_working_dir: {container_working_dir}"
            )

            # Set up volumes first to determine the correct working directory
            relative_task_path = str(task_dir).replace("/shared/azurite/", "")
            self.logger.info(
                f"[PIPELINE-TRACE] Relative task path: {relative_task_path}"
            )

            volumes = {}

            # Mount the azurite volume - this contains both blob storage AND task_work
            # Volume name depends on docker-compose project name (directory name)
            azurite_volume_name = os.getenv(
                "HASTE_DOCKER_AZURITE_VOLUME", "docker_azurite-data"
            )
            volumes[azurite_volume_name] = {
                "bind": "/shared/azurite",
                "mode": "rw",
            }
            self.logger.info(
                f"[PIPELINE-TRACE] Using azurite volume: {azurite_volume_name}"
            )

            # Container working dir points directly to the task directory in the volume
            container_working_dir = f"/shared/azurite/{relative_task_path}"

            self.logger.info(
                f"[PIPELINE-TRACE] Final container_working_dir: {container_working_dir}"
            )

            task_env = {
                "AZ_BATCH_TASK_WORKING_DIR": container_working_dir,
                "AZ_BATCH_JOB_ID": job_id,
                "AZ_BATCH_TASK_ID": task_id,
            }
            self.logger.info(
                f"[PIPELINE-TRACE] Base task environment created: {task_env}"
            )
            task_env.setdefault("DATA_PATH", container_working_dir)

            # Pass through verbose flag so workflow scripts can emit TRACE logs
            if self.verbose:
                task_env["HASTE_DEBUG_VERBOSE"] = "1"
                self.logger.info(
                    "[PIPELINE-TRACE] Added verbose debug flag to environment"
                )

            dataloader_workers = os.getenv("HASTE_DATALOADER_WORKERS")
            if dataloader_workers:
                task_env["HASTE_DATALOADER_WORKERS"] = dataloader_workers

            self.logger.info(
                "[PIPELINE-TRACE] ========== STORAGE CONFIG SETUP =========="
            )
            # Add storage configuration for azurite connectivity
            if self.config and hasattr(self.config, "storage_config"):
                storage_config = self.config.storage_config
                self.logger.info(
                    f"[PIPELINE-TRACE] Found storage_config: {storage_config}"
                )

                if "connection_string" in storage_config:
                    # Pass the connection string so spawned containers can connect to azurite
                    task_env[
                        "AZURE_STORAGE_CONNECTION_STRING"
                    ] = storage_config["connection_string"]
                    task_env["BLOB_CONNECTION_STRING"] = storage_config[
                        "connection_string"
                    ]
                    task_env.setdefault(
                        "AzureWebJobsStorage",
                        storage_config["connection_string"],
                    )
                    self.logger.info(
                        "[PIPELINE-TRACE] Added Azure storage connection string to environment"
                    )

                    # Also add individual storage account components for different tools
                    task_env["STORAGE_ACCOUNT_NAME"] = "devstoreaccount1"
                    task_env[
                        "STORAGE_ACCOUNT_KEY"
                    ] = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="  # pragma: allowlist secret
                    storage_account_url = _normalize_azurite_url(
                        storage_config.get(
                            "account_url",
                            "http://azurite:10000/devstoreaccount1",
                        )
                    )
                    task_env["STORAGE_ACCOUNT_URL"] = storage_account_url
                    task_env["BLOB_ACCOUNT_URL"] = storage_account_url
                    if "container" in storage_config:
                        task_env["BLOB_CONTAINER"] = storage_config[
                            "container"
                        ]
                    self.logger.info(
                        "[PIPELINE-TRACE] Added individual storage account components"
                    )
                else:
                    self.logger.info(
                        "[PIPELINE-TRACE] No connection_string found in storage_config"
                    )
            else:
                self.logger.info(
                    f"[PIPELINE-TRACE] No storage_config found - config exists: {self.config is not None}"
                )

            if env_vars:
                self.logger.info(
                    f"[PIPELINE-TRACE] Adding custom env vars: {env_vars}"
                )
                task_env.update(env_vars)

            if self.config:
                task_env.setdefault(
                    "METADATA_STORAGE_TYPE", self.config.storage_type
                )
                task_env.setdefault(
                    "ARTIFACT_STORAGE_TYPE",
                    self.config.artifact_storage_type,
                )
                image_storage_type = os.getenv(
                    "IMAGERY_STORAGE_TYPE",
                    self.config.artifact_storage_type,
                )
                task_env.setdefault("IMAGERY_STORAGE_TYPE", image_storage_type)
                queue_cfg = getattr(self.config, "queue_config", {}) or {}
                queue_account_url = _normalize_azurite_url(
                    queue_cfg.get(
                        "queue_account_url",
                        "http://azurite:10001/devstoreaccount1",
                    )
                )
                task_env.setdefault("QUEUE_ACCOUNT_URL", queue_account_url)
                for key in (
                    "image_queue_name",
                    "train_queue_name",
                    "stats_queue_name",
                    "zip_queue_name",
                    "inference_queue_name",
                ):
                    if key in queue_cfg:
                        task_env.setdefault(key.upper(), queue_cfg[key])

            self.logger.info(
                f"[PIPELINE-TRACE] Final task environment: {task_env}"
            )
            self.logger.info(
                "[PIPELINE-TRACE] ========== CONTAINER IMAGE MAPPING =========="
            )

            # Determine container image - map ACR images to local ones
            if image_name in self.container_images:
                container_image = self.container_images[image_name]
                self.logger.info(
                    f"[PIPELINE-TRACE] Mapped image '{image_name}' to '{container_image}'"
                )
            else:
                container_image = image_name or self.container_images.get(
                    "training", "haste-training"
                )
                self.logger.info(
                    f"[PIPELINE-TRACE] Using direct/fallback image: '{container_image}'"
                )

            self.logger.info(
                "[PIPELINE-TRACE] ========== COMMAND PREPARATION =========="
            )
            # Prepare command - replace Azure Batch environment variables
            container_command = command
            self.logger.info(f"[PIPELINE-TRACE] Original command: {command}")
            self.logger.info(
                f"[PIPELINE-TRACE] Original arguments: {arguments}"
            )

            if arguments:
                if isinstance(arguments, list):
                    container_command = (
                        command + arguments if command else arguments
                    )
                    self.logger.info(
                        f"[PIPELINE-TRACE] Combined command+arguments (list): {container_command}"
                    )
                else:
                    container_command = (
                        f"{command} {arguments}" if command else arguments
                    )
                    self.logger.info(
                        f"[PIPELINE-TRACE] Combined command+arguments (string): {container_command}"
                    )

            # Replace Azure Batch environment variables in the command
            self.logger.info(
                "[PIPELINE-TRACE] Replacing environment variables in command..."
            )
            if isinstance(container_command, str):
                orig_command = container_command
                container_command = container_command.replace(
                    "$AZ_BATCH_TASK_WORKING_DIR", container_working_dir
                )
                container_command = container_command.replace(
                    "${AZ_BATCH_TASK_WORKING_DIR}", container_working_dir
                )
                container_command = container_command.replace(
                    "$BATCH_JOB_WORKDIR", container_working_dir
                )
                container_command = container_command.replace(
                    "${BATCH_JOB_WORKDIR}", container_working_dir
                )
                container_command = container_command.replace(
                    "$AZ_BATCH_JOB_ID", job_id
                )
                container_command = container_command.replace(
                    "${AZ_BATCH_JOB_ID}", job_id
                )
                container_command = container_command.replace(
                    "$AZ_BATCH_TASK_ID", task_id
                )
                container_command = container_command.replace(
                    "${AZ_BATCH_TASK_ID}", task_id
                )
                self.logger.info(
                    f"[PIPELINE-TRACE] Env var replacement: '{orig_command}' -> '{container_command}'"
                )
            elif isinstance(container_command, list):
                orig_command = container_command[:]
                container_command = [
                    arg.replace(
                        "$AZ_BATCH_TASK_WORKING_DIR", container_working_dir
                    )
                    .replace(
                        "${AZ_BATCH_TASK_WORKING_DIR}", container_working_dir
                    )
                    .replace("$BATCH_JOB_WORKDIR", container_working_dir)
                    .replace("${BATCH_JOB_WORKDIR}", container_working_dir)
                    .replace("$AZ_BATCH_JOB_ID", job_id)
                    .replace("${AZ_BATCH_JOB_ID}", job_id)
                    .replace("$AZ_BATCH_TASK_ID", task_id)
                    .replace("${AZ_BATCH_TASK_ID}", task_id)
                    for arg in container_command
                ]
                self.logger.info(
                    f"[PIPELINE-TRACE] Env var replacement (list): {orig_command} -> {container_command}"
                )

            self.logger.info(
                "[PIPELINE-TRACE] ========== CONTAINER EXECUTION SETUP =========="
            )
            self.logger.info(
                f"[PIPELINE-TRACE] Container image: {container_image}"
            )
            self.logger.info(
                f"[PIPELINE-TRACE] Working directory: {container_working_dir}"
            )
            self.logger.info(f"[PIPELINE-TRACE] Volume mounts: {volumes}")
            self.logger.info(
                f"[PIPELINE-TRACE] Environment vars count: {len(task_env)}"
            )

            # For containers with bash entrypoint (like haste containers),
            # ensure the command is always a single string
            if container_image.startswith("haste-"):
                self.logger.info(
                    "[PIPELINE-TRACE] Processing haste container command format..."
                )

                if isinstance(container_command, list):
                    if (
                        len(container_command) == 3
                        and container_command[0] == "/bin/bash"
                        and container_command[1] == "-c"
                    ):
                        # Extract the actual command from ["/bin/bash", "-c", "command"]
                        container_command = container_command[2]
                        self.logger.info(
                            f"[PIPELINE-TRACE] Extracted bash -c command: {container_command}"
                        )
                    else:
                        # Convert list to string for bash entrypoint
                        container_command = " ".join(
                            str(arg) for arg in container_command
                        )
                        self.logger.info(
                            f"[PIPELINE-TRACE] Converted list to string: {container_command}"
                        )

                # Inject a diagnostic preamble when verbose to ensure we get some stdout even on early failures
                # Temporarily disabled to avoid command parsing issues
                # if self.verbose and isinstance(container_command, str):
                #     diag_preamble = "echo [CONTAINER-DIAG] Container started && date && pwd && ls -al && echo [CONTAINER-DIAG] Python version && python -c \"import sys; print(sys.version)\" && echo [CONTAINER-DIAG] Environment check && env | grep -E \"(HASTE|AZ_BATCH|STORAGE)\" && echo [CONTAINER-DIAG] Starting actual command &&"
                #     container_command = f"{diag_preamble} {container_command}"
                #     self.logger.info(f"[PIPELINE-TRACE] Added diagnostic preamble to command")
            else:
                self.logger.info(
                    "[PIPELINE-TRACE] Processing non-haste container command format..."
                )
                # For non-bash entrypoint containers, handle complex shell commands
                if isinstance(container_command, str) and (
                    "&&" in container_command
                    or "$" in container_command
                    or "|" in container_command
                ):
                    # Complex shell command - run through bash
                    container_command = ["/bin/bash", "-c", container_command]
                    self.logger.info(
                        f"[PIPELINE-TRACE] Wrapped complex command in bash: {container_command}"
                    )

            self.logger.info(
                f"[PIPELINE-TRACE] FINAL container command: {repr(container_command)}"
            )

            # Run the container
            start_time = time.time()
            output_file_path = task_dir / "output.log"
            result_preview_bytes = bytearray()
            try:
                self.logger.info(
                    f"BEFORE DOCKER RUN - Image: {container_image}, Command: {repr(container_command)}"
                )
                # Persist the resolved command for debugging
                try:
                    with open(task_dir / "resolved_command.txt", "w") as fc:
                        fc.write(str(container_command))
                except Exception as e:
                    self.logger.warning(
                        f"Failed writing resolved_command.txt: {e}"
                    )
                # Use detach=True to get the container object so we can check exit code
                # Configure GPU access if requested via environment variables
                device_requests = None
                if os.getenv("HASTE_ENABLE_GPU", "0").lower() in {
                    "1",
                    "true",
                    "yes",
                }:
                    try:
                        gpu_devices = (
                            os.getenv("HASTE_GPU_DEVICES", "all")
                            .strip()
                            .lower()
                        )
                        request_kwargs: Dict[str, Any] = {
                            "capabilities": [["gpu"]]
                        }
                        visible_devices = None

                        if gpu_devices and gpu_devices != "all":
                            device_ids = [
                                d.strip()
                                for d in gpu_devices.split(",")
                                if d.strip()
                            ]
                            if device_ids:
                                request_kwargs["device_ids"] = device_ids
                                request_kwargs["count"] = len(device_ids)
                                visible_devices = ",".join(device_ids)
                            else:
                                request_kwargs["count"] = -1
                        else:
                            request_kwargs["count"] = -1

                        device_requests = [DeviceRequest(**request_kwargs)]
                        if visible_devices:
                            task_env.setdefault(
                                "CUDA_VISIBLE_DEVICES", visible_devices
                            )
                            task_env.setdefault(
                                "NVIDIA_VISIBLE_DEVICES", visible_devices
                            )

                        self.logger.info(
                            f"[PIPELINE-TRACE] GPU device request configured: {request_kwargs}"
                        )
                    except Exception as gpu_err:
                        device_requests = None
                        self.logger.error(
                            f"Failed to configure GPU device request, continuing without GPU: {gpu_err}"
                        )

                container = self.docker_client.containers.run(
                    container_image,
                    command=container_command,
                    environment=task_env,
                    volumes=volumes,
                    working_dir=container_working_dir,
                    device_requests=device_requests,
                    shm_size=os.getenv("HASTE_DOCKER_SHM_SIZE", "8g"),
                    mem_limit=os.getenv("HASTE_DOCKER_MEM_LIMIT", "32g"),
                    network=os.getenv(
                        "HASTE_DOCKER_NETWORK", "docker_default"
                    ),  # Connect to docker-compose network for azurite access
                    remove=False,  # Keep for inspection (we'll decide after)
                    detach=True,
                    stdout=True,
                    stderr=True,
                )

                # Stream container logs to disk for parity with Azure Batch outputs
                try:
                    with open(output_file_path, "wb") as log_fp:
                        for chunk in container.logs(
                            stream=True,
                            stdout=True,
                            stderr=True,
                            follow=True,
                        ):
                            if not chunk:
                                continue
                            log_fp.write(chunk)
                            log_fp.flush()
                            if len(result_preview_bytes) < 512:
                                remaining = 512 - len(result_preview_bytes)
                                result_preview_bytes.extend(chunk[:remaining])
                except Exception as log_err:
                    self.logger.warning(
                        f"Failed streaming container logs; falling back to single fetch: {log_err}"  # noqa: E702
                    )
                    fallback_logs = container.logs(stdout=True, stderr=True)
                    with open(output_file_path, "ab") as log_fp:
                        if isinstance(fallback_logs, bytes):
                            log_fp.write(fallback_logs)
                            result_preview_bytes = bytearray(
                                fallback_logs[:512]
                            )
                        else:
                            log_str = str(fallback_logs)
                            log_fp.write(log_str.encode())
                            result_preview_bytes = bytearray(
                                log_str.encode()[:512]
                            )

                # Wait for container to finish and get result
                container_result = container.wait()
                exit_code = container_result["StatusCode"]

                # Only auto-remove container if CLEANUP_CONTAINERS not disabled
                if os.getenv("CLEANUP_CONTAINERS", "1") == "1":
                    try:
                        container.remove()
                    except Exception as e:
                        self.logger.warning(
                            f"Failed removing container {container.id}: {e}"
                        )

                end_time = time.time()
                duration = end_time - start_time

                if exit_code == 0:
                    state = "completed"
                    self.logger.info(
                        f"Container completed successfully in {duration:.2f} seconds with exit code {exit_code}"
                    )
                else:
                    state = "failed"
                    self.logger.error(
                        f"Container failed in {duration:.2f} seconds with exit code {exit_code}"
                    )

                preview_text = (
                    bytes(result_preview_bytes).decode(
                        "utf-8", errors="replace"
                    )
                    if result_preview_bytes
                    else "No output"
                )
                self.logger.info(
                    f"Container output preview (first 500 chars): {preview_text[:500]}"
                )

                # Post-run validation for imagery preprocessing tasks: ensure manifest present
                try:
                    output_log_path = task_dir / "output.log"
                    empty_log = (
                        output_log_path.exists()
                        and os.path.getsize(output_log_path) == 0
                    )
                    is_imagery = (
                        isinstance(container_command, str)
                        and "prepare_imagery" in container_command
                    )
                    # Manifest is created in outputs/ subdirectory by prepare_imagery workflow
                    manifest_path = (
                        task_dir / "outputs" / "imagery_manifest.json"
                    )

                    # Rule 1: Any task that reports success but produced an empty log is suspicious -> fail
                    if exit_code == 0 and empty_log:
                        base_msg = (
                            "Task reported success but output.log is empty"
                        )
                        if self.fail_on_empty_logs:
                            self.logger.error(
                                f"{base_msg}; marking failed"  # noqa: E702
                            )
                        else:
                            self.logger.warning(
                                f"{base_msg}; continuing per configuration"  # noqa: E702
                            )
                        if not (task_dir / "no_logs.debug").exists():
                            with open(task_dir / "no_logs.debug", "w") as f:
                                f.write(
                                    f"Empty output.log detected. Command: {container_command}\n"
                                )
                        if self.fail_on_empty_logs:
                            state = "failed"
                            exit_code = 12

                    # Rule 2 (imagery specific): Missing manifest is failure even if log not empty
                    if (
                        exit_code == 0
                        and is_imagery
                        and not manifest_path.exists()
                    ):
                        self.logger.error(
                            "Imagery task reported success but manifest missing; marking failed"
                        )
                        file_list = [p.name for p in task_dir.iterdir()]
                        diagnostics = {
                            "reason": "manifest_missing",
                            "files_present": file_list,
                            "config_present": (
                                task_dir / "config.json"
                            ).exists(),
                            "output_log_size": os.path.getsize(output_log_path)
                            if output_log_path.exists()
                            else -1,
                            "command": container_command,
                        }
                        with open(
                            task_dir / "manifest_missing.debug.json", "w"
                        ) as fdiag:
                            json.dump(diagnostics, fdiag, indent=2)
                        state = "failed"
                        # Preserve previous override if we already marked for empty log; otherwise set
                        if exit_code == 0:
                            exit_code = 11
                except Exception as e:
                    self.logger.error(f"Post-run validation failed: {e}")

            except docker.errors.ContainerError as e:
                end_time = time.time()
                exit_code = e.exit_status
                state = "failed"
                error_output = e.stderr if e.stderr else str(e)
                with open(output_file_path, "wb") as log_fp:
                    if isinstance(error_output, bytes):
                        log_fp.write(error_output)
                        result_preview_bytes = bytearray(error_output[:512])
                    else:
                        log_fp.write(str(error_output).encode())
                        result_preview_bytes = bytearray(
                            str(error_output).encode()[:512]
                        )
                self.logger.error(
                    f"Container failed with exit code {exit_code}: {error_output}"
                )
            except Exception as e:
                end_time = time.time()
                exit_code = 1
                state = "failed"
                error_message = str(e)
                with open(output_file_path, "wb") as log_fp:
                    log_fp.write(error_message.encode())
                result_preview_bytes = bytearray(error_message.encode()[:512])
                self.logger.error(
                    f"Unexpected error running container: {error_message}"
                )

            # Save task status
            status_data = {
                "state": state,
                "exit_code": exit_code,
                "start_time": start_time,
                "end_time": end_time,
                "job_id": job_id,
                "task_id": task_id,
            }

            status_file = task_dir / "status.json"
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)

            self.logger.info(f"Task {task_id} completed successfully")

            # Upload ALL task files to blob storage for full traceability
            # This includes inputs, outputs, logs, status files, everything
            if output_container_url:
                self.logger.info(
                    "[PIPELINE-TRACE] Uploading all task files to blob storage for traceability"
                )
                self._upload_all_task_files(
                    task_dir,
                    output_container_url,
                    output_prefix,
                )

            return job_id, task_id

        except docker.errors.ContainerError as e:
            self.logger.error(f"Container execution failed: {e}")
            # Save error status
            status_data = {
                "state": "failed",
                "exit_code": e.exit_status,
                "error": str(e),
                "start_time": time.time(),
                "end_time": time.time(),
                "job_id": job_id,
                "task_id": task_id,
            }

            status_file = task_dir / "status.json"
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)

            raise
        except Exception as e:
            self.logger.error(f"Task execution failed: {e}")
            # Save error status
            status_data = {
                "state": "failed",
                "exit_code": -1,
                "error": str(e),
                "start_time": time.time(),
                "end_time": time.time(),
                "job_id": job_id,
                "task_id": task_id,
            }

            status_file = task_dir / "status.json"
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)

            raise

    def cleanup_task(self, job_id, task_id):
        """Clean up local task files."""
        if os.getenv("PRESERVE_LOCAL_TASK_DIRS", "0") == "1":
            self.logger.info(
                "Skipping task directory cleanup because PRESERVE_LOCAL_TASK_DIRS is set"
            )
            return
        task_dir = self.work_dir / job_id / task_id
        if task_dir.exists():
            try:
                shutil.rmtree(task_dir)
                self.logger.info(f"Cleaned up task directory: {task_dir}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to cleanup task directory {task_dir}: {e}"
                )

        # Check if job directory is empty and remove it
        job_dir = self.work_dir / job_id
        if job_dir.exists() and not any(job_dir.iterdir()):
            try:
                job_dir.rmdir()
                self.logger.info(f"Cleaned up empty job directory: {job_dir}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to cleanup job directory {job_dir}: {e}"
                )

    def cancel_task(self, job_id, task_id):
        """Cancel a running task (for local runner, tasks are synchronous so this is a no-op)."""
        self.logger.info(
            f"Cancel requested for task {task_id} in job {job_id}"
        )
        # Since local tasks run synchronously, we can't really cancel them
        # but we can mark them as cancelled
        task_dir = self.work_dir / job_id / task_id
        if task_dir.exists():
            status_file = task_dir / "status.json"
            status_data = {
                "state": "cancelled",
                "exit_code": -2,
                "cancelled_time": time.time(),
                "job_id": job_id,
                "task_id": task_id,
            }
            with open(status_file, "w") as f:
                json.dump(status_data, f, indent=2)

        return True

    def _download_blob_data(self, blob_path: str, local_dir: Path):
        """Download data from blob storage to local directory."""
        if not blob_path or not self.blob_client:
            return

        try:
            # Parse blob path (format: container/blob/path)
            parts = blob_path.split("/", 1)
            if len(parts) != 2:
                self.logger.warning(f"Invalid blob path format: {blob_path}")
                return

            container_name, blob_name = parts
            blob_client = self.blob_client.get_blob_client(
                container_name, blob_name
            )

            local_file = local_dir / Path(blob_name).name
            local_file.parent.mkdir(parents=True, exist_ok=True)

            with open(local_file, "wb") as f:
                blob_data = blob_client.download_blob()
                blob_data.readinto(f)

            self.logger.info(f"Downloaded {blob_path} to {local_file}")
        except Exception as e:
            self.logger.error(f"Failed to download blob {blob_path}: {e}")

    def _build_blob_client_candidates(self, blob_url: str):
        candidates = []

        if not self.blob_client or not blob_url:
            return candidates

        credential = getattr(self.blob_client, "credential", None)

        # Prefer direct URL when it is reachable (covers real Azure accounts)
        try:
            if credential is not None:
                candidates.append(
                    BlobClient.from_blob_url(blob_url, credential=credential)
                )
            else:
                candidates.append(BlobClient.from_blob_url(blob_url))
        except Exception as blob_url_err:
            self.logger.debug(
                f"BlobClient.from_blob_url failed; will try fallbacks: {blob_url_err}"
            )

        parsed = urlparse(blob_url)
        path_parts = [part for part in parsed.path.split("/") if part]

        # Reject path traversal and null bytes before joining segments into
        # a blob name. The Azure SDK likely rejects these too, but we should
        # not rely on undocumented downstream behavior.
        if any(part == ".." or "\x00" in part for part in path_parts):
            self.logger.warning(
                f"Rejecting blob URL with unsafe path segments: {blob_url}"
            )
            return candidates

        account_name = getattr(self.blob_client, "account_name", None)
        if (
            account_name
            and path_parts
            and path_parts[0].lower() == account_name.lower()
        ):
            path_parts = path_parts[1:]

        if path_parts:
            container_name = path_parts[0]
            blob_name = "/".join(path_parts[1:])

            if container_name and blob_name:
                try:
                    candidates.append(
                        self.blob_client.get_blob_client(
                            container_name, blob_name
                        )
                    )
                except Exception as bc_err:
                    self.logger.debug(
                        f"get_blob_client failed for {container_name}/{blob_name}: {bc_err}"
                    )

        return candidates

    def _download_resource_files(self, task_dir: Path, resource_files: dict):
        """Download resource files from blob storage to local task directory."""
        try:
            for file_key, file_info in resource_files.items():
                if not isinstance(file_info, dict):
                    continue

                if "http_url" in file_info and "file_path" in file_info:
                    blob_url = file_info.get("http_url")
                    target_rel_path = file_info.get("file_path")

                    if not blob_url or not target_rel_path:
                        self.logger.warning(
                            f"Skipping resource '{file_key}' due to missing URL or file path"
                        )
                        continue

                    if not self.blob_client:
                        self.logger.warning(
                            "No blob client available for downloading resource files"
                        )
                        continue

                    local_file_path = task_dir / target_rel_path
                    local_file_path.parent.mkdir(parents=True, exist_ok=True)

                    download_succeeded = False
                    last_error = None

                    for candidate in self._build_blob_client_candidates(
                        blob_url
                    ):
                        try:
                            with open(local_file_path, "wb") as f:
                                blob_data = candidate.download_blob()
                                blob_data.readinto(f)
                            download_succeeded = True
                            break
                        except Exception as download_err:
                            last_error = download_err
                            if local_file_path.exists():
                                try:
                                    local_file_path.unlink()
                                except Exception as unlink_err:
                                    self.logger.debug(
                                        f"Failed to clean up partial download {local_file_path}: {unlink_err}"
                                    )

                    if download_succeeded:
                        self.logger.info(
                            f"Downloaded resource '{file_key}' to {local_file_path}"
                        )
                    else:
                        self.logger.error(
                            f"Failed to download resource '{file_key}' from {blob_url}: {last_error}"
                        )
                    continue

                if (
                    "storage_container_url" in file_info
                    and "blob_prefix" in file_info
                    and "file_path" in file_info
                ):
                    if not self.blob_client:
                        self.logger.warning(
                            "No blob client available for downloading resource files"
                        )
                        continue

                    container_url = file_info.get("storage_container_url")
                    blob_prefix = (file_info.get("blob_prefix") or "").lstrip(
                        "/"
                    )
                    target_rel_path = file_info.get("file_path") or ""

                    if not container_url or not blob_prefix:
                        self.logger.warning(
                            f"Skipping resource '{file_key}' due to missing container URL or blob prefix"
                        )
                        continue

                    parsed_url = urlparse(container_url)
                    path_parts = [p for p in parsed_url.path.split("/") if p]
                    container_name = path_parts[-1] if path_parts else None

                    if not container_name:
                        self.logger.warning(
                            f"Skipping resource '{file_key}' due to unresolved container name"
                        )
                        continue

                    dest_root = task_dir / target_rel_path
                    dest_root.mkdir(parents=True, exist_ok=True)

                    try:
                        container_client = (
                            self.blob_client.get_container_client(
                                container_name
                            )
                        )
                        blob_count = 0
                        for blob in container_client.list_blobs(
                            name_starts_with=blob_prefix
                        ):
                            blob_count += 1
                            # For local runs, preserve the full blob path structure
                            # so that INPUT_DIR (which includes the hash prefix) works correctly
                            local_blob_path = dest_root / blob.name
                            if blob_count <= 3:
                                self.logger.info(
                                    f"[ZIP-DEBUG] blob.name={blob.name}, dest_root={dest_root}, local_blob_path={local_blob_path}"
                                )
                            local_blob_path.parent.mkdir(
                                parents=True, exist_ok=True
                            )
                            with open(local_blob_path, "wb") as f:
                                container_client.download_blob(
                                    blob.name
                                ).readinto(f)
                        self.logger.info(
                            f"[ZIP-DEBUG] Downloaded {blob_count} blobs from {blob_prefix}"
                        )
                        self.logger.info(
                            f"Synced resource '{file_key}' from prefix {blob_prefix} to {dest_root}"
                        )
                    except Exception as download_err:
                        self.logger.error(
                            f"Failed to download resource '{file_key}' from prefix {blob_prefix}: {download_err}"
                        )
        except Exception as e:
            self.logger.error(f"Failed to download resource files: {e}")

    def _upload_blob_data(self, local_dir: Path, blob_path: str):
        """Upload data from local directory to blob storage."""
        if not blob_path or not self.blob_client:
            return

        try:
            # Parse blob path
            parts = blob_path.split("/", 1)
            if len(parts) != 2:
                self.logger.warning(f"Invalid blob path format: {blob_path}")
                return

            container_name, blob_prefix = parts
            container_client = self.blob_client.get_container_client(
                container_name
            )

            # Upload all files in the directory
            for file_path in local_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(local_dir)
                    blob_name = f"{blob_prefix}/{relative_path}".replace(
                        "\\", "/"
                    )
                    blob_client = container_client.get_blob_client(blob_name)

                    with open(file_path, "rb") as f:
                        blob_client.upload_blob(f, overwrite=True)

                    self.logger.info(
                        f"Uploaded {file_path} to {container_name}/{blob_name}"
                    )
        except Exception as e:
            self.logger.error(f"Failed to upload to blob {blob_path}: {e}")

    def _upload_all_task_files(
        self,
        task_dir: Path,
        output_container_url: str,
        output_prefix: str,
    ):
        """Upload ALL task files to blob storage for full traceability.
        This includes inputs, outputs, logs, config files, everything."""
        if not self.blob_client:
            self.logger.warning(
                "No blob client available for uploading task files"
            )
            return

        try:
            container_name = output_container_url.split("/")[-1]
            uploaded_count = 0

            # Upload every file in the task directory
            for file_path in task_dir.rglob("*"):
                if file_path.is_file():
                    # Create blob path maintaining the full directory structure
                    relative_path = file_path.relative_to(task_dir)

                    if (
                        relative_path.parts
                        and relative_path.parts[0] == "outputs"
                        and len(relative_path.parts) > 1
                    ):
                        relative_path = Path(*relative_path.parts[1:])

                    blob_path = (
                        f"{output_prefix}/{relative_path}"
                        if output_prefix
                        else str(relative_path)
                    )
                    blob_path = blob_path.replace("\\", "/")

                    try:
                        blob_client = self.blob_client.get_blob_client(
                            container_name, blob_path
                        )

                        with open(file_path, "rb") as f:
                            blob_client.upload_blob(f, overwrite=True)

                        uploaded_count += 1
                        self.logger.info(
                            f"Uploaded {relative_path} to {container_name}/{blob_path}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to upload {relative_path}: {e}"
                        )

            self.logger.info(
                f"[PIPELINE-TRACE] Uploaded {uploaded_count} files to blob storage for task traceability"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to upload task files to blob storage: {e}"
            )

    def _upload_task_outputs(
        self,
        task_dir: Path,
        output_container_url: str,
        output_prefix: str,
        resource_files: list,
        file_pattern: str,
    ):
        """Upload task output files to blob storage."""
        if not self.blob_client:
            return

        try:
            # Simple implementation - upload all files matching pattern
            files_to_upload = []

            if file_pattern:
                normalized_pattern = file_pattern.replace("\\", "/")
                try:
                    files_to_upload = [
                        Path(p)
                        for p in glob.glob(normalized_pattern, recursive=True)
                    ]
                except Exception as e:
                    self.logger.warning(
                        f"Failed globbing output pattern {file_pattern}: {e}. Falling back to task_dir search"
                    )

            if not files_to_upload:
                outputs_dir = task_dir / "outputs"
                if outputs_dir.exists():
                    files_to_upload = list(outputs_dir.rglob("*"))

            if not files_to_upload:
                files_to_upload = list(task_dir.rglob("*"))

            for file_path in files_to_upload:
                if file_path.is_file():
                    # Create blob path
                    relative_path = file_path.relative_to(task_dir)

                    # Mirror Azure Batch behavior by omitting the local
                    # staging folder name (e.g. "outputs/") from the blob path.
                    if (
                        relative_path.parts
                        and relative_path.parts[0] == "outputs"
                    ):
                        relative_path = Path(*relative_path.parts[1:])

                    blob_path = (
                        f"{output_prefix}/{relative_path}"
                        if output_prefix
                        else str(relative_path)
                    )
                    blob_path = blob_path.replace("\\", "/")

                    # Upload to blob storage
                    self._upload_single_file(
                        file_path, output_container_url, blob_path
                    )

        except Exception as e:
            self.logger.error(f"Failed to upload task outputs: {e}")

    def _upload_single_file(
        self, file_path: Path, container_url: str, blob_name: str
    ):
        """Upload a single file to blob storage."""
        try:
            # Extract container name from URL (simple parsing)
            # This is a simplified version - in production you'd want more robust URL parsing
            container_name = container_url.split("/")[-1]

            blob_client = self.blob_client.get_blob_client(
                container_name, blob_name
            )

            with open(file_path, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)

            self.logger.info(
                f"Uploaded {file_path} to {container_name}/{blob_name}"
            )
        except Exception as e:
            self.logger.error(f"Failed to upload file {file_path}: {e}")

    def ensure_docker_images(self):
        """Ensure required Docker images are available."""
        required_images = list(self.container_images.values())
        missing_images = []

        for image in required_images:
            try:
                self.docker_client.images.get(image)
                self.logger.info(f"Docker image {image} is available")
            except docker.errors.ImageNotFound:
                missing_images.append(image)
                self.logger.warning(f"Docker image {image} not found")

        if missing_images:
            self.logger.error(f"Missing Docker images: {missing_images}")
            self.logger.error(
                "Please build the required images using docker-compose"
            )
            return False

        return True
