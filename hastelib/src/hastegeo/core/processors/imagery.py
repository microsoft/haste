# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
from typing import NamedTuple

from hastegeo.core.runners.unified_runner import UnifiedRunner

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.projects import ImageLayer, ImageryPreprocessJob
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler

BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
IMAGERY_PREFIX = "img"


class ImageryLogRecord(NamedTuple):
    """
    Named tuple representing a log record for imagery processing operations.

    This structure captures timestamped log messages generated during imagery
    preprocessing workflows, providing structured logging for debugging and
    progress tracking.

    Attributes:
        timestamp (str): ISO formatted timestamp when the log message was created
        message (str): Descriptive log message about the processing operation

    Example:
        ```python
        log_record = ImageryLogRecord(
            timestamp="2023-08-01T12:00:00Z",
            message="Starting imagery preprocessing for layer img_123"
        )
        print(log_record)  # "2023-08-01T12:00:00Z: Starting imagery preprocessing..."
        ```
    """

    timestamp: str
    message: str

    def __str__(self):
        return f"{self.timestamp}: {self.message}"

    def __repr__(self):
        return f"{self.timestamp}: {self.message}"


class ImageryPreProcessor:
    """
    Processor for handling satellite and aerial imagery preprocessing workflows.

    This class manages the complete imagery preprocessing pipeline including download,
    validation, mosaic creation, and Cloud Optimized GeoTIFF (COG) generation.
    It integrates with Azure Batch services for scalable processing and Azure Queue
    Storage for asynchronous job management.

    The processor handles both pre-event and post-event imagery for change detection
    and damage assessment workflows, supporting multiple imagery sources and formats.

    Args:
        image_data (ImageLayer): Image layer model containing imagery metadata and URLs
        config (Config, optional): Configuration object with environment settings.
            Defaults to None, which creates a new Config instance.

    Attributes:
        image_data (ImageLayer): The image layer being processed
        logger (Logger): Logger instance for tracking processing operations
        queue (AzureQueueHandler): Queue handler for asynchronous job management
        config (Config): Configuration object with system settings

    Raises:
        ValueError: If image_data is not a valid ImageLayer instance

    Example:
        ```python
        # Create image layer with pre and post event imagery
        image_layer = ImageLayer(
            imageLayerId="layer_123",
            projectId="proj_456",
            preEventImageryUrls=["https://storage/pre_event.tif"],
            postEventImageryUrls=["https://storage/post_event.tif"]
        )

        # Initialize processor and queue for processing
        processor = ImageryPreProcessor(image_layer)
        processor.queue_for_processing()
        ```

    Note:
        The processor supports various imagery sources including Sentinel-2,
        Landsat, WorldView, and other satellite/aerial imagery formats.
        All processing operations are designed to handle large-scale imagery
        datasets efficiently through cloud-based batch processing.
    """

    def __init__(self, image_data: ImageLayer, config: Config = None):
        if not isinstance(image_data, ImageLayer):
            raise ValueError(f"{self.__class__.__name__}: Invalid image data.")
        if config is None:
            config = Config()
        self.image_data = image_data
        self.logger = Logger.get_logger(__name__)
        self.queue = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["image_queue_name"],
            config.queue_config["queue_account_url"],
        )
        self.config = config

    def queue_for_processing(self):
        """
        Queue the imagery layer for asynchronous preprocessing.

        This method prepares the image layer for processing by setting initial
        status values and sending the layer data to the Azure Queue for
        asynchronous processing by background workers.

        The method sets up progress tracking with 4 total processing steps:
        1. Download and validation of imagery files
        2. Mosaic creation for multi-file imagery
        3. Cloud Optimized GeoTIFF (COG) generation
        4. Metadata updates and finalization

        Updates the image layer status to PENDING and resets progress indicators
        before queuing the processing job.

        Returns:
            ImageLayer: The updated image layer with processing status set to PENDING

        Example:
            ```python
            processor = ImageryPreProcessor(image_layer)
            updated_layer = processor.queue_for_processing()
            print(f"Layer {updated_layer.imageLayerId} queued with status: {updated_layer.status}")
            ```

        Note:
            The actual processing is handled asynchronously by Azure Queue
            consumers. This method only queues the job and updates initial status.
        """
        self.image_data.status = self.config.get_status_types().PENDING.value
        self.image_data.currentStep = 0
        self.image_data.totalSteps = 4
        self.image_data.progressPct = 0.0
        self.image_data.statusMessage = MetadataUtils.append_status_message(
            self.image_data.statusMessage, "Queued for processing"
        )
        self.queue.put_message(json.dumps(self.image_data.dict()), 0)
        self.logger.info(
            f"Image data queued for processing for project: {self.image_data.projectId} and image layer id: {self.image_data.imageLayerId}"
        )
        return self.image_data


class ImageryPostProcessor:
    def __init__(self, image_data: ImageLayer, config: Config = None):
        if not isinstance(image_data, ImageLayer):
            raise ValueError(f"{self.__class__.__name__}: Invalid image data.")
        if config is None:
            config = Config()
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=image_data.projectId,
            **config.storage_config,
        )
        self.gdal_warp_params = config.gdal_warp_params
        self.gdal_translate_params = config.gdal_translate_params
        self.image_data = image_data
        self.fine_tune = image_data.autoFineTune
        self.source_type_pre_event = image_data.sourceTypePreEvent
        self.source_type_post_event = image_data.sourceTypePostEvent
        self.logger = Logger.get_logger(__name__)
        self.config = config
        self.process_id = MetadataUtils.generate_short_int_id()
        self.runner = UnifiedRunner(
            runner_type=config.runner_type,
            config=self.config,
            pool_id=self.config.get_azure_batch_config()["imageprep_pool_id"],
            candidate_pool_ids=self.config.get_azure_batch_config()[
                "imageryprep_pool_ids"
            ],
        )
        self.queue = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["image_queue_name"],
            config.queue_config["queue_account_url"],
        )

    def process(self):
        self.logger.info(
            f"{self.__class__.__name__}.process: Processing image data for project: {self.image_data.projectId} and image layer id: {self.image_data.imageLayerId}"
        )

        if (
            self.image_data.status
            == self.config.get_status_types().PENDING.value
        ):
            self.logger.info(
                f"Executing preprocess for image layer id: {self.image_data.imageLayerId}"
            )
            self._update_imagery_progress(
                "Submitting image preprocessing task", step=0
            )
            self.image_data = self._execute_image_preprocess()
        elif (
            self.image_data.status
            == self.config.get_status_types().IN_PROGRESS.value
        ):
            task_status = self.runner.get_task_status(
                job_id=self.image_data.preprocessJob.jobId,
                task_id=self.image_data.preprocessJob.taskId,
            )

            self.logger.info(
                f"Task status for image layer {self.image_data.imageLayerId} is {task_status}"
            )

            if task_status == self.config.get_status_types().COMPLETED.value:
                self.image_data.status = task_status
                self.image_data.preprocessJob.status = task_status
                self.image_data.preprocessJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                # Add imageryPath only for successful training - may not be needed
                self.image_data.imageryPath = f"{MetadataUtils.hash_string(self.image_data.projectId)}/imagery_{self.image_data.preprocessJob.taskId}"
                self._update_results_from_job()
                logs = self._get_image_preprocess_logs()
                if logs:
                    for log in logs:
                        if log.message not in self.image_data.statusMessage:
                            self._update_imagery_progress(
                                log.message, timestamp=log.timestamp
                            )
                        # Also update the logs for the specific job
                    self.image_data.preprocessJob.logs = (
                        self.image_data.statusMessage
                    )

                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.image_data.preprocessJob.jobId,
                    task_id=self.image_data.preprocessJob.taskId,
                )

            elif task_status == self.config.get_status_types().FAILED.value:
                self.image_data.preprocessJob.status = task_status
                self.image_data.preprocessJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self.image_data.status = task_status
                logs = self._get_image_preprocess_logs()
                if logs:
                    for log in logs:
                        if log.message not in self.image_data.statusMessage:
                            self._update_imagery_progress(
                                log.message, timestamp=log.timestamp
                            )
                self._update_imagery_progress(
                    "Preprocess job failed", step=self.image_data.currentStep
                )
                # Also update the logs for the specific job
                self.image_data.preprocessJob.logs = (
                    self.image_data.statusMessage
                )
                # Cleanup the task on the runner
                self.runner.cleanup_task(
                    job_id=self.image_data.preprocessJob.jobId,
                    task_id=self.image_data.preprocessJob.taskId,
                )
            else:
                self.image_data.status = task_status
                self.image_data.preprocessJob.status = task_status
                self.queue.put_message(json.dumps(self.image_data.dict()))

        return self.image_data

    def _execute_image_preprocess(self):
        image_preprocess_config = {
            "project_id": self.image_data.projectId,
            "image_layer_id": self.image_data.imageLayerId,
            "pre_event_imagery_urls": self.image_data.preEventImageryUrls,
            "post_event_imagery_urls": self.image_data.postEventImageryUrls,
            "source_type_pre_event": self.source_type_pre_event,
            "source_type_post_event": self.source_type_post_event,
            "fine_tune": self.fine_tune,
            # When the user supplied a custom building-footprint GPKG at
            # layer-creation time, prepare-imagery skips the Overture
            # download and instead clips/reprojects this file to EPSG:4326
            # against the post-event AOI.
            "user_building_footprints_url": (
                self.image_data.userBuildingFootprintsUrl
            ),
        }
        self.storage.save(
            identifier=self.image_data.imageLayerId,
            data=image_preprocess_config,
            data_type=self.config.get_metadata_types().IMAGERY_CONFIG.value,
            data_format="yaml",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.image_data.imageLayerId,
            self.config.get_metadata_types().IMAGERY_CONFIG.value,
            data_format="yaml",
        )
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.image_data.projectId)}/(.*)\?+"
        )
        plain_url_pattern = r"(.*)\?+"
        imagery_input_files = {
            "config": {
                "http_url": extract_from_url(
                    config_filepath, plain_url_pattern
                ),
                "file_path": f"{extract_from_url(config_filepath, filename_pattern)}",
            }
        }

        self.logger.info(
            f"Adding task for preprocessing image layer id: {self.image_data.imageLayerId}"
        )
        command = (
            f'"mkdir -p ${BATCH_JOB_WORKDIR} '
            f"&& cd ${BATCH_JOB_WORKDIR} "
            f'&& prepare-imagery --config ${BATCH_JOB_WORKDIR}/{imagery_input_files["config"]["file_path"]}'
            '"'
        )
        job_id = self.config.get_azure_batch_config()[
            "imageryprep_batch_job_id"
        ]
        # Trim job_id to 64 characters to comply with Azure Batch limits
        job_id = job_id[:64]
        task_id = f"{IMAGERY_PREFIX}-{MetadataUtils.generate_id()}"
        imagery_output_prefix = (
            f"{MetadataUtils.hash_string(self.image_data.projectId)}/{task_id}"
        )
        self.runner.add_task(
            job_id=job_id,
            task_id=task_id,
            output_prefix=imagery_output_prefix,
            resource_files_for_upload=imagery_input_files,
            file_pattern=f"${BATCH_JOB_WORKDIR}/outputs/*.*",
            command=command,
            # TODO: maybe this needs to be encapsulated in the batch runner and not be part of the processor
            image_name=self.config.get_azure_batch_config()[
                "imageprep_docker_image"
            ],
        )
        self.logger.info(
            f"Completed add task {task_id} to job id {job_id} for preprocessing image layer {self.image_data.imageLayerId}"
        )
        self.image_data.preprocessJob = ImageryPreprocessJob(
            jobId=job_id,
            taskId=task_id,
            imageLayerId=self.image_data.imageLayerId,
            projectId=self.image_data.projectId,
            status=self.config.get_status_types().IN_PROGRESS.value,
            creationDate=MetadataUtils.get_timestamp(),
        )
        self.image_data.status = (
            self.config.get_status_types().IN_PROGRESS.value
        )
        self._update_imagery_progress(
            f"Image preprocessing submitted with task id {task_id}", step=0
        )
        self.queue.put_message(json.dumps(self.image_data.dict()))
        self.logger.info(
            f"InProgress message sent to queue for image layer {self.image_data.imageLayerId}"
        )
        return self.image_data

    def _get_image_preprocess_logs(self):
        content = self.runner.get_filecontent_from_task(
            job_id=self.image_data.preprocessJob.jobId,
            task_id=self.image_data.preprocessJob.taskId,
            filename="imagery_friendly.log",
        )
        logs = []
        if content:
            try:
                logs = [
                    ImageryLogRecord(*record.split("|"))
                    for record in content.splitlines()
                    if record
                ]
            except Exception as e:
                self.logger.error(
                    f"Error parsing imagery log record: {e}", stack_info=True
                )
                # suggests data contract with run_imagery_preprocess.py is broken
                raise
        return logs

    def _update_imagery_progress(
        self, message: str, step: int = None, timestamp: str = None
    ):
        if step is not None:
            self.image_data.currentStep = int(step)
        else:
            self.image_data.currentStep += 1
        self.image_data.progressPct = round(
            int(self.image_data.currentStep)
            / int(self.image_data.totalSteps)
            * 100,
            2,
        )
        self.image_data.statusMessage = MetadataUtils.append_status_message(
            self.image_data.statusMessage, message, timestamp=timestamp
        )

    def _update_results_from_job(self):
        """
        Update the image layer object with imagery processing results from the processed manifest file
        """
        content = self.runner.get_filecontent_from_task(
            job_id=self.image_data.preprocessJob.jobId,
            task_id=self.image_data.preprocessJob.taskId,
            filename="imagery_manifest.json",
        )
        if not content:
            raise FileNotFoundError(
                f"Processed manifest file not found for image layer id: {self.image_data.imageLayerId}"
            )

        processed_manifest = json.loads(content)

        for pre_event_preview_fn in processed_manifest[
            "preview_pre_event_filenames"
        ]:
            url = self._generate_imagery_url(
                filename=pre_event_preview_fn,
                imagery_type=self.config.get_artifact_types().PRE_EVENT_PREVIEW,
            )
            if url:
                self.image_data.preEventPreviewUrls.append(url)

        self.image_data.preEventMosaicCogImageryUrl = (
            self._generate_imagery_url(
                filename=processed_manifest["pre_event_mosaic_filename"],
                imagery_type=self.config.get_artifact_types().PRE_EVENT_MOSAIC,
            )
        )

        self.image_data.preEventProcessedImageryUrl = self._generate_imagery_url(
            filename=processed_manifest["pre_event_processed_filename"],
            imagery_type=self.config.get_artifact_types().PRE_EVENT_PROCESSED_COG,
        )

        for post_event_fn in processed_manifest[
            "preview_post_event_filenames"
        ]:
            url = self._generate_imagery_url(
                filename=post_event_fn,
                imagery_type=self.config.get_artifact_types().POST_EVENT_PREVIEW,
            )
            if url:
                self.image_data.postEventPreviewUrls.append(url)

        self.image_data.postEventMosaicCogImageryUrl = self._generate_imagery_url(
            filename=processed_manifest["post_event_mosaic_filename"],
            imagery_type=self.config.get_artifact_types().POST_EVENT_MOSAIC,
        )

        self.image_data.postEventProcessedImageryUrl = self._generate_imagery_url(
            filename=processed_manifest["post_event_processed_filename"],
            imagery_type=self.config.get_artifact_types().POST_EVENT_PROCESSED_COG,
        )

        self.image_data.normalizationMeans = processed_manifest.get(
            "normalization_means", []
        )

        self.image_data.normalizationStds = processed_manifest.get(
            "normalization_stds", []
        )

        # Cached building-footprints GPKG (either Overture-derived or
        # user-supplied via ImageLayer.userBuildingFootprintsUrl, depending
        # on which branch prepare-imagery took). The imageryprep subprocess
        # records any failure in ``building_footprints_error`` rather than
        # raising (so the imagery COGs still upload). Here we honor that
        # and flip the image layer to FAILED with the captured message,
        # since downstream inference can't run without the gpkg.
        building_footprints_filename = processed_manifest.get(
            "building_footprints_filename", ""
        )
        self.image_data.buildingFootprintsUrl = self._generate_imagery_url(
            filename=building_footprints_filename,
            imagery_type=self.config.get_artifact_types().BUILDING_FOOTPRINTS,
        )
        building_footprints_error = processed_manifest.get(
            "building_footprints_error", ""
        )
        if building_footprints_error:
            self.image_data.status = (
                self.config.get_status_types().FAILED.value
            )
            self.image_data.preprocessJob.status = self.image_data.status
            self._update_imagery_progress(
                f"Building footprints unavailable — {building_footprints_error}",
                step=self.image_data.currentStep,
            )
            self.image_data.preprocessJob.logs = self.image_data.statusMessage

        # Valid-area mask GeoJSON. Surfaced as a downloadable artifact;
        # a missing mask is not by itself a layer failure (the matching
        # AOI failure is already reported via building_footprints_error
        # above when the two share root cause).
        valid_area_mask_filename = processed_manifest.get(
            "valid_area_mask_filename", ""
        )
        self.image_data.validAreaMaskUrl = self._generate_imagery_url(
            filename=valid_area_mask_filename,
            imagery_type=self.config.get_artifact_types().VALID_AREA_MASK,
        )

    def _generate_imagery_url(
        self, filename: str, imagery_type: ArtifactTypes, validate=True
    ):
        """
        Validate the imagery name against the type and generate a URL.
        """

        expected_prefix = imagery_type.value.substitute(
            projectId=self.image_data.projectId,
            imageLayerId=self.image_data.imageLayerId,
        )
        url = ""
        if filename:
            if validate:
                assert filename.startswith(
                    expected_prefix
                ), f"Expected imagery name of type {imagery_type.name} to start with {expected_prefix}, but got {filename}"
            url = self.storage.get_file_remote_path(
                identifier=filename,
                extra_partition_keys=f"{self.image_data.preprocessJob.taskId}",
                data_format=os.path.splitext(filename)[1].strip("."),
            )
        return url
