# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import re
import unicodedata
from typing import List, Optional

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeWorkload,
)
from hastegeo.core.models.projects import Model, ModelArtifacts, ZipJob
from hastegeo.core.utils.compute_jobs import resolve_compute_job_handle
from hastegeo.core.utils.compute_specs import (
    JOB_WORKDIR,
    build_execution_service,
    compute_profile,
    container_ref,
    container_resources,
    folder_input,
    handle_log_fields,
    map_state_to_status,
    new_task_id,
    output_prefix,
    output_uri,
    resolve_backend_preference,
    spec_tags,
    workspace_output,
)
from hastegeo.core.utils.logs import Logger
from hastegeo.core.utils.metadata import MetadataUtils
from hastegeo.core.utils.queues import AzureQueueHandler

ZIP_PREFIX = "zip"
ARTIFACT_WORKLOAD = ComputeWorkload.ARTIFACT_PACKAGING

#: Workspace directory each source artifact folder is staged into. One
#: numbered subdirectory per source (``staged/source-0``, ``source-1``,
#: ...), because the neutral compute contract requires every input to
#: target a distinct destination path. The index — not the task id — names
#: the directory so the staged path never depends on how a backend lays
#: the contents out inside it.
STAGE_DIR = "staged"

#: Workspace directory ``zip_artifacts`` reads (``INPUT_DIR``). It holds one
#: symlink per source task pointing at that task's staged tree, which
#: reproduces exactly the ``<task-id>/...`` layout the packaging workflow
#: classified by ``trn-``/``inf-`` prefix before the migration — so the
#: produced ZIPs keep their existing internal structure.
MERGE_DIR = "merged"

_SLUG_INVALID = re.compile(r"[^A-Za-z0-9._-]+")

#: HASTE artifact prefixes are always ``<project-hash>/<task-id>``, both
#: server-generated. Validated before being placed in a generated command
#: so nothing outside that shape can ever reach a shell string.
_ARTIFACT_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def stage_directory(index: int) -> str:
    """Workspace-relative destination for the ``index``-th source folder."""
    return f"{STAGE_DIR}/source-{index}"


def _link_source_command(index: int, source_path: str) -> str:
    """Shell fragment linking one staged source into ``MERGE_DIR``.

    Backends stage a folder input differently, and both shapes are
    legitimate:

    * Azure Batch and the local Docker adapter preserve the source blob
      prefix, so the contents appear at
      ``staged/source-N/<project-hash>/<task-id>/...``;
    * Azure ML mounts a ``uri_folder`` whose *contents* are the input, so
      the same files appear directly at ``staged/source-N/...``.

    The fragment resolves that at runtime instead of branching on the
    provider: it links the nested ``<project-hash>/<task-id>`` directory
    when that directory exists, and the staged directory itself otherwise.
    The link is always named after the task id, because
    ``hastegeo.workflows.zip_artifacts`` classifies input directories by
    their ``trn-``/``inf-`` prefix and names ZIP entries after them — so
    the archive layout is identical on every backend.

    Written as an explicit ``if``/``else`` rather than
    ``[ -d x ] && ln ... || ln ...``: in the ``&&``/``||`` form a *failed
    link* on a correctly detected nested layout silently falls through to
    linking the flat directory, producing a wrong-but-successful job. Here
    only the directory test chooses the branch, and a failing ``ln``
    remains the fragment's exit status, so the surrounding ``&&`` chain
    stops on it.

    Every interpolated value is either a fixed literal or an already
    validated ``<project-hash>/<task-id>`` prefix
    (``_ARTIFACT_PATH_RE``), never anything client-supplied.
    """
    staged = f"{JOB_WORKDIR}/{stage_directory(index)}"
    nested = f"{staged}/{source_path}"
    link = f"{JOB_WORKDIR}/{MERGE_DIR}/{source_path.split('/')[-1]}"
    return (
        f"if [ -d {nested} ]; "
        f"then ln -sfn {nested} {link}; "
        f"else ln -sfn {staged} {link}; "
        f"fi"
    )


def _slugify_model_name(name: str) -> str:
    """Convert a free-form Model.name into a value safe for blob paths.

    Normalizes unicode (NFKD decomposition + ASCII-only encoding) so that
    accented characters map to their ASCII base letters (e.g. é → e),
    collapses any run of characters outside [A-Za-z0-9._-] into a single
    '-', strips leading/trailing '-._' so paths don't start with a dot
    or hyphen, and falls back to 'model' when the result is empty.
    """
    if not name:
        return "model"
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_INVALID.sub("-", name)
    slug = slug.strip("-._")
    return slug or "model"


def build_artifact_zip_job_spec(
    *,
    model_artifacts: ModelArtifacts,
    execution_id: str,
    source_artifact_paths: List[str],
    artifact_container_url: str,
    training_zip_name: str,
    inference_zip_name: str,
    config: Config,
    backend=None,
) -> ComputeJobSpec:
    """Build the backend-neutral spec for one artifact-packaging job.

    Each source prefix (the training and/or inference output folder) is a
    folder input staged under ``staged/source-N/``; the generated command
    then links each staged tree into ``merged/<task-id>`` and points
    ``INPUT_DIR`` there, so ``hastegeo.workflows.zip_artifacts`` sees the
    same ``trn-``/``inf-``-prefixed directories — and therefore writes the
    same ZIP entries — as before the migration. Two folder inputs cannot
    share one destination directory under the neutral input contract,
    which is why the merge step exists; the link step resolves the two
    legitimate provider staging shapes at runtime (see
    :func:`_link_source_command`) instead of branching on the backend.

    Runs with no accelerator request so the workload stays CPU-target
    capable on every backend (design.md#workload-migration-matrix).
    """
    runtime = config.get_compute_runtime_config(ARTIFACT_WORKLOAD)
    inputs = []
    link_commands = []
    for index, path in enumerate(source_artifact_paths):
        if not _ARTIFACT_PATH_RE.match(path or ""):
            raise ValueError(
                f"artifact source path {path!r} is not a "
                "<project-hash>/<task-id> prefix"
            )
        inputs.append(
            folder_input(
                output_uri(artifact_container_url, path),
                stage_directory(index),
            )
        )
        link_commands.append(_link_source_command(index, path))

    command_parts = [f"mkdir -p {JOB_WORKDIR}/{MERGE_DIR}"]
    command_parts.extend(link_commands)
    command_parts.append("python -m hastegeo.workflows.zip_artifacts")
    command = '"' + " && ".join(command_parts) + '"'

    prefix = output_prefix(model_artifacts.projectId, execution_id)
    return ComputeJobSpec(
        executionId=execution_id,
        workload=ARTIFACT_WORKLOAD,
        backendPreference=resolve_backend_preference(
            requested=backend,
            workload=ARTIFACT_WORKLOAD,
            config=config,
        ),
        container=container_ref(runtime),
        command=command,
        inputs=inputs,
        outputs=[
            workspace_output(
                name="outputs",
                pattern="outputs/*.*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
            )
        ],
        environment={
            "INPUT_DIR": MERGE_DIR,
            "OUTPUT_TRAINING_ZIP_NAME": training_zip_name,
            "OUTPUT_INFERENCE_ZIP_NAME": inference_zip_name,
        },
        resources=container_resources(runtime),
        timeoutSeconds=runtime["timeout_seconds"],
        tags=spec_tags(
            workload=ARTIFACT_WORKLOAD,
            project_id=model_artifacts.projectId,
            task_id=execution_id,
            image_layer_id=model_artifacts.imageLayerId,
            model_id=model_artifacts.modelId,
        ),
    )


class ArtifactProcessor:
    def __init__(
        self,
        partition_key: str = None,
        config: Config = None,
        model: Model = None,
        model_artifacts: ModelArtifacts = None,
        execution_service=None,
    ):
        self.config = config or Config()
        self.storage = UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            partition_key=partition_key,
            **self.config.artifact_storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.queue_client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config["zip_queue_name"],
            self.config.queue_config["queue_account_url"],
        )
        self.model_data = model
        # Injectable so tests can drive the processor with fake adapters.
        self.execution_service = (
            execution_service
            if execution_service is not None
            else build_execution_service(self.config)
        )
        self.model_artifacts = model_artifacts
        if self.model_data is not None:
            safe_name = _slugify_model_name(self.model_data.name)
            self.zip_name = self.config.get_artifact_types().MODEL_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )
            self.training_zip_name = self.config.get_artifact_types().TRAINING_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )
            self.inference_zip_name = self.config.get_artifact_types().INFERENCE_ARTIFACTS_ZIP.value.substitute(
                modelName=safe_name
            )

    def get_download_url(
        self,
        identifier=None,
        artifact_path=None,
        extra_partition_keys=None,
    ):
        """
        Get the download URL for the artifact.
        """
        return self.storage.get_download_url(
            identifier=identifier,
            artifact_path=artifact_path,
            extra_partition_keys=extra_partition_keys,
        )

    def send_to_zip_queue(self):
        """
        Put a message to the queue.
        """
        self.model_artifacts.zipStatus = (
            self.config.get_status_types().PENDING.value
        )
        self.model_artifacts.zipStatusMessage = (
            MetadataUtils.append_status_message("", "Queued for zipping")
        )
        self.model_artifacts.zipUrl = None
        # Mint the task/execution id before queueing and record it on a
        # pending ZipJob so the postprocessor reuses it; a duplicate queue
        # delivery therefore cannot start a second packaging job.
        task_id = new_task_id(ZIP_PREFIX)
        self.model_artifacts.zipJobs.append(
            ZipJob(
                projectId=self.model_artifacts.projectId,
                imageLayerId=self.model_artifacts.imageLayerId,
                modelId=self.model_artifacts.modelId,
                taskId=task_id,
                status=self.config.get_status_types().PENDING.value,
                dstZipPath=output_prefix(
                    self.model_artifacts.projectId, task_id
                ),
                creationDate=MetadataUtils.get_timestamp(),
            )
        )
        self.model_artifacts.currentZipJobUid = task_id
        # Setting visibility timeout to 0 to make sure the message is processed immediately
        self.queue_client.put_message(
            json.dumps(self.model_artifacts.dict()), visibility_timeout=0
        )
        return self.model_artifacts

    # -- compute handle plumbing --------------------------------------

    def _current_zip_job_index(self) -> Optional[int]:
        for idx, zip_job in enumerate(self.model_artifacts.zipJobs):
            if zip_job.taskId == self.model_artifacts.currentZipJobUid:
                return idx
        return None

    def _zip_output_uri(self, task_id: str) -> str:
        runtime = self.config.get_compute_runtime_config(ARTIFACT_WORKLOAD)
        return output_uri(
            runtime["output_container_url"],
            output_prefix(self.model_artifacts.projectId, task_id),
        )

    def _compute_handle(self, zip_job: ZipJob) -> Optional[ComputeJobHandle]:
        return resolve_compute_job_handle(
            zip_job,
            output_uri=(
                self._zip_output_uri(zip_job.taskId)
                if zip_job.taskId
                else None
            ),
        )

    def process_zip(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Processing artifacts for "
            f"model {self.model_artifacts.modelId} with status "
            f"{self.model_artifacts.zipStatus}"
        )

        if (
            self.model_artifacts.zipStatus
            == self.config.get_status_types().PENDING.value
        ):
            self.logger.info(
                f"Zipping artifacts for model {self.model_artifacts.modelId}"
            )
            self._update_zip_progress("Submitting zip task")
            self.model_artifacts = self.submit_zip_job()
        elif (
            self.model_artifacts.zipStatus
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            for idx, zip_job in enumerate(self.model_artifacts.zipJobs):
                if zip_job.taskId == self.model_artifacts.currentZipJobUid:
                    break
            handle = self._compute_handle(self.model_artifacts.zipJobs[idx])
            if handle is None:
                raise ValueError(
                    "Zip job "
                    f"{self.model_artifacts.currentZipJobUid} for model "
                    f"{self.model_artifacts.modelId} has no compute "
                    "submission to poll"
                )
            task_status = map_state_to_status(
                self.execution_service.get_status(handle), self.config
            )

            self.logger.info(
                f"Task status of zip job for model {self.model_artifacts.modelId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self.model_artifacts.zipJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()

                # Read the zip manifest to get individual zip URLs and sizes
                zip_task_id = self.model_artifacts.zipJobs[idx].taskId
                zip_prefix = self.model_artifacts.zipJobs[idx].dstZipPath
                try:
                    manifest_data = self._read_zip_manifest(zip_prefix)
                except Exception as e:
                    self.logger.warning(
                        f"Could not read zip manifest: {e}; "
                        "falling back to combined zip URL"
                    )
                    manifest_data = {}

                if "training_zip" in manifest_data:
                    self.model_artifacts.trainingZipUrl = (
                        self.storage.get_download_url(
                            identifier=manifest_data["training_zip"][
                                "filename"
                            ],
                            extra_partition_keys=zip_task_id,
                        )
                    )
                    self.model_artifacts.trainingZipSize = manifest_data[
                        "training_zip"
                    ]["size_bytes"]

                if "inference_zip" in manifest_data:
                    self.model_artifacts.inferenceZipUrl = (
                        self.storage.get_download_url(
                            identifier=manifest_data["inference_zip"][
                                "filename"
                            ],
                            extra_partition_keys=zip_task_id,
                        )
                    )
                    self.model_artifacts.inferenceZipSize = manifest_data[
                        "inference_zip"
                    ]["size_bytes"]

                # Keep legacy zipUrl pointing at the training zip for
                # backwards compatibility with older UI versions.
                self.model_artifacts.zipUrl = (
                    self.model_artifacts.trainingZipUrl
                    or self.model_artifacts.inferenceZipUrl
                )

                self._update_zip_progress(
                    "Zipping artifacts completed successfully"
                )
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)

            elif task_status in (
                self.config.get_status_types().FAILED.value,
                self.config.get_status_types().CANCELLED.value,
            ):
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self.model_artifacts.zipJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()
                self._update_zip_progress("Zip job failed")
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)
            else:
                self.model_artifacts.zipStatus = task_status
                self.model_artifacts.zipJobs[idx].status = task_status
                self._update_zip_progress("Zipping in progress")
                self.model_artifacts.zipJobs[
                    idx
                ].logs = self.model_artifacts.zipStatusMessage
                self.queue_client.put_message(
                    json.dumps(self.model_artifacts.dict())
                )
        else:
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().FAILED.value
            )
            self.logger.info(
                f"Model {self.model_artifacts.modelId} is not ready for zipping"
            )

        return self.model_artifacts

    def fetch_artifact(
        self,
        identifier: str = None,
        extra_partition_keys: list | str = None,
        src_path: str = None,
        dst_path: str = None,
    ) -> str:
        """
        Download the artifact from the storage.
        """
        return self.storage.fetch_artifact(
            identifier=identifier,
            extra_partition_keys=extra_partition_keys,
            src_path=src_path,
            dst_path=dst_path,
        )

    def store_artifact(
        self,
        artifact_name: str,
        data: str = None,
        src_path: str = None,
        namespace: str | list = None,
    ) -> str:
        """
        Store an artifact in artifact storage.
        """
        return self.storage.store_artifact(
            artifact_name=artifact_name,
            data=data,
            src_path=src_path,
            namespace=namespace,
        )

    def prepare_zip_job(self) -> List[str]:
        """Return the artifact prefixes this packaging job must include."""
        source_artifact_paths: List[str] = []
        if self.model_data.trainingOutputPath:
            source_artifact_paths.append(self.model_data.trainingOutputPath)
        if self.model_data.inferenceOutputPath:
            source_artifact_paths.append(self.model_data.inferenceOutputPath)
        return source_artifact_paths

    def _pending_task_id(self) -> str:
        if self.model_artifacts.currentZipJobUid:
            return self.model_artifacts.currentZipJobUid
        return new_task_id(ZIP_PREFIX)

    def submit_zip_job(self):
        try:
            self.logger.info(
                f"Submitting artifact zipping job for model {self.model_artifacts.modelId}"
            )
            source_artifact_paths = self.prepare_zip_job()
            task_id = self._pending_task_id()
            zip_output_prefix = output_prefix(
                self.model_artifacts.projectId, task_id
            )
            spec = build_artifact_zip_job_spec(
                model_artifacts=self.model_artifacts,
                execution_id=task_id,
                source_artifact_paths=source_artifact_paths,
                artifact_container_url=self.storage.get_base_url(),
                training_zip_name=self.training_zip_name,
                inference_zip_name=self.inference_zip_name,
                config=self.config,
                backend=self.model_artifacts.computeBackend,
            )
            handle = self.execution_service.submit(
                spec, profile=compute_profile(ARTIFACT_WORKLOAD)
            )
            self.logger.info(
                "Artifact packaging submitted for model %s: %s",
                self.model_artifacts.modelId,
                handle_log_fields(handle),
            )
            submitted_job = ZipJob(
                projectId=self.model_artifacts.projectId,
                imageLayerId=self.model_artifacts.imageLayerId,
                modelId=self.model_artifacts.modelId,
                jobId=handle.providerJobId,
                taskId=handle.providerTaskId or handle.executionId,
                status=self.config.get_status_types().IN_PROGRESS.value,
                srcArtifactPaths=source_artifact_paths,
                dstZipPath=zip_output_prefix,
                creationDate=MetadataUtils.get_timestamp(),
                computeJob=handle,
            )
            pending_idx = self._current_zip_job_index()
            if pending_idx is not None:
                submitted_job.creationDate = (
                    self.model_artifacts.zipJobs[pending_idx].creationDate
                    or submitted_job.creationDate
                )
                self.model_artifacts.zipJobs[pending_idx] = submitted_job
            else:
                self.model_artifacts.zipJobs.append(submitted_job)
            self.model_artifacts.currentZipJobUid = submitted_job.taskId
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_zip_progress(
                f"Zipping submitted with task id {submitted_job.taskId}"
            )
            self.queue_client.put_message(
                json.dumps(self.model_artifacts.dict())
            )
            self.logger.info(
                f"InProgress message to queue sent for model {self.model_artifacts.modelId}"
            )
        except Exception as e:
            self.logger.error(
                f"Error processing model {self.model_artifacts.modelId}: {e}",
                stack_info=True,
            )
            self.model_artifacts.zipStatus = (
                self.config.get_status_types().FAILED.value
            )

        return self.model_artifacts

    def _read_zip_manifest(self, zip_prefix: str) -> dict:
        """Read the zip_manifest.json produced by zip_artifacts.py."""
        blob_path = f"{zip_prefix}/zip_manifest.json"
        blob_client = (
            self.storage.artifact_storage.container_client.get_blob_client(
                blob_path
            )
        )
        data = blob_client.download_blob().readall()
        return json.loads(data)

    def _update_zip_progress(self, message: str, timestamp: str = None):
        self.model_artifacts.zipStatusMessage = (
            MetadataUtils.append_status_message(
                self.model_artifacts.zipStatusMessage,
                message,
                timestamp=timestamp,
            )
        )
