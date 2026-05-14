# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os

from hastegeo.core.runners.unified_runner import UnifiedRunner

from ..config import Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    Project,
    TrainingJob,
)
from ..models.training import ExperimentConfig, Imagery, Labels, Training
from ..utils.data import convert_json_to_geojson, extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler
from ..utils.tbparser import calculate_metrics, parse_tb_event_logs

# Do not prefix with '$' here. This string will be replaced
# at runtime with the generated working directory for the task
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
TRAINING_PREFIX = "trn"


class BaseTrainProcessor:
    def __init__(
        self, model: Model, image_layer: ImageLayer, config: Config = None
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
        self.runner = UnifiedRunner(
            runner_type=config.runner_type,
            config=self.config,
            pool_id=self.config.get_azure_batch_config()["training_pool_id"],
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
    ):
        super().__init__(model, image_layer, config)
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
            task_status = self.runner.get_task_status(
                job_id=self.model_data.trainingJob.jobId,
                task_id=self.model_data.trainingJob.taskId,
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
                self.model_data.trainingOutputPath = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{self.model_data.trainingJob.taskId}"
                # Add checkpointPath only for successful training
                self.model_data.checkpointPath = (
                    f"{self.model_data.trainingOutputPath}/checkpoint"
                )

                train_start_time, logs = self._get_training_logs()
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
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_data.trainingJob.jobId,
                    task_id=self.model_data.trainingJob.taskId,
                )

            elif task_status == self.config.get_status_types().FAILED.value:
                self.model_data.trainingJob.status = task_status
                self.model_data.trainingJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self.model_data.status = task_status
                self.model_data.trainingOutputPath = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{self.model_data.trainingJob.taskId}"

                # Retrieve error details from the batch task before cleanup
                error_details = self._get_task_error_details(
                    self.model_data.trainingJob.jobId,
                    self.model_data.trainingJob.taskId,
                )
                failure_message = "Training job failed"
                if error_details:
                    failure_message += f"\n{error_details}"
                self._update_training_progress(
                    failure_message, step=self.model_data.currentStep
                )
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_data.trainingJob.jobId,
                    task_id=self.model_data.trainingJob.taskId,
                )
            else:
                self.model_data.status = task_status
                self.model_data.trainingJob.status = task_status
                train_start_time, logs = self._get_training_logs()
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
            self.logger.info(
                f"Adding task for model training {self.model_data.modelId}"
            )
            command = (
                f'"cd /app '
                f'&& source scripts/set_dirs.sh ${BATCH_JOB_WORKDIR}/{experiment_input_files["config"]["file_path"]} '
                f"&& python scripts/print_gpu_info.py "
                f'&& python run_workflow.py --config ${BATCH_JOB_WORKDIR}/{experiment_input_files["config"]["file_path"]} --step training'
                '"'
            )
            job_id = self.config.get_azure_batch_config()[
                "training_batch_job_id"
            ]
            # Trim job_id to 64 characters to comply with Azure Batch limits
            job_id = job_id[:64]
            task_id = f"{TRAINING_PREFIX}-{MetadataUtils.generate_id()}"
            training_output_prefix = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{task_id}"
            self.runner.add_task(
                job_id=job_id,
                task_id=task_id,
                output_prefix=training_output_prefix,
                resource_files_for_upload=experiment_input_files,
                file_pattern=f"${BATCH_JOB_WORKDIR}/**/*",
                command=command,
                # NOTE: rename this config
                image_name=self.config.get_azure_batch_config()[
                    "docker_image"
                ],
            )
            self.logger.info(
                f"Completed add task {task_id} to job id {job_id} for model training {self.model_data.modelId}"
            )
            self.model_data.trainingJob = TrainingJob(
                jobId=job_id,
                taskId=task_id,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=self.config.get_status_types().IN_PROGRESS.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
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
        # including the SAS token results in batch job failing to download the blob with an InvalidAuthenticationInfo error
        plain_url_pattern = r"(.*)\?+"
        # Save the aliased labels as a geojson file to feed to the batch job
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
            experiment_dir=BATCH_JOB_WORKDIR,
            experiment_name=f"model_{self.model_data.modelId}",
            imagery=Imagery(
                normalization_means=self.image_layer.normalizationMeans,
                normalization_stds=self.image_layer.normalizationStds,
                num_channels=len(self.image_layer.normalizationMeans),
                raw_fn=f"{BATCH_JOB_WORKDIR}/{raw_fn}",
                rgb_fn=f"{BATCH_JOB_WORKDIR}/{rgb_fn}",
            ),
            labels=Labels(
                buffer_in_meters=3,  # default - add options on user input form to customize
                class_to_buffer="Building",  # default - add options on user input form to customize
                class_to_buffer_by="Background",  # default - add options on user input form to customize
                classes=label_classes,
                fn=f"{BATCH_JOB_WORKDIR}/{experiment_input_files['labels']['file_path']}",
            ),
            training=Training(
                batch_size=self.model_data.batchSize or 1,
                checkpoint_subdir="checkpoint",
                gpu_id=0,
                learning_rate=self.model_data.learningRate or 0.0001,
                log_dir=f"{BATCH_JOB_WORKDIR}/logs",
                max_epochs=self.model_data.maxEpochs or 1,
                initial_weights_fn=(
                    f"{BATCH_JOB_WORKDIR}/inputs/{initial_weights_filename}"
                    if self.model_data.initialWeightsUrl
                    else None
                ),
            ),
        )
        # Save the experiment config as a yaml file to feed to the batch job
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

    def _get_training_logs(self):
        # file_name = self.batch_cluster.get_file_by_match_from_task(job_id, task_id,'events.out.tfevents')
        # if file_name is None:
        #     return None,None
        # output = self.batch_cluster.get_file_from_task(job_id, task_id,file_name)
        content = self.runner.get_filecontent_from_task(
            job_id=self.model_data.trainingJob.jobId,
            task_id=self.model_data.trainingJob.taskId,
            filename="events.out.tfevents",
            as_chunk=True,
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

    def _get_task_error_details(self, job_id: str, task_id: str) -> str:
        """Retrieve user-safe error details from a failed batch task.

        Returns generic error lines from workflow_progress.log (which run_workflow.py
        sanitizes before writing). Raw stderr.txt is logged server-side only — never
        returned to callers, since it can contain stack traces, file paths, and other
        internal details that must not reach end users.

        Returns:
            A string with sanitized error details, or empty string if none found.
        """
        error_parts = []

        try:
            progress_content = self.runner.get_filecontent_from_task(
                job_id, task_id, "workflow_progress.log"
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
            stderr_content = self.runner.get_filecontent_from_task(
                job_id, task_id, "stderr.txt"
            )
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
        try:
            message = self.runner.cancel_task(
                job_id=self.model_data.trainingJob.jobId,
                task_id=self.model_data.trainingJob.taskId,
            )
            self.logger.info(
                f"Training task {self.model_data.trainingJob.taskId} cancellation message: {message}"
            )
            # Cleanup the task on the runner
            self.runner.cleanup_task(
                job_id=self.model_data.trainingJob.jobId,
                task_id=self.model_data.trainingJob.taskId,
            )
            self.model_data.trainingOutputPath = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{self.model_data.trainingJob.taskId}"
            # Note: Do we want to set checkpoint paths if available for cancelled model training tasks?
            return message
        except Exception as e:
            self.logger.error(
                f"Error cancelling training job {self.model_data.trainingJob.jobId} for model {self.model_data.modelId}: {e}",
                stack_info=True,
            )
            raise
