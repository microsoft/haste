# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Building-embedding job: queue + execute the MOSAIKS embedding workflow.

Mirrors the imagery preprocessing pipeline (``processors/imagery.py``): a
``Model`` with ``modelType="embedding"`` is the unit of work. The preprocessor
enqueues it; the postprocessor submits a task to the *training* docker image
running ``embed-buildings`` (the workflow module ``embed_buildings.py``), polls
it, and on completion records the embeddings GeoJSON + PMTiles artifact URLs on
the model so the interactive labeler can load them.
"""

import json
import os
from typing import Dict, Optional

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.compute import (
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeWorkload,
    OutputNotAvailableError,
)
from ..models.projects import ImageLayer, Model, TrainingJob
from ..utils.compute_jobs import resolve_compute_job_handle
from ..utils.compute_specs import (
    JOB_WORKDIR,
    build_execution_service,
    compute_profile,
    container_ref,
    container_resources,
    file_input,
    follow_on_backend,
    handle_log_fields,
    map_state_to_status,
    new_task_id,
    output_prefix,
    output_uri,
    resolve_backend_preference,
    spec_tags,
    workspace_output,
)
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler

EMBEDDING_PREFIX = "emb"
EMBEDDING_WORKLOAD = ComputeWorkload.EMBEDDING


def build_embedding_job_spec(
    *,
    model: Model,
    execution_id: str,
    input_files: Dict[str, dict],
    config: Config,
    backend=None,
) -> ComputeJobSpec:
    """Build the backend-neutral spec for one building-embedding job.

    Same training image and ``embed-buildings`` invocation as before, and
    the same ``outputs/*.*`` artifacts under HASTE's
    ``<project-hash>/<task-id>`` prefix, so the embeddings GeoJSON,
    PMTiles and feature-sidecar URLs are unchanged. ``logs/`` is declared
    alongside them because ``embed_buildings`` writes
    ``logs/embedding_friendly.log`` there: without that declaration a
    backend with a static output layout (Azure ML) never binds the
    directory to durable storage, so the friendly progress the processor
    surfaces in the status message is lost. Both outputs are mounted live
    (the log is read while the job runs) and share the one destination
    prefix.
    """
    runtime = config.get_compute_runtime_config(EMBEDDING_WORKLOAD)
    config_path = input_files["config"]["file_path"]
    command = (
        f'"mkdir -p {JOB_WORKDIR} '
        f"&& cd {JOB_WORKDIR} "
        f"&& embed-buildings --config {JOB_WORKDIR}/{config_path}"
        '"'
    )
    prefix = output_prefix(model.projectId, execution_id)
    return ComputeJobSpec(
        executionId=execution_id,
        workload=EMBEDDING_WORKLOAD,
        backendPreference=resolve_backend_preference(
            requested=backend,
            workload=EMBEDDING_WORKLOAD,
            config=config,
        ),
        container=container_ref(runtime),
        command=command,
        inputs=[
            file_input(entry["http_url"], entry["file_path"])
            for entry in input_files.values()
        ],
        outputs=[
            workspace_output(
                name="outputs",
                pattern="outputs/*.*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            ),
            workspace_output(
                name="logs",
                # embed_buildings writes logs/embedding_friendly.log;
                # read live so the status message follows the run.
                pattern="logs/*.*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            ),
        ],
        resources=container_resources(runtime),
        timeoutSeconds=runtime["timeout_seconds"],
        tags=spec_tags(
            workload=EMBEDDING_WORKLOAD,
            project_id=model.projectId,
            task_id=execution_id,
            image_layer_id=model.imageLayerId,
            model_id=model.modelId,
        ),
    )


class EmbeddingPreprocessor:
    def __init__(self, model: Model, config: Config = None):
        if config is None:
            config = Config()
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["embedding_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.model_data = model
        self.config = config

    def send_to_queue(self):
        self.model_data.status = self.config.get_status_types().PENDING.value
        self.model_data.currentStep = 0
        self.model_data.progressPct = 0.0
        # 3 friendly steps: submit -> embedding -> tiling/finalize.
        self.model_data.totalSteps = 3
        # Stable task/execution id minted before queueing; the
        # postprocessor reuses it so a duplicate delivery cannot create a
        # second provider job.
        self.model_data.embeddingJob = TrainingJob(
            taskId=new_task_id(EMBEDDING_PREFIX),
            modelId=self.model_data.modelId,
            projectId=self.model_data.projectId,
            status=self.config.get_status_types().PENDING.value,
            creationDate=MetadataUtils.get_timestamp(),
        )
        self.queue_client.put_message(json.dumps(self.model_data.dict()))
        self.model_data.statusMessage = MetadataUtils.append_status_message(
            self.model_data.statusMessage, "Queued for embedding"
        )
        return self.model_data


class EmbeddingPostprocessor:
    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer = None,
        config: Config = None,
        execution_service=None,
    ):
        if config is None:
            config = Config()
        self.config = config
        self.model_data = model
        self.image_layer = image_layer
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=model.projectId,
            **config.storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        # Injectable so tests can drive the processor with fake adapters.
        self.execution_service = (
            execution_service
            if execution_service is not None
            else build_execution_service(self.config)
        )
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["embedding_queue_name"],
            config.queue_config["queue_account_url"],
        )

    # -- compute handle plumbing --------------------------------------

    def _pending_task_id(self) -> str:
        job = self.model_data.embeddingJob
        if job is not None and job.taskId:
            return job.taskId
        return new_task_id(EMBEDDING_PREFIX)

    def _embedding_output_uri(self, task_id: str) -> str:
        runtime = self.config.get_compute_runtime_config(EMBEDDING_WORKLOAD)
        return output_uri(
            runtime["output_container_url"],
            output_prefix(self.model_data.projectId, task_id),
        )

    def _compute_handle(self) -> Optional[ComputeJobHandle]:
        job = self.model_data.embeddingJob
        if job is None:
            return None
        return resolve_compute_job_handle(
            job,
            output_uri=(
                self._embedding_output_uri(job.taskId) if job.taskId else None
            ),
        )

    def _require_handle(self) -> ComputeJobHandle:
        handle = self._compute_handle()
        if handle is None:
            raise ValueError(
                "Embedding job for model "
                f"{self.model_data.modelId} has no compute submission to "
                "poll"
            )
        return handle

    def _read_job_output(
        self, handle: ComputeJobHandle, filename: str
    ) -> Optional[str]:
        try:
            return self.execution_service.read_output(handle, filename)
        except OutputNotAvailableError as exc:
            self.logger.info(
                "Output %s is not available yet for task %s: %s",
                filename,
                handle.executionId,
                exc,
            )
            return None

    def process(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: model "
            f"{self.model_data.modelId} status {self.model_data.status}"
        )

        if (
            self.model_data.status
            == self.config.get_status_types().PENDING.value
        ):
            self._update_progress("Submitting embedding job", step=0)
            self.model_data = self._execute_embedding()

        elif (
            self.model_data.status
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            handle = self._require_handle()
            task_status = map_state_to_status(
                self.execution_service.get_status(handle), self.config
            )
            self.logger.info(
                f"Task status for embedding model "
                f"{self.model_data.modelId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.model_data.embeddingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self._update_results_from_job(handle)
                for log in self._get_friendly_logs(handle):
                    if log[1] not in self.model_data.statusMessage:
                        self._update_progress(log[1], timestamp=log[0])
                self.execution_service.finalize(handle)

            elif task_status in (
                self.config.get_status_types().FAILED.value,
                self.config.get_status_types().CANCELLED.value,
            ):
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.model_data.embeddingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                for log in self._get_friendly_logs(handle):
                    if log[1] not in self.model_data.statusMessage:
                        self._update_progress(log[1], timestamp=log[0])
                self._update_progress(
                    "Embedding job failed", step=self.model_data.currentStep
                )
                self.execution_service.finalize(handle)
            else:
                self.model_data.status = task_status
                self.model_data.embeddingJob.status = task_status
                self.queue_client.put_message(
                    json.dumps(self.model_data.dict())
                )

        return self.model_data

    def _execute_embedding(self):
        try:
            input_files = self._create_embedding_config()
            task_id = self._pending_task_id()
            spec = build_embedding_job_spec(
                model=self.model_data,
                execution_id=task_id,
                input_files=input_files,
                config=self.config,
                backend=self.model_data.computeBackend,
            )
            handle = self.execution_service.submit(
                spec, profile=compute_profile(EMBEDDING_WORKLOAD)
            )
            self.logger.info(
                "Embedding submitted for model %s: %s",
                self.model_data.modelId,
                handle_log_fields(handle),
            )
            pending_job = self.model_data.embeddingJob
            self.model_data.embeddingJob = TrainingJob(
                jobId=handle.providerJobId,
                taskId=handle.providerTaskId or handle.executionId,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().IN_PROGRESS.value,
                creationDate=(
                    pending_job.creationDate
                    if pending_job is not None and pending_job.creationDate
                    else MetadataUtils.get_timestamp()
                ),
                computeJob=handle,
            )
            inherited = follow_on_backend(
                handle.selectedBackend, config=self.config
            )
            if inherited is not None:
                self.model_data.computeBackend = inherited
            self.model_data.status = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_progress(
                f"Embedding submitted with task id "
                f"{self.model_data.embeddingJob.taskId}",
                step=1,
            )
            self.queue_client.put_message(json.dumps(self.model_data.dict()))
        except Exception as e:
            self.logger.error(
                f"Error executing embedding for model "
                f"{self.model_data.modelId}: {e}",
                stack_info=True,
            )
            self.model_data.status = (
                self.config.get_status_types().FAILED.value
            )
            self._update_progress(
                f"Embedding job failed: {e}", step=self.model_data.currentStep
            )
        return self.model_data

    def _create_embedding_config(self):
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.model_data.projectId)}/(.*)\?+"
        )
        plain_url_pattern = r"(.*)\?+"

        imagery_url = self.image_layer.postEventMosaicCogImageryUrl
        footprints_url = self.image_layer.buildingFootprintsUrl
        if not imagery_url:
            raise ValueError("Image layer has no post-event mosaic COG.")
        if not footprints_url:
            raise ValueError("Image layer has no building footprints.")

        imagery_fn = (
            f"inputs/{extract_from_url(imagery_url, filename_pattern)}"
        )
        footprints_fn = (
            f"inputs/{extract_from_url(footprints_url, filename_pattern)}"
        )

        embeddings_name = (
            ArtifactTypes.BUILDING_EMBEDDINGS.value.substitute(
                modelName=self.model_data.modelId
            )
            + ".geojson"
        )
        pmtiles_name = (
            ArtifactTypes.BUILDING_PMTILES.value.substitute(
                modelName=self.model_data.modelId
            )
            + ".pmtiles"
        )
        sidecar_name = (
            ArtifactTypes.BUILDING_FEATURES_SIDECAR.value.substitute(
                modelName=self.model_data.modelId
            )
            + ".bin"
        )

        embedding_config = {
            "project_id": self.model_data.projectId,
            "image_layer_id": self.model_data.imageLayerId,
            "model_id": self.model_data.modelId,
            "output_dir": "outputs",
            # Relative to the task working dir: the command cd's into
            # $HASTE_JOB_WORKDIR before running embed-buildings, whose
            # WORKDIR defaults to ".". No env-var substitution step needed.
            "files": {
                "imagery": imagery_fn,
                "footprints": footprints_fn,
                "embeddings": embeddings_name,
                "pmtiles": pmtiles_name,
                "sidecar": sidecar_name,
            },
            "pipeline": {
                "model": self.model_data.embeddingModel or "mosaiks",
                "num_feats": self.model_data.numFeatures or 1024,
                "resize_factor": self.model_data.resizeFactor or 4,
                "batch_size": int(self.model_data.batchSize or 16),
            },
        }
        self.storage.save(
            identifier=self.model_data.modelId,
            data=embedding_config,
            data_type=self.config.get_metadata_types().EMBEDDING_CONFIG.value,
            data_format="json",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().EMBEDDING_CONFIG.value,
            data_format="json",
        )

        input_files = {
            "config": {
                "http_url": extract_from_url(
                    config_filepath, plain_url_pattern
                ),
                "file_path": f"inputs/{extract_from_url(config_filepath, filename_pattern)}",
            },
            "imagery": {
                "http_url": extract_from_url(imagery_url, plain_url_pattern),
                "file_path": imagery_fn,
            },
            "footprints": {
                "http_url": extract_from_url(
                    footprints_url, plain_url_pattern
                ),
                "file_path": footprints_fn,
            },
        }
        return input_files

    def _update_results_from_job(self, handle: ComputeJobHandle):
        content = self._read_job_output(handle, "embedding_manifest.json")
        if not content:
            raise FileNotFoundError(
                f"Embedding manifest not found for model "
                f"{self.model_data.modelId}"
            )
        manifest = json.loads(content)
        self.model_data.embeddingsGeoJSONUrl = self._artifact_url(
            manifest.get("embeddings_filename", "")
        )
        self.model_data.pmtilesUrl = self._artifact_url(
            manifest.get("pmtiles_filename", "")
        )
        self.model_data.featuresSidecarUrl = self._artifact_url(
            manifest.get("sidecar_filename", "")
        )
        self._update_progress(
            f"Embedded {manifest.get('num_buildings', '?')} buildings "
            f"with {manifest.get('num_features', '?')} features",
            step=self.model_data.totalSteps,
        )

    def _artifact_url(self, filename: str) -> str:
        if not filename:
            return ""
        return self.storage.get_file_remote_path(
            identifier=filename,
            extra_partition_keys=f"{self.model_data.embeddingJob.taskId}",
            data_format=os.path.splitext(filename)[1].strip("."),
        )

    def _get_friendly_logs(self, handle: ComputeJobHandle):
        content = self._read_job_output(handle, "embedding_friendly.log")
        logs = []
        if content:
            for record in content.splitlines():
                if not record:
                    continue
                parts = record.split("|", 1)
                if len(parts) == 2:
                    logs.append((parts[0], parts[1]))
        return logs

    def _update_progress(
        self, message: str, step: int = None, timestamp: str = None
    ):
        if step is not None:
            self.model_data.currentStep = int(step)
        else:
            self.model_data.currentStep += 1
        total = int(self.model_data.totalSteps or 1)
        self.model_data.progressPct = round(
            int(self.model_data.currentStep) / total * 100, 2
        )
        self.model_data.statusMessage = MetadataUtils.append_status_message(
            self.model_data.statusMessage, message, timestamp=timestamp
        )
