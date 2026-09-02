# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
from typing import Dict, NamedTuple, Optional

from ..config import Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.compute import (
    LEGACY_SYNTHESIZED_ROUTING_REASON,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeWorkload,
    OutputNotAvailableError,
)
from ..models.projects import ImageLayer, InferenceJob, Model
from ..models.training import ExperimentConfig, Inference
from ..utils.compute_jobs import resolve_compute_job_handle
from ..utils.compute_specs import (
    CONTAINER_CONFIG_WORKDIR_TOKEN,
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

# Placeholder the training image substitutes inside the generated
# experiment config (see ``compute_specs``); the command itself uses the
# canonical ``$HASTE_JOB_WORKDIR`` reference every backend exports.
CONFIG_WORKDIR = CONTAINER_CONFIG_WORKDIR_TOKEN
INFERENCE_PREFIX = "inf"
INFERENCE_WORKLOAD = ComputeWorkload.INFERENCE


def build_inference_job_spec(
    *,
    model: Model,
    execution_id: str,
    input_files: Dict[str, dict],
    config: Config,
    gdal_translate_params: str,
    backend=None,
) -> ComputeJobSpec:
    """Build the backend-neutral spec for one inference submission.

    Mirrors the pre-migration Azure Batch submission exactly: same
    training image, same ``run_workflow.py --step inference`` command,
    same ``inference/`` output pattern under HASTE's
    ``<project-hash>/<task-id>`` prefix — so ``predictedDamageLayerUrl``/
    ``gpkgUrl`` keep resolving to the same blobs. ``logs/`` is declared
    alongside it because ``run_workflow.py`` writes
    ``logs/workflow_progress.log`` there: without that declaration a
    backend with a static output layout (Azure ML) never binds the
    directory to durable storage, so the progress the processor streams
    into the user-visible status — and the failure detail it reads
    afterwards — is lost. Both outputs are mounted live (they are read
    while the job is still running) and share the one destination prefix.
    """
    runtime = config.get_compute_runtime_config(INFERENCE_WORKLOAD)
    config_path = input_files["config"]["file_path"]
    command = (
        f'"cd /app '
        f"&& source scripts/set_dirs.sh {JOB_WORKDIR}/{config_path} "
        f"&& python scripts/print_gpu_info.py "
        f"&& python run_workflow.py --config {JOB_WORKDIR}/{config_path} "
        f"--step inference"
        '"'
    )
    prefix = output_prefix(model.projectId, execution_id)
    return ComputeJobSpec(
        executionId=execution_id,
        workload=INFERENCE_WORKLOAD,
        backendPreference=resolve_backend_preference(
            requested=backend,
            workload=INFERENCE_WORKLOAD,
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
                name="inference",
                pattern="inference/**/*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            ),
            workspace_output(
                name="logs",
                # run_workflow.py's log_progress() writes
                # logs/workflow_progress.log; read live for progress and
                # after completion for failure detail.
                pattern="logs/*.*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            ),
        ],
        environment={"GDAL_TRANSLATE_PARAMS": gdal_translate_params},
        resources=container_resources(runtime),
        timeoutSeconds=runtime["timeout_seconds"],
        tags=spec_tags(
            workload=INFERENCE_WORKLOAD,
            project_id=model.projectId,
            task_id=execution_id,
            image_layer_id=model.imageLayerId,
            model_id=model.modelId,
        ),
    )


class BaseInferenceProcessor:
    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer,
        config: Config = None,
        execution_service=None,
    ):
        if config is None:
            config = Config()
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=model.projectId,
            **config.storage_config,
        )
        self.model_data = model
        self.image_layer = image_layer
        self.config = config
        self.temp_dir = os.path.join(
            config.TEMP_DIR,
            self.model_data.projectId,
            f"temp{MetadataUtils.generate_short_int_id()}",
        )
        self.logger = Logger.get_logger(__name__)
        # Injectable so tests can drive the processor with fake adapters.
        self.execution_service = (
            execution_service
            if execution_service is not None
            else build_execution_service(self.config)
        )


class InferencePreprocessor:
    def __init__(self, model: Model, config: Config = None):
        if config is None:
            config = Config()
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["inference_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.model_data = model
        self.config = config

    def send_to_queue(self, status=None):
        if status == self.config.get_status_types().CANCELLED.value:
            # Cancellation path: no new job record, just ask the queue
            # worker to cancel the inference currently in flight.
            self.model_data.inferenceStatus = status
            self.queue_client.put_message(
                json.dumps(self.model_data.dict()), visibility_timeout=1
            )
            self.model_data.inferenceStatusMessage = (
                MetadataUtils.append_status_message(
                    self.model_data.inferenceStatusMessage,
                    "Cancelling inference",
                )
            )
            return self.model_data

        self.model_data.inferenceStatus = (
            self.config.get_status_types().PENDING.value
        )
        self.model_data.inferenceCurrentStep = 0
        self.model_data.inferenceTotalSteps = 7
        self.model_data.inferenceProgressPct = 0.0

        self.model_data.inferenceStatusMessage = ""
        self.model_data.inferenceStatusMessage = (
            MetadataUtils.append_status_message(
                self.model_data.inferenceStatusMessage, "Queued for inference"
            )
        )
        # Mint the task/execution id before queueing and record it on a
        # pending InferenceJob, so the postprocessor reuses it and a
        # duplicate delivery cannot start a second provider job.
        task_id = new_task_id(INFERENCE_PREFIX)
        self.model_data.inferenceJobs.append(
            InferenceJob(
                taskId=task_id,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().PENDING.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
        )
        self.model_data.currentInferenceTaskId = task_id
        self.queue_client.put_message(json.dumps(self.model_data.dict()))
        return self.model_data


class InferenceLogRecord(NamedTuple):
    timestamp: str
    message: str

    def __str__(self):
        return f"{self.timestamp}: {self.message}"

    def __repr__(self):
        return f"{self.timestamp}: {self.message}"


class InferencePostprocessor(BaseInferenceProcessor):
    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer = None,
        experiment_config: ExperimentConfig = None,
        config: Config = None,
        execution_service=None,
    ):
        super().__init__(model, image_layer, config, execution_service)
        self.model_data = model
        self.image_layer = image_layer
        self.experiment_config = experiment_config
        self.config = config or Config()
        self.queue_client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config["inference_queue_name"],
            self.config.queue_config["queue_account_url"],
        )

    # -- compute handle plumbing --------------------------------------

    def _current_job_index(self) -> Optional[int]:
        """Index of the inference job this message is about, or ``None``."""
        for idx, inference_job in enumerate(self.model_data.inferenceJobs):
            if inference_job.taskId == self.model_data.currentInferenceTaskId:
                return idx
        return None

    def _pending_task_id(self) -> str:
        """Return the task id this run submits under, preferring the one
        the preprocessor already recorded (so retries reuse it)."""
        if self.model_data.currentInferenceTaskId:
            return self.model_data.currentInferenceTaskId
        return new_task_id(INFERENCE_PREFIX)

    def _inference_output_uri(self, task_id: str) -> str:
        runtime = self.config.get_compute_runtime_config(INFERENCE_WORKLOAD)
        return output_uri(
            runtime["output_container_url"],
            output_prefix(self.model_data.projectId, task_id),
        )

    def _compute_handle(self, job: InferenceJob) -> Optional[ComputeJobHandle]:
        """Persisted handle, or one synthesized from a legacy
        ``jobId``/``taskId`` pair plus this job's real output URI."""
        return resolve_compute_job_handle(
            job,
            output_uri=(
                self._inference_output_uri(job.taskId) if job.taskId else None
            ),
        )

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
            f"{self.__class__.__name__}.process: Processing model {self.model_data.modelId} with model status {self.model_data.status} and inference status {self.model_data.inferenceStatus}"
        )

        if (
            self.model_data.status
            == self.config.get_status_types().COMPLETED.value
            and self.model_data.inferenceStatus
            == self.config.get_status_types().PENDING.value
        ):
            self.logger.info(
                f"Executing inference for model {self.model_data.modelId}"
            )
            self._update_inference_progress(
                "Submitting inference task", step=0
            )
            self.model_data = self._execute_inference()
        elif (
            len(self.model_data.inferenceJobs) > 0
            and self.model_data.inferenceStatus
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            self.logger.info(
                f"Inference status: {self.model_data.inferenceStatus} for model {self.model_data.modelId}"
            )

            for idx, inference_job in enumerate(self.model_data.inferenceJobs):
                if (
                    inference_job.taskId
                    == self.model_data.currentInferenceTaskId
                ):
                    break

            handle = self._compute_handle(inference_job)
            if handle is None:
                raise ValueError(
                    "Inference job "
                    f"{self.model_data.currentInferenceTaskId} for model "
                    f"{self.model_data.modelId} has no compute submission "
                    "to poll"
                )
            task_status = map_state_to_status(
                self.execution_service.get_status(handle), self.config
            )

            self.logger.info(
                f"Task status for model {self.model_data.modelId} is {task_status}"
            )

            logs = self._get_inference_logs(handle)
            if logs:
                for log in logs:
                    if (
                        log.message
                        not in self.model_data.inferenceStatusMessage
                    ):
                        self._update_inference_progress(
                            log.message, timestamp=log.timestamp
                        )
                    # Also update the logs for the specific job
                self.model_data.inferenceJobs[
                    idx
                ].logs = self.model_data.inferenceStatusMessage

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_data.inferenceStatus = task_status
                self.model_data.inferenceJobs[idx].status = task_status
                self.model_data.inferenceJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()

                self.model_data.inferenceOutputPath = output_prefix(
                    self.model_data.projectId,
                    self.model_data.inferenceJobs[idx].taskId,
                )

                # Add artifact Urls only for successful inference
                identifier = self.config.get_artifact_types().VISUALIZER.value.substitute(
                    projectId=self.model_data.projectId,
                    imageLayerId=self.model_data.imageLayerId,
                )

                # The local Docker backend stores files in an inference/
                # subfolder, the remote backends don't. Keyed off the
                # backend that actually ran *this* job (from its persisted
                # handle), not the process-wide default, so a mixed-backend
                # deployment resolves each job's URLs correctly. A job
                # submitted before the compute layer existed has no
                # recorded backend (its handle is synthesized as Batch),
                # so for that case only, fall back to the deployment's
                # configured runner type — preserving the pre-migration
                # behavior for jobs already in flight during an upgrade.
                ran_locally = (
                    handle.selectedBackend == ComputeBackend.LOCAL
                    or (
                        handle.routingReason
                        == LEGACY_SYNTHESIZED_ROUTING_REASON
                        and self.config.runner_type == "local"
                    )
                )
                if ran_locally:
                    extra_keys = [
                        f"{self.model_data.inferenceJobs[idx].taskId}",
                        "inference",
                    ]
                else:
                    extra_keys = f"{self.model_data.inferenceJobs[idx].taskId}"

                self.model_data.predictedDamageLayerUrl = (
                    self.storage.get_file_remote_path(
                        identifier=identifier,
                        extra_partition_keys=extra_keys,
                        data_format="tif",
                    )
                )

                identifier = self.config.get_artifact_types().INFERENCE_GPKG.value.substitute(
                    modelName=self.model_data.name
                )

                self.model_data.gpkgUrl = self.storage.get_file_remote_path(
                    identifier=identifier,
                    extra_partition_keys=extra_keys,
                    data_format="gpkg",
                )
                self._update_inference_progress(
                    "Inference job completed successfully"
                )
                self.model_data.inferenceJobs[
                    idx
                ].logs = self.model_data.inferenceStatusMessage
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)

            elif task_status in (
                self.config.get_status_types().FAILED.value,
                self.config.get_status_types().CANCELLED.value,
            ):
                self.model_data.inferenceStatus = task_status
                self.model_data.inferenceJobs[idx].status = task_status
                self.model_data.inferenceJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()
                self.model_data.inferenceOutputPath = output_prefix(
                    self.model_data.projectId,
                    self.model_data.inferenceJobs[idx].taskId,
                )

                # Retrieve stderr from the job for additional error context
                stderr_detail = self._get_task_stderr(handle)
                failure_message = "Inference job failed"
                if stderr_detail:
                    failure_message += f"\n{stderr_detail}"
                self._update_inference_progress(
                    failure_message,
                    step=self.model_data.inferenceCurrentStep,
                )
                self.model_data.inferenceJobs[
                    idx
                ].logs = self.model_data.inferenceStatusMessage
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)
            else:
                self.model_data.inferenceStatus = task_status
                self.model_data.inferenceJobs[idx].status = task_status
                self.queue_client.put_message(
                    json.dumps(self.model_data.dict())
                )
        else:
            self.model_data.inferenceStatus = (
                self.config.get_status_types().FAILED.value
            )
            self.logger.info(
                f"Model {self.model_data.modelId} is not ready for inference"
            )

        return self.model_data

    def _execute_inference(self):
        try:
            self.logger.info(
                f"Adding task for model inference {self.model_data.modelId}"
            )
            # Prepare the input files and experiment config for the inference task
            inference_input_files = self._create_inference_config()
            # Multiple inference outputs are stored, but the visualizer
            # imagery is set to the last completed job.
            task_id = self._pending_task_id()
            spec = build_inference_job_spec(
                model=self.model_data,
                execution_id=task_id,
                input_files=inference_input_files,
                config=self.config,
                gdal_translate_params=self.config.gdal_translate_params,
                backend=self.model_data.computeBackend,
            )
            handle = self.execution_service.submit(
                spec, profile=compute_profile(INFERENCE_WORKLOAD)
            )
            self.logger.info(
                "Inference submitted for model %s: %s",
                self.model_data.modelId,
                handle_log_fields(handle),
            )
            submitted_job = InferenceJob(
                jobId=handle.providerJobId,
                taskId=handle.providerTaskId or handle.executionId,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().IN_PROGRESS.value,
                creationDate=MetadataUtils.get_timestamp(),
                computeJob=handle,
            )
            pending_idx = self._current_job_index()
            if pending_idx is not None:
                # Replace the pending record created by the preprocessor
                # instead of appending a second entry for the same run.
                submitted_job.creationDate = (
                    self.model_data.inferenceJobs[pending_idx].creationDate
                    or submitted_job.creationDate
                )
                self.model_data.inferenceJobs[pending_idx] = submitted_job
            else:
                self.model_data.inferenceJobs.append(submitted_job)
            self.model_data.currentInferenceTaskId = submitted_job.taskId
            # Persist the backend that ran this job so the automatic
            # artifact-packaging follow-on inherits it.
            inherited = follow_on_backend(
                handle.selectedBackend, config=self.config
            )
            if inherited is not None:
                self.model_data.computeBackend = inherited
            self.model_data.inferenceStatus = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_inference_progress(
                f"Inference submitted with task id {submitted_job.taskId}",
                step=0,
            )
            self.queue_client.put_message(json.dumps(self.model_data.dict()))
            self.logger.info(
                f"InProgress message to queue sent for model {self.model_data.modelId}"
            )
        except Exception as e:
            self.logger.error(
                f"Error processing model {self.model_data.modelId}: {e}",
                stack_info=True,
            )
            # Surface the error in the user-facing status message for the most
            # common actionable failure (missing cached building-footprint URL
            # — see _create_inference_config). For other exception types this
            # still gives the user something more useful than a silent FAILED.
            self._update_inference_progress(
                f"Inference failed to start: {e}",
                step=self.model_data.inferenceCurrentStep,
            )
            self.model_data.inferenceStatus = (
                self.config.get_status_types().FAILED.value
            )

        return self.model_data

    def _create_inference_config(self):
        # Hard requirement: every layer that goes through inference must have
        # a cached building-footprint URL produced by the imageryprep workflow.
        # See PR 24 — the inference workflow no longer downloads
        # footprints itself. Layers created before this change must be
        # re-processed.
        if not self.image_layer.buildingFootprintsUrl:
            raise ValueError(
                f"Image layer {self.image_layer.imageLayerId} has no cached "
                "building-footprint URL. This layer was processed before the "
                "imageryprep workflow began caching footprints; please "
                "re-process the image layer."
            )

        inference_input_files = {}
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.model_data.projectId)}/(.*)\?+"
        )
        # NOTE: SAS token is not needed if using Managed Identity but this is very blob specific
        #  - so these may need to be methods in the data layer classes
        # if SAS token is included then the compute job fails to download the blob with an InvalidAuthenticationInfo error
        # NOTE: One cleaner way to build inference resource files could be to make the bda code responsible for
        # downloading the files, and this download runs on the batch container.
        plain_url_pattern = r"(.*)\?+"

        raw_fn = f"inputs/{extract_from_url(self.image_layer.postEventMosaicCogImageryUrl, filename_pattern)}"
        inference_input_files["raw_cog_image"] = {
            "http_url": extract_from_url(
                self.image_layer.postEventMosaicCogImageryUrl,
                plain_url_pattern,
            ),
            "file_path": raw_fn,
        }

        rgb_fn = f"inputs/{extract_from_url(self.image_layer.postEventProcessedImageryUrl, filename_pattern)}"
        inference_input_files["rgb_image"] = {
            "http_url": extract_from_url(
                self.image_layer.postEventProcessedImageryUrl,
                plain_url_pattern,
            ),
            "file_path": rgb_fn,
        }

        # Cached Overture building footprints from the imageryprep workflow.
        # Land at a stable, image-name-agnostic path so run_workflow.py can
        # reference it directly without parsing image-layer-specific filenames.
        inference_input_files["building_footprints"] = {
            "http_url": extract_from_url(
                self.image_layer.buildingFootprintsUrl,
                plain_url_pattern,
            ),
            "file_path": "inputs/building_footprints.gpkg",
        }

        checkpoint_version = "last.ckpt"  # TODO - accept the checkpoint version from UI when inference is invoked
        inference_input_files["checkpoint"] = {
            "http_url": f"{self.storage.get_base_url()}/{self.model_data.checkpointPath}/{checkpoint_version}",
            "file_path": f"inputs/checkpoint/{checkpoint_version}",
        }

        # Load the experiment config that was saved during training
        config_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )

        # Create a copy of the existing experiment config and update inference configuration
        updated_experiment_config = self.experiment_config.dict()

        # Create inference configuration using pydantic model for consistency
        inference_config = Inference(
            batch_size=1,
            checkpoint_fn=f"{CONFIG_WORKDIR}/inputs/checkpoint/{checkpoint_version}",
            gpu_id=0,
            output_subdir="inference",
            padding=64,
            patch_size=256,
            building_footprints_source="microsoft",
            country_alpha2_iso_code="US",
            predictions_gpkg_fileprefix=self.config.get_artifact_types().INFERENCE_GPKG.value.substitute(
                modelName=self.model_data.name.replace(" ", "-"),
            ),
        )

        # Update inference settings for the inference run
        updated_experiment_config["inference"] = inference_config.dict()

        # Save the updated experiment config with inference settings
        self.storage.save(
            identifier=self.model_data.modelId,
            data=updated_experiment_config,
            data_type=self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )
        inference_input_files["config"] = {
            "http_url": extract_from_url(config_filepath, plain_url_pattern),
            "file_path": f"inputs/{extract_from_url(config_filepath, filename_pattern)}",
        }
        return inference_input_files

    def _get_inference_logs(self, handle: ComputeJobHandle):
        content = self._read_job_output(handle, "workflow_progress.log")
        if content is None:
            return None
        logs = []
        try:
            logs = [
                InferenceLogRecord(*record.split("|", 1))
                for record in content.splitlines()
                if record and "|" in record
            ]
        except Exception as e:
            self.logger.error(
                f"Error parsing inference log record: {e}", stack_info=True
            )
            # suggests data contract with run_workflow.py is broken
            # Long term fix: refactor core into installable python package, install in training docker image
            # Short term fix: raise an error
            raise
        return logs

    def _get_task_stderr(self, handle: ComputeJobHandle) -> str:
        """Log stderr from a failed job server-side for admin diagnostics.

        Raw stderr can contain stack traces, file paths, and other internal details
        that must not reach end users. This method always returns an empty string;
        the content is recorded only via the server-side logger.
        """
        task_id = handle.providerTaskId or handle.executionId
        try:
            stderr_content = self._read_job_output(handle, "stderr.txt")
            if stderr_content and stderr_content.strip():
                self.logger.error(
                    f"Inference task {task_id} stderr (server-side only): "
                    f"{stderr_content.strip()[-2000:]}"
                )
        except Exception as e:
            self.logger.warning(
                f"Could not read stderr.txt for task {task_id}: {e}"
            )
        return ""

    def _update_inference_progress(
        self, message: str, step: int = None, timestamp: str = None
    ):
        if step is not None:
            self.model_data.inferenceCurrentStep = int(step)
        else:
            self.model_data.inferenceCurrentStep += 1
        self.model_data.inferenceProgressPct = round(
            int(self.model_data.inferenceCurrentStep)
            / int(self.model_data.inferenceTotalSteps)
            * 100,
            2,
        )
        self.model_data.inferenceStatusMessage = (
            MetadataUtils.append_status_message(
                self.model_data.inferenceStatusMessage,
                message,
                timestamp=timestamp,
            )
        )

    def cancel(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Canceling inference for model {self.model_data.modelId}"
        )
        self.model_data.inferenceStatus = (
            self.config.get_status_types().CANCELLED.value
        )

        self._cancel_inference()
        self._update_inference_progress(
            "Inference task cancelled",
            step=self.model_data.inferenceCurrentStep,
        )
        return self.model_data

    def _cancel_inference(self):
        idx = self._current_job_index()
        if idx is None:
            self.logger.info(
                "No inference job matching %s for model %s; nothing to "
                "cancel.",
                self.model_data.currentInferenceTaskId,
                self.model_data.modelId,
            )
            return
        job = self.model_data.inferenceJobs[idx]
        job.status = self.config.get_status_types().CANCELLED.value
        job.completedDate = MetadataUtils.get_timestamp()
        handle = self._compute_handle(job)
        if handle is None:
            # Cancelled before submission: the pending record above is
            # all there is to update.
            self.logger.info(
                "Inference job %s for model %s was cancelled before "
                "submission; no provider job to cancel.",
                job.taskId,
                self.model_data.modelId,
            )
            return
        try:
            self.execution_service.cancel(handle)
            self.logger.info(
                "Inference cancellation requested for model %s: %s",
                self.model_data.modelId,
                handle_log_fields(handle),
            )
        except Exception as e:
            self.logger.error(
                f"Error cancelling inference job {job.jobId} for model {self.model_data.modelId}: {e}",
                stack_info=True,
            )
