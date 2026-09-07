# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import os
from typing import NamedTuple

from azure.core.exceptions import ResourceNotFoundError
from hastegeo.core.runners.unified_runner import UnifiedRunner

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.projects import ImageLayer, InferenceJob, Model, ModelArtifacts
from ..models.training import ExperimentConfig, Inference
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.prediction_attrs import attrs_artifact_name
from ..utils.queues import AzureQueueHandler
from .artifacts import ArtifactProcessor, _slugify_model_name
from .metadata import MetadataProcessor
from .prediction_results import validate_uploaded_pair

# Do not prefix with '$' here. This string will be replaced
# at runtime with the generated working directory for the task
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
INFERENCE_PREFIX = "inf"


def process_inference_request(
    request: Model, config: Config | None = None
) -> Model | None:
    """Use the stored Model, not the queued snapshot, and reject old task IDs.

    The final re-read is an ordinary freshness check, not metadata CAS.
    """
    config = config or Config()
    metadata = MetadataProcessor("model", request.projectId, config)
    try:
        record = metadata.load(request.modelId)
    except FileNotFoundError:
        return None
    if not record:
        return None
    model = Model.model_validate(record)
    if (
        request.currentInferenceTaskId != model.currentInferenceTaskId
        or request.imageLayerId != model.imageLayerId
    ):
        return None
    if model.inferenceStatus in (
        config.get_status_types().COMPLETED.value,
        config.get_status_types().FAILED.value,
    ):
        return None
    task_id, status, revision = (
        model.currentInferenceTaskId,
        model.inferenceStatus,
        model.predictionRevision,
    )
    if status == config.get_status_types().CANCELLED.value:
        processor = InferencePostprocessor(model, config=config)
        output = processor.cancel()
    else:
        layer = ImageLayer.model_validate(
            MetadataProcessor(
                config.get_metadata_types().IMAGELAYER.value,
                model.projectId,
                config,
            ).load(model.imageLayerId)
        )
        if (
            layer.projectId != model.projectId
            or layer.imageLayerId != model.imageLayerId
        ):
            raise ValueError("Inference layer does not match its model")
        experiment = ExperimentConfig.model_validate(
            MetadataProcessor(
                config.get_metadata_types().EXPERIMENT_CONFIG.value,
                model.projectId,
                config,
            ).load(model.modelId, data_format="yaml")
        )
        processor = InferencePostprocessor(model, layer, experiment, config)
        output = processor.process()
    try:
        latest = Model.model_validate(metadata.load(model.modelId))
    except FileNotFoundError:
        return None
    if (
        latest.currentInferenceTaskId,
        latest.inferenceStatus,
        latest.predictionRevision,
    ) != (task_id, status, revision):
        return None
    fields = {
        key: value
        for key, value in output.model_dump().items()
        if key.startswith("inference")
        or key in ("currentInferenceTaskId", "predictionGpkgFilename")
    }
    if output.inferenceStatus == config.get_status_types().COMPLETED.value:
        fields.update(
            output.model_dump(
                include={
                    "gpkgUrl",
                    "predictionAttrsUrl",
                    "predictionRevision",
                    "predictedBuildingCount",
                    "predictedAt",
                    "predictedDamageLayerUrl",
                }
            )
        )
    metadata.save(output.modelId, fields)
    if output.inferenceStatus == config.get_status_types().IN_PROGRESS.value:
        processor.queue_client.put_message(output.model_dump_json())
    return output


def enqueue_inference_artifacts(model: Model, config: Config) -> None:
    """Keep the existing zip follow-on, independent of result readiness."""
    if (
        model.inferenceStatus
        not in (
            config.get_status_types().COMPLETED.value,
            config.get_status_types().FAILED.value,
        )
        or not model.inferenceOutputPath
    ):
        return
    metadata = MetadataProcessor(
        data_type=config.get_metadata_types().MODEL_ARTIFACTS.value,
        partition_key=model.projectId,
        config=config,
    )
    try:
        record = metadata.load(model.modelId)
    except FileNotFoundError:
        record = None
    artifacts = ModelArtifacts.model_validate(
        record
        or {
            "projectId": model.projectId,
            "imageLayerId": model.imageLayerId,
            "modelId": model.modelId,
        }
    )
    output = ArtifactProcessor(
        partition_key=model.projectId,
        config=config,
        model=model,
        model_artifacts=artifacts,
    ).send_to_zip_queue()
    metadata.save(model.modelId, output.model_dump())


class BaseInferenceProcessor:
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
            candidate_pool_ids=self.config.get_azure_batch_config()[
                "inference_pool_ids"
            ],
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

    def send_to_queue(self, status: str | None = None) -> Model:
        metadata = MetadataProcessor(
            "model", self.model_data.projectId, self.config
        )
        record = metadata.load(self.model_data.modelId)
        if not record:
            raise FileNotFoundError("Model not found")
        model = Model.model_validate(record)
        if model.imageLayerId != self.model_data.imageLayerId:
            raise ValueError("Inference request does not match its model")
        fields = {
            "inferenceStatus": status
            or self.config.get_status_types().PENDING.value
        }
        if status != self.config.get_status_types().CANCELLED.value:
            fields.update(
                currentInferenceTaskId=f"{INFERENCE_PREFIX}-{MetadataUtils.generate_id()}",
                predictionGpkgFilename=self.config.get_artifact_types().INFERENCE_GPKG.value.substitute(
                    modelName=_slugify_model_name(model.name)
                )
                + ".gpkg",
                inferenceCurrentStep=0,
                inferenceTotalSteps=7,
                inferenceProgressPct=0.0,
                inferenceOutputPath=None,
                inferenceStatusMessage=MetadataUtils.append_status_message(
                    "", "Queued for inference"
                ),
            )
        metadata.save(model.modelId, fields)
        self.model_data = model.model_copy(update=fields)
        try:
            self.queue_client.put_message(self.model_data.model_dump_json())
        except Exception:
            latest = metadata.load(model.modelId)
            if (
                status != self.config.get_status_types().CANCELLED.value
                and latest.get("currentInferenceTaskId")
                == self.model_data.currentInferenceTaskId
            ):
                metadata.save(
                    model.modelId,
                    {
                        "inferenceStatus": self.config.get_status_types().FAILED.value
                    },
                )
            raise
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
    ):
        super().__init__(model, image_layer, config)
        self.model_data = model
        self.image_layer = image_layer
        self.experiment_config = experiment_config
        self.config = config or Config()
        self.queue_client = AzureQueueHandler(
            self.config.queue_config["queue_connection_string"],
            self.config.queue_config["inference_queue_name"],
            self.config.queue_config["queue_account_url"],
        )

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
            else:
                raise ValueError("Current inference task reference is missing")

            task_status = self.runner.get_task_status(
                inference_job.jobId, inference_job.taskId
            )

            self.logger.info(
                f"Task status for model {self.model_data.modelId} is {task_status}"
            )

            logs = self._get_inference_logs(
                inference_job.jobId, inference_job.taskId
            )
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
                # A local runner can finish while its upload failed. Check
                # actual artifact storage (not the node or a synthesized SAS).
                try:
                    self._complete_prediction_artifacts(inference_job.taskId)
                except (FileNotFoundError, ResourceNotFoundError, ValueError):
                    self.model_data.inferenceStatus = (
                        self.config.get_status_types().FAILED.value
                    )
                    inference_job.status = self.model_data.inferenceStatus
                    inference_job.completedDate = MetadataUtils.get_timestamp()
                    self._update_inference_progress(
                        "Uploaded prediction artifacts are missing or invalid; rerun inference."
                    )
                    return self.model_data
                self.model_data.inferenceStatus = task_status
                self.model_data.inferenceJobs[idx].status = task_status
                self.model_data.inferenceJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()

                self.model_data.inferenceOutputPath = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{self.model_data.inferenceJobs[idx].taskId}"

                self._update_inference_progress(
                    "Inference job completed successfully"
                )
                self.model_data.inferenceJobs[
                    idx
                ].logs = self.model_data.inferenceStatusMessage
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_data.inferenceJobs[idx].jobId,
                    task_id=self.model_data.inferenceJobs[idx].taskId,
                )

            elif task_status == self.config.get_status_types().FAILED.value:
                self.model_data.inferenceStatus = task_status
                self.model_data.inferenceJobs[idx].status = task_status
                self.model_data.inferenceJobs[
                    idx
                ].completedDate = MetadataUtils.get_timestamp()
                self.model_data.inferenceOutputPath = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{self.model_data.inferenceJobs[idx].taskId}"

                # Retrieve stderr from the batch task for additional error context
                stderr_detail = self._get_task_stderr(
                    inference_job.jobId, inference_job.taskId
                )
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
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.model_data.inferenceJobs[idx].jobId,
                    task_id=self.model_data.inferenceJobs[idx].taskId,
                )
            else:
                self.model_data.inferenceStatus = (
                    self.config.get_status_types().IN_PROGRESS.value
                )
                self.model_data.inferenceJobs[idx].status = task_status
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
            task_id = (
                self.model_data.currentInferenceTaskId
                or f"{INFERENCE_PREFIX}-{MetadataUtils.generate_id()}"
            )
            self.model_data.currentInferenceTaskId = task_id
            self.model_data.predictionGpkgFilename = self.model_data.predictionGpkgFilename or (
                self.config.get_artifact_types().INFERENCE_GPKG.value.substitute(
                    modelName=_slugify_model_name(self.model_data.name)
                )
                + ".gpkg"
            )
            inference_input_files = self._create_inference_config()
            # Multiple inference outputs are stored, but the visualizer imagery is set to the last completed job
            command = (
                f'"cd /app '
                f'&& source scripts/set_dirs.sh ${BATCH_JOB_WORKDIR}/{inference_input_files["config"]["file_path"]} '
                f"&& python scripts/print_gpu_info.py "
                f'&& python run_workflow.py --config ${BATCH_JOB_WORKDIR}/{inference_input_files["config"]["file_path"]} --step inference'
                '"'
            )
            job_id = self.config.get_azure_batch_config()[
                "inference_batch_job_id"
            ]
            # Trim job_id to 64 characters to comply with Azure Batch limits
            job_id = job_id[:64]
            inference_output_prefix = f"{MetadataUtils.hash_string(self.model_data.projectId)}/{task_id}"

            job_id, task_id = self.runner.add_task(
                job_id=job_id,
                task_id=task_id,
                output_prefix=inference_output_prefix,
                resource_files_for_upload=inference_input_files,
                file_pattern=f"${BATCH_JOB_WORKDIR}/inference/**/*",
                command=command,
                env_vars={
                    "GDAL_TRANSLATE_PARAMS": self.config.gdal_translate_params,
                },
                image_name=self.config.get_azure_batch_config()[
                    "docker_image"
                ],
            )
            self.logger.info(
                f"Completed add task {task_id} to job id {job_id} for model inference {self.model_data.modelId}"
            )
            self.model_data.inferenceJobs.append(
                InferenceJob(
                    jobId=job_id,
                    taskId=task_id,
                    modelId=self.model_data.modelId,
                    projectId=self.model_data.projectId,
                    status=self.config.get_status_types().IN_PROGRESS.value,
                    creationDate=MetadataUtils.get_timestamp(),
                )
            )
            self.model_data.currentInferenceTaskId = task_id
            self.model_data.inferenceStatus = (
                self.config.get_status_types().IN_PROGRESS.value
            )
            self._update_inference_progress(
                f"Inference submitted with task id {task_id}", step=0
            )
        except Exception as e:
            self.logger.error(
                "Inference submission failed (%s)",
                type(e).__name__,
            )
            if not isinstance(e, ValueError):
                raise RuntimeError(
                    f"Inference submission failed ({type(e).__name__})"
                ) from None
            self._update_inference_progress(
                "Inference configuration is invalid; check the model and cached footprints.",
                step=self.model_data.inferenceCurrentStep,
            )
            self.model_data.inferenceStatus = (
                self.config.get_status_types().FAILED.value
            )

        return self.model_data

    def _complete_prediction_artifacts(self, task_id: str) -> None:
        storage = UnifiedArtifactStorage(
            self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )
        namespace = [
            MetadataUtils.hash_string(self.model_data.projectId),
            task_id,
        ]
        if self.config.runner_type == "local":
            namespace.append("inference")
        names = {
            "gpkgUrl": self.model_data.predictionGpkgFilename,
            "predictionAttrsUrl": attrs_artifact_name(self.model_data.modelId),
            "predictedDamageLayerUrl": self.config.get_artifact_types().VISUALIZER.value.substitute(
                projectId=self.model_data.projectId,
                imageLayerId=self.model_data.imageLayerId,
            )
            + ".tif",
        }
        attributes = validate_uploaded_pair(
            storage,
            storage.get_file_path(names["gpkgUrl"], namespace),
            storage.get_file_path(names["predictionAttrsUrl"], namespace),
            task_id,
            "inference",
        )
        urls = {
            field: storage.get_download_url(
                identifier=name, extra_partition_keys=namespace
            )
            for field, name in names.items()
        }
        for field, url in urls.items():
            setattr(self.model_data, field, url)
        self.model_data.predictedBuildingCount = attributes.n
        self.model_data.predictedAt = MetadataUtils.get_timestamp()
        self.model_data.predictionRevision = task_id

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
        # if SAS token is included then batch job fails to download the blob with an InvalidAuthenticationInfo error
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
        if not self.model_data.checkpointPath:
            raise ValueError("Model has no checkpoint for inference")
        artifacts = UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )
        checkpoint_url = artifacts.get_download_url(
            identifier=checkpoint_version,
            extra_partition_keys=self.model_data.checkpointPath,
        )
        inference_input_files["checkpoint"] = {
            "http_url": extract_from_url(checkpoint_url, plain_url_pattern),
            "file_path": f"inputs/checkpoint/{checkpoint_version}",
        }

        # Load the experiment config that was saved during training
        inference_config_id = f"{self.model_data.modelId}-{self.model_data.currentInferenceTaskId}"
        # Create a copy of the existing experiment config and update inference configuration
        updated_experiment_config = self.experiment_config.model_dump()

        # Create inference configuration using pydantic model for consistency
        inference_config = Inference(
            batch_size=1,
            checkpoint_fn=f"{BATCH_JOB_WORKDIR}/inputs/checkpoint/{checkpoint_version}",
            gpu_id=0,
            output_subdir="inference",
            padding=64,
            patch_size=256,
            building_footprints_source="microsoft",
            country_alpha2_iso_code="US",
            predictions_gpkg_fileprefix=self.model_data.predictionGpkgFilename.removesuffix(
                ".gpkg"
            ),
            prediction_attrs_filename=attrs_artifact_name(
                self.model_data.modelId
            ),
            prediction_revision=self.model_data.currentInferenceTaskId,
        )

        # Update inference settings for the inference run
        updated_experiment_config["inference"] = inference_config.model_dump()

        # Save the updated experiment config with inference settings
        self.storage.save(
            identifier=inference_config_id,
            data=updated_experiment_config,
            data_type=self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )
        config_filepath = self.storage.get_file_remote_path(
            inference_config_id,
            self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            data_format="yaml",
        )
        inference_input_files["config"] = {
            "http_url": extract_from_url(config_filepath, plain_url_pattern),
            "file_path": f"inputs/{extract_from_url(config_filepath, filename_pattern)}",
        }
        return inference_input_files

    def _get_inference_logs(self, job_id: str, task_id: str):
        content = self.runner.get_filecontent_from_task(
            job_id, task_id, "workflow_progress.log"
        )
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

    def _get_task_stderr(self, job_id: str, task_id: str) -> str:
        """Log stderr from a failed batch task server-side for admin diagnostics.

        Raw stderr can contain stack traces, file paths, and other internal details
        that must not reach end users. This method always returns an empty string;
        the content is recorded only via the server-side logger.
        """
        try:
            stderr_content = self.runner.get_filecontent_from_task(
                job_id, task_id, "stderr.txt"
            )
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

    def _cancel_inference(self) -> None:
        if not self.model_data.currentInferenceTaskId:
            return  # Cancellation before submission has no Batch task.
        job = next(
            (
                job
                for job in self.model_data.inferenceJobs or []
                if job.taskId == self.model_data.currentInferenceTaskId
            ),
            None,
        )
        if job is None:
            return  # A queued task may not have been submitted yet.
        job.status = self.config.get_status_types().CANCELLED.value
        job.completedDate = MetadataUtils.get_timestamp()
        try:
            self.runner.cancel_task(
                job_id=job.jobId,
                task_id=job.taskId,
            )
        except Exception as error:
            self.logger.error(
                "Inference task cancellation failed (%s)",
                type(error).__name__,
            )
            raise RuntimeError("Inference task cancellation failed") from None
