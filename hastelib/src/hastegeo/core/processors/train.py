# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
from typing import Dict, Optional

from ..config import Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.compute import (
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeWorkload,
    OutputNotAvailableError,
)
from ..models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    Project,
    TrainingJob,
)
from ..models.training import ExperimentConfig, Imagery, Labels, Training
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
from ..utils.data import convert_json_to_geojson, extract_from_url
from ..utils.label_classes import should_use_constraint_loss
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler
from ..utils.tbparser import calculate_metrics, parse_tb_event_logs

# Placeholder the training image substitutes inside the generated
# experiment config (see ``compute_specs``); the command itself uses the
# canonical ``$HASTE_JOB_WORKDIR`` reference every backend exports.
CONFIG_WORKDIR = CONTAINER_CONFIG_WORKDIR_TOKEN
TRAINING_PREFIX = "trn"
TRAINING_WORKLOAD = ComputeWorkload.TRAINING


def build_training_job_spec(
    *,
    model: Model,
    execution_id: str,
    input_files: Dict[str, dict],
    config: Config,
    backend=None,
) -> ComputeJobSpec:
    """Build the backend-neutral spec for one training submission.

    ``input_files`` is the ``{name: {"http_url", "file_path"}}`` mapping
    ``TrainPostprocessor._create_experiment_config`` produces; each entry
    becomes a ``ComputeInput`` staged at its workspace-relative
    ``file_path``. Every artifact of the run is written back under HASTE's
    unchanged ``<project-hash>/<task-id>`` prefix, mounted live because
    the processor reads TensorBoard events and the progress log while the
    job is still running.
    """
    runtime = config.get_compute_runtime_config(TRAINING_WORKLOAD)
    config_path = input_files["config"]["file_path"]
    command = (
        f'"cd /app '
        f"&& source scripts/set_dirs.sh {JOB_WORKDIR}/{config_path} "
        f"&& python scripts/print_gpu_info.py "
        f"&& python run_workflow.py --config {JOB_WORKDIR}/{config_path} "
        f"--step training"
        '"'
    )
    prefix = output_prefix(model.projectId, execution_id)
    return ComputeJobSpec(
        executionId=execution_id,
        workload=TRAINING_WORKLOAD,
        backendPreference=resolve_backend_preference(
            requested=backend,
            workload=TRAINING_WORKLOAD,
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
                name="workspace",
                # Everything under the job work directory, matching the
                # pre-migration file pattern: checkpoints, TensorBoard
                # events, logs and every other training artifact land
                # under the same task prefix as before.
                pattern="**/*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            )
        ],
        resources=container_resources(runtime),
        timeoutSeconds=runtime["timeout_seconds"],
        tags=spec_tags(
            workload=TRAINING_WORKLOAD,
            project_id=model.projectId,
            task_id=execution_id,
            image_layer_id=model.imageLayerId,
            model_id=model.modelId,
        ),
    )


class BaseTrainProcessor:
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
        # Injectable so tests (and any future caller that owns its own
        # registry) can supply a service backed by fake adapters instead
        # of reaching real providers.
        self.execution_service = (
            execution_service
            if execution_service is not None
            else build_execution_service(self.config)
        )


class TrainPreprocessor:
    def __init__(self, model: Model, config: Config = None):
        if config is None:
            config = Config()
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["train_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.model_data = model
        self.config = config

    def send_to_queue(self, status=None):
        if status == self.config.get_status_types().CANCELLED.value:
            self.model_data.status = status
            # Cancel the training job ASAP
            self.queue_client.put_message(
                json.dumps(self.model_data.dict()), visibility_timeout=1
            )
            self.model_data.statusMessage = (
                MetadataUtils.append_status_message(
                    self.model_data.statusMessage, "Cancelling training"
                )
            )
        else:
            self.model_data.status = (
                self.config.get_status_types().PENDING.value
            )
            self.model_data.currentStep = 0
            self.model_data.progressPct = 0.0
            self.model_data.totalSteps = int(self.model_data.maxEpochs) + 1
            # Mint the task/execution id here, before the message is
            # queued, and record it on a pending TrainingJob. The
            # postprocessor reuses it verbatim, so a duplicate queue
            # delivery (or a worker restart after the provider already
            # accepted the job) can never produce a second id for the
            # same run. A new user-triggered run comes through here
            # again and gets a fresh one.
            self.model_data.trainingJob = TrainingJob(
                taskId=new_task_id(TRAINING_PREFIX),
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().PENDING.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
            self.queue_client.put_message(json.dumps(self.model_data.dict()))
            self.model_data.statusMessage = (
                MetadataUtils.append_status_message(
                    self.model_data.statusMessage, "Queued for training"
                )
            )
        return self.model_data


class TrainPostprocessor(BaseTrainProcessor):
    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer = None,
        label_project: LabelProject = None,
        project: Project = None,
        config: Config = None,
        execution_service=None,
    ):
        super().__init__(model, image_layer, config, execution_service)
        self.model_data = model
        self.image_layer = image_layer
        self.label_project = label_project
        self.project = project
        self.config = config or Config()
        self.queue_client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config["train_queue_name"],
            self.config.queue_config["queue_account_url"],
        )

    # -- compute handle plumbing --------------------------------------

    def _pending_task_id(self) -> str:
        """Return the task id this run submits under.

        Reuses the id the preprocessor recorded on the pending
        ``TrainingJob``; only falls back to minting one for a message
        queued before that record existed.
        """
        job = self.model_data.trainingJob
        if job is not None and job.taskId:
            return job.taskId
        return new_task_id(TRAINING_PREFIX)

    def _training_output_uri(self, task_id: str) -> str:
        runtime = self.config.get_compute_runtime_config(TRAINING_WORKLOAD)
        return output_uri(
            runtime["output_container_url"],
            output_prefix(self.model_data.projectId, task_id),
        )

    def _compute_handle(self) -> Optional[ComputeJobHandle]:
        """Resolve this model's training submission to a compute handle.

        Prefers the persisted ``computeJob``; for a record written before
        the compute layer existed it synthesizes an Azure Batch handle
        from ``jobId``/``taskId`` plus this workload's real output URI, so
        an in-flight legacy job keeps polling on the backend that actually
        ran it.
        """
        job = self.model_data.trainingJob
        if job is None:
            return None
        return resolve_compute_job_handle(
            job,
            output_uri=(
                self._training_output_uri(job.taskId) if job.taskId else None
            ),
        )

    def _require_handle(self) -> ComputeJobHandle:
        handle = self._compute_handle()
        if handle is None:
            raise ValueError(
                "Training job for model "
                f"{self.model_data.modelId} has no compute submission to "
                "poll"
            )
        return handle

    def process(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Processing model {self.model_data.modelId} with status {self.model_data.status}"
        )

        if (
            self.model_data.status
            == self.config.get_status_types().PENDING.value
        ):
            self.logger.info(f"Executing model {self.model_data.modelId}")
            self._update_training_progress("Submitting training job", step=0)
            self.model_data = self._execute_training()

        elif (
            self.model_data.status
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            handle = self._require_handle()
            task_status = map_state_to_status(
                self.execution_service.get_status(handle), self.config
            )

            self.logger.info(
                f"Task status for model {self.model_data.modelId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.model_data.status = task_status
                self.model_data.trainingJob.status = task_status
                self.model_data.trainingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self.model_data.trainingOutputPath = output_prefix(
                    self.model_data.projectId,
                    self.model_data.trainingJob.taskId,
                )
                # Add checkpointPath only for successful training
                self.model_data.checkpointPath = (
                    f"{self.model_data.trainingOutputPath}/checkpoint"
                )

                train_start_time, logs = self._get_training_logs(handle)
                if logs:
                    self.model_data.trainingJob.logs = logs
                    self._calculate_upsert_training_metrics(job_completed=True)
                    self.model_data.trainingJob.trainStartTime = (
                        train_start_time
                    )
                    step = (
                        int(self.model_data.trainingJob.completedEpochs or "0")
                        + 1
                    )
                    message = (
                        f"Training job completed successfully\n"
                        f"trainStartTime: {self.model_data.trainingJob.trainStartTime or 'n/a'}\n"
                        f"epoch: {self.model_data.trainingJob.completedEpochs}\n"
                        f"elapsedDurationInMinutes: {self.model_data.trainingJob.totalElapsedTime}\n"
                        f"completedDate: {self.model_data.trainingJob.completedDate}"
                    )
                    self._update_training_progress(message, step=step)
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)

            elif task_status in (
                self.config.get_status_types().FAILED.value,
                self.config.get_status_types().CANCELLED.value,
            ):
                self.model_data.trainingJob.status = task_status
                self.model_data.trainingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self.model_data.status = task_status
                self.model_data.trainingOutputPath = output_prefix(
                    self.model_data.projectId,
                    self.model_data.trainingJob.taskId,
                )

                # Retrieve error details from the compute job before cleanup
                error_details = self._get_task_error_details(handle)
                failure_message = "Training job failed"
                if error_details:
                    failure_message += f"\n{error_details}"
                self._update_training_progress(
                    failure_message, step=self.model_data.currentStep
                )
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)
            else:
                self.model_data.status = task_status
                self.model_data.trainingJob.status = task_status
                train_start_time, logs = self._get_training_logs(handle)
                if logs:
                    self.model_data.trainingJob.logs = logs
                    self._calculate_upsert_training_metrics()
                    self.model_data.trainingJob.trainStartTime = (
                        train_start_time
                    )
                    self.model_data.currentStep = (
                        int(self.model_data.trainingJob.completedEpochs) + 1
                    )
                    if (
                        self.model_data.trainingJob.approxMinutesToComplete
                        == "n/a"
                    ):
                        approxTimeStr = "calculating..."
                    else:
                        approxTimeStr = (
                            self.model_data.trainingJob.approxMinutesToComplete
                        )

                    message = (
                        f"Training job in progress\n"
                        f"trainStartTime: {self.model_data.trainingJob.trainStartTime or 'n/a'}\n"
                        # We're in progress in the one after the latest completed epoch
                        f"epoch: {int(self.model_data.trainingJob.completedEpochs or '0') + 1}\n"
                        f"elapsedDurationInMinutes: {self.model_data.trainingJob.totalElapsedTime}\n"
                        f"approxMinutesToComplete: {approxTimeStr}"
                    )
                    self._update_training_progress(
                        message, step=self.model_data.currentStep
                    )
                self.queue_client.put_message(
                    json.dumps(self.model_data.dict())
                )

        return self.model_data

    def _execute_training(self):
        try:
            experiment_input_files = self._create_experiment_config()
            task_id = self._pending_task_id()
            self.logger.info(
                "Submitting training job for model %s with task id %s",
                self.model_data.modelId,
                task_id,
            )
            spec = build_training_job_spec(
                model=self.model_data,
                execution_id=task_id,
                input_files=experiment_input_files,
                config=self.config,
                backend=self.model_data.computeBackend,
            )
            handle = self.execution_service.submit(
                spec, profile=compute_profile(TRAINING_WORKLOAD)
            )
            self.logger.info(
                "Training submitted for model %s: %s",
                self.model_data.modelId,
                handle_log_fields(handle),
            )
            pending_job = self.model_data.trainingJob
            self.model_data.trainingJob = TrainingJob(
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
            # Persist the backend that actually ran this job so an
            # automatic follow-on (inference, artifact packaging) inherits
            # it; an explicit preference on a later request still wins.
            inherited = follow_on_backend(
                handle.selectedBackend, config=self.config
            )
            if inherited is not None:
                self.model_data.computeBackend = inherited
            self.model_data.trainDate = MetadataUtils.get_timestamp()
            self.model_data.status = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_training_progress(
                f"Training submitted with task id {task_id}", step=0
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
            self.model_data.status = (
                self.config.get_status_types().FAILED.value
            )

        return self.model_data

    def _create_experiment_config(self):
        experiment_input_files = {}
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.model_data.projectId)}/(.*)\?+"
        )
        # NOTE: SAS token is not needed if using Managed Identity but this is very blob specific
        #  - so these may need to be methods in the data layer classes
        # including the SAS token results in the compute job failing to download the blob with an InvalidAuthenticationInfo error
        plain_url_pattern = r"(.*)\?+"
        # Save the aliased labels as a geojson file to feed to the compute job
        labels_geojson = convert_json_to_geojson(
            self.label_project.model_dump(by_alias=True)
        )
        self.storage.save(
            identifier=self.model_data.modelId,
            data=labels_geojson,
            data_type=self.config.get_metadata_types().TRAIN_LABELS.value,
            data_format="geojson",
        )
        labels_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().TRAIN_LABELS.value,
            data_format="geojson",
        )
        self.model_data.labelsUrl = labels_filepath

        experiment_input_files["labels"] = {
            "http_url": extract_from_url(labels_filepath, plain_url_pattern),
            "file_path": f"inputs/{extract_from_url(labels_filepath, filename_pattern)}",
        }
        raw_fn = f"inputs/{extract_from_url(self.image_layer.postEventMosaicCogImageryUrl, filename_pattern)}"
        experiment_input_files["raw_cog_image"] = {
            "http_url": extract_from_url(
                self.image_layer.postEventMosaicCogImageryUrl,
                plain_url_pattern,
            ),
            "file_path": raw_fn,
        }

        rgb_fn = f"inputs/{extract_from_url(self.image_layer.postEventProcessedImageryUrl, filename_pattern)}"
        experiment_input_files["rgb_image"] = {
            "http_url": extract_from_url(
                self.image_layer.postEventProcessedImageryUrl,
                plain_url_pattern,
            ),
            "file_path": rgb_fn,
        }
        if self.model_data.initialWeightsUrl:
            initial_weights_filename = os.path.basename(
                self.model_data.initialWeightsUrl
            )

            experiment_input_files["initial_weights"] = {
                "http_url": f"{self.storage.get_base_url()}/{self.model_data.initialWeightsUrl}",
                "file_path": f"inputs/{initial_weights_filename}",
            }
        # Label class order affects the colors assigned to the predicted damage layer.
        # This logic preserves the order to match how the label classes were defined at project creation time
        # Note: By providing the classes in a suitable order on Project creation, we are covering
        # the 80% use case.
        # NOTE: verify if this will work for all use cases, like flooding, etc.
        label_classes = [
            primary_class.name for primary_class in self.project.primaryClasses
        ]
        # Paths here need to be in the context of the working directory of the task
        experiment_config = ExperimentConfig(
            experiment_dir=CONFIG_WORKDIR,
            experiment_name=f"model_{self.model_data.modelId}",
            imagery=Imagery(
                normalization_means=self.image_layer.normalizationMeans,
                normalization_stds=self.image_layer.normalizationStds,
                num_channels=len(self.image_layer.normalizationMeans),
                raw_fn=f"{CONFIG_WORKDIR}/{raw_fn}",
                rgb_fn=f"{CONFIG_WORKDIR}/{rgb_fn}",
            ),
            labels=Labels(
                buffer_in_meters=3,  # default - add options on user input form to customize
                class_to_buffer="Building",  # default - add options on user input form to customize
                class_to_buffer_by="Background",  # default - add options on user input form to customize
                classes=label_classes,
                fn=f"{CONFIG_WORKDIR}/{experiment_input_files['labels']['file_path']}",
            ),
            training=Training(
                batch_size=self.model_data.batchSize or 1,
                checkpoint_subdir="checkpoint",
                gpu_id=0,
                learning_rate=self.model_data.learningRate or 0.0001,
                log_dir=f"{CONFIG_WORKDIR}/logs",
                max_epochs=self.model_data.maxEpochs or 1,
                # "No Damage" is a weak label -- it says a building is not
                # damaged, not what its pixels look like -- so when a project
                # defines that class, train it with the constraint loss
                # instead of as an ordinary hard class.
                use_constraint_loss=should_use_constraint_loss(label_classes),
                initial_weights_fn=(
                    f"{CONFIG_WORKDIR}/inputs/{initial_weights_filename}"
                    if self.model_data.initialWeightsUrl
                    else None
                ),
            ),
        )
        # Save the experiment config as a yaml file to feed to the compute job
        self.storage.save(
            identifier=self.model_data.modelId,
            data=experiment_config.dict(),
            data_type=self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )
        experiment_input_files["config"] = {
            "http_url": extract_from_url(config_filepath, plain_url_pattern),
            "file_path": f"inputs/{extract_from_url(config_filepath, filename_pattern)}",
        }
        return experiment_input_files

    def _read_job_output(
        self, handle: ComputeJobHandle, filename: str, *, as_chunks=False
    ):
        """Read one file from the job's workspace, or ``None``.

        A not-yet-produced live file (progress log before the first write,
        TensorBoard events before the first epoch) is an expected
        condition, not an error, so ``OutputNotAvailableError`` is
        reported as "nothing to read" rather than propagated.
        """
        try:
            return self.execution_service.read_output(
                handle, filename, as_chunks=as_chunks
            )
        except OutputNotAvailableError as exc:
            self.logger.info(
                "Output %s is not available yet for task %s: %s",
                filename,
                handle.executionId,
                exc,
            )
            return None

    def _get_training_logs(self, handle: ComputeJobHandle):
        content = self._read_job_output(
            handle, "events.out.tfevents", as_chunks=True
        )
        if content is None:
            return None, None
        # Read the output content and save it to a local file
        output_path = f"{self.temp_dir}/log.tfevents"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in content:
                f.write(chunk)
        # Parse the TensorBoard event file using tensorboard package
        try:
            start_time, events_json = parse_tb_event_logs(output_path)
        except Exception as e:
            self.logger.error(f"Error parsing Tensorboard Log file: {e}")
            events_json = None
            start_time = None
        return start_time, events_json

    def _get_task_error_details(self, handle: ComputeJobHandle) -> str:
        """Retrieve user-safe error details from a failed training job.

        Returns generic error lines from workflow_progress.log (which run_workflow.py
        sanitizes before writing). Raw stderr.txt is logged server-side only — never
        returned to callers, since it can contain stack traces, file paths, and other
        internal details that must not reach end users.

        Returns:
            A string with sanitized error details, or empty string if none found.
        """
        error_parts = []
        task_id = handle.providerTaskId or handle.executionId

        try:
            progress_content = self._read_job_output(
                handle, "workflow_progress.log"
            )
            if progress_content:
                for line in progress_content.strip().splitlines():
                    if not line:
                        continue
                    parts = line.split("|", 1)
                    message = parts[1] if len(parts) == 2 else line
                    if any(
                        keyword in message.lower()
                        for keyword in ["error", "failed", "unexpected"]
                    ):
                        error_parts.append(message.strip())
        except Exception as e:
            self.logger.warning(
                f"Could not read workflow_progress.log for task {task_id}: {e}"
            )

        # Read stderr.txt to log server-side for admin diagnostics, but do NOT
        # include it in the returned (user-visible) string.
        try:
            stderr_content = self._read_job_output(handle, "stderr.txt")
            if stderr_content and stderr_content.strip():
                self.logger.error(
                    f"Training task {task_id} stderr (server-side only): "
                    f"{stderr_content.strip()[-2000:]}"
                )
        except Exception as e:
            self.logger.warning(
                f"Could not read stderr.txt for task {task_id}: {e}"
            )

        return "\n".join(error_parts)

    def _calculate_upsert_training_metrics(self, job_completed=False):
        # Calculate metrics from the TensorBoard event file and set the attrbutes in the TrainingJob
        try:
            if self.model_data.trainingJob.logs:
                metrics = calculate_metrics(
                    self.model_data.trainingJob.logs, self.model_data.maxEpochs
                )
                if metrics is None:
                    return False

                if job_completed:
                    self.model_data.trainingJob.completedEpochs = (
                        self.model_data.maxEpochs
                    )
                    self.model_data.trainingJob.approxMinutesToComplete = "0"
                else:
                    self.model_data.trainingJob.completedEpochs = (
                        str(metrics["completed_epochs"])
                        if metrics["completed_epochs"]
                        else "0"
                    )
                    self.model_data.trainingJob.approxMinutesToComplete = (
                        str(metrics["approx_time_to_complete"])
                        if metrics["approx_time_to_complete"]
                        else "n/a"
                    )
                    self.model_data.trainingJob.timePerEpoch = (
                        str(metrics["time_per_epoch"])
                        if metrics["time_per_epoch"]
                        else "n/a"
                    )

                self.model_data.trainingJob.totalElapsedTime = (
                    str(metrics["total_elapsed_time"])
                    if metrics["total_elapsed_time"]
                    else "n/a"
                )

            else:
                return False
        except Exception as e:
            self.logger.error(
                f"Error calculating training metrics: {e}", exc_info=True
            )
            return False
        self.logger.info("Training metrics calculated successfully")
        return True

    def _update_training_progress(
        self, message: str, step: int = None, timestamp: str = None
    ):
        if step is not None:
            self.model_data.currentStep = int(step)
        else:
            self.model_data.currentStep += 1
        self.model_data.progressPct = round(
            int(self.model_data.currentStep)
            / int(self.model_data.totalSteps)
            * 100,
            2,
        )
        self.model_data.statusMessage = MetadataUtils.append_status_message(
            self.model_data.statusMessage, message, timestamp=timestamp
        )

    def cancel(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Canceling training for model {self.model_data.modelId}"
        )
        self.model_data.status = self.config.get_status_types().CANCELLED.value
        if (
            self.model_data.trainingJob
            and self.model_data.trainingJob.status is not None
            and self.model_data.trainingJob.status
            != self.config.get_status_types().CANCELLED.value
        ):
            message = self._cancel_training()
            self._update_training_progress(
                f"{message}", step=self.model_data.currentStep
            )
            self.model_data.trainingJob.status = (
                self.config.get_status_types().CANCELLED.value
            )
            self.model_data.trainingJob.completedDate = (
                MetadataUtils.get_timestamp()
            )
        self._update_training_progress(
            "Training cancelled", step=self.model_data.currentStep
        )
        return self.model_data

    def _cancel_training(self):
        handle = self._compute_handle()
        if handle is None:
            # Cancelled before the job was ever submitted to a provider:
            # there is nothing to cancel remotely, and the pending record
            # is marked cancelled by the caller below.
            self.logger.info(
                "Training for model %s was cancelled before submission; "
                "no provider job to cancel.",
                self.model_data.modelId,
            )
            return "Training cancelled before submission."
        try:
            task_id = handle.providerTaskId or handle.executionId
            self.execution_service.cancel(handle)
            message = f"Task {task_id} cancelled successfully."
            self.logger.info(
                "Training cancellation requested: %s",
                handle_log_fields(handle),
            )
            # Release the execution's temporary resources
            self.execution_service.finalize(handle)
            self.model_data.trainingOutputPath = output_prefix(
                self.model_data.projectId, task_id
            )
            # Note: Do we want to set checkpoint paths if available for cancelled model training tasks?
            return message
        except Exception as e:
            self.logger.error(
                f"Error cancelling training job {self.model_data.trainingJob.jobId} for model {self.model_data.modelId}: {e}",
                stack_info=True,
            )
            raise
