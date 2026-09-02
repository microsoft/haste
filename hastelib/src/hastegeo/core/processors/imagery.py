# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json
import os
from typing import Dict, NamedTuple, Optional

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.compute import (
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeWorkload,
    OutputNotAvailableError,
)
from ..models.projects import ImageLayer, ImageryPreprocessJob
from ..utils.blob import fetch_url_text
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

IMAGERY_PREFIX = "img"
IMAGERY_WORKLOAD = ComputeWorkload.IMAGERY_PREPARATION


def build_imagery_job_spec(
    *,
    image_layer: ImageLayer,
    execution_id: str,
    input_files: Dict[str, dict],
    config: Config,
    backend=None,
) -> ComputeJobSpec:
    """Build the backend-neutral spec for one imagery-preparation job.

    Same imagery-prep image and ``prepare-imagery`` invocation as before.
    Both output directories the pre-migration Azure Batch task uploaded
    are preserved: ``outputs/`` (COGs, previews, footprints, manifests)
    and ``logs/`` (the friendly progress log, which must survive node
    loss). Mounted live so the status dialog can follow the progress log
    while the job runs.
    """
    runtime = config.get_compute_runtime_config(IMAGERY_WORKLOAD)
    config_path = input_files["config"]["file_path"]
    command = (
        f'"mkdir -p {JOB_WORKDIR} '
        f"&& cd {JOB_WORKDIR} "
        f"&& prepare-imagery --config {JOB_WORKDIR}/{config_path}"
        '"'
    )
    prefix = output_prefix(image_layer.projectId, execution_id)
    return ComputeJobSpec(
        executionId=execution_id,
        workload=IMAGERY_WORKLOAD,
        backendPreference=resolve_backend_preference(
            requested=backend,
            workload=IMAGERY_WORKLOAD,
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
                # Progress log, so it survives the node being deallocated
                # or preempted once the task completes.
                pattern="logs/*.*",
                container_url=runtime["output_container_url"],
                prefix=prefix,
                live=True,
            ),
        ],
        resources=container_resources(runtime),
        timeoutSeconds=runtime["timeout_seconds"],
        tags=spec_tags(
            workload=IMAGERY_WORKLOAD,
            project_id=image_layer.projectId,
            task_id=execution_id,
            image_layer_id=image_layer.imageLayerId,
        ),
    )


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
        # Stable task/execution id minted before queueing and recorded on
        # a pending ImageryPreprocessJob; the postprocessor reuses it, so
        # a duplicate queue delivery cannot start a second provider job.
        self.image_data.preprocessJob = ImageryPreprocessJob(
            taskId=new_task_id(IMAGERY_PREFIX),
            imageLayerId=self.image_data.imageLayerId,
            projectId=self.image_data.projectId,
            status=self.config.get_status_types().PENDING.value,
            creationDate=MetadataUtils.get_timestamp(),
        )
        self.image_data.statusMessage = MetadataUtils.append_status_message(
            self.image_data.statusMessage, "Queued for processing"
        )
        self.queue.put_message(json.dumps(self.image_data.dict()), 0)
        self.logger.info(
            f"Image data queued for processing for project: {self.image_data.projectId} and image layer id: {self.image_data.imageLayerId}"
        )
        return self.image_data


class ImageryPostProcessor:
    def __init__(
        self,
        image_data: ImageLayer,
        config: Config = None,
        execution_service=None,
    ):
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
        # Injectable so tests can drive the processor with fake adapters.
        self.execution_service = (
            execution_service
            if execution_service is not None
            else build_execution_service(self.config)
        )
        self.queue = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["image_queue_name"],
            config.queue_config["queue_account_url"],
        )

    # -- compute handle plumbing --------------------------------------

    def _pending_task_id(self) -> str:
        job = self.image_data.preprocessJob
        if job is not None and job.taskId:
            return job.taskId
        return new_task_id(IMAGERY_PREFIX)

    def _imagery_output_uri(self, task_id: str) -> str:
        runtime = self.config.get_compute_runtime_config(IMAGERY_WORKLOAD)
        return output_uri(
            runtime["output_container_url"],
            output_prefix(self.image_data.projectId, task_id),
        )

    def _compute_handle(self) -> Optional[ComputeJobHandle]:
        job = self.image_data.preprocessJob
        if job is None:
            return None
        return resolve_compute_job_handle(
            job,
            output_uri=(
                self._imagery_output_uri(job.taskId) if job.taskId else None
            ),
        )

    def _require_handle(self) -> ComputeJobHandle:
        handle = self._compute_handle()
        if handle is None:
            raise ValueError(
                "Image layer "
                f"{self.image_data.imageLayerId} has no compute submission "
                "to poll"
            )
        return handle

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
            handle = self._require_handle()
            task_status = map_state_to_status(
                self.execution_service.get_status(handle), self.config
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
                # Record the imagery output path only once the
                # preprocessing job has succeeded - may not be needed
                self.image_data.imageryPath = f"{MetadataUtils.hash_string(self.image_data.projectId)}/imagery_{self.image_data.preprocessJob.taskId}"
                self._update_results_from_job(handle)
                logs = self._get_image_preprocess_logs(handle)
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

                # Release the execution's temporary resources
                self.execution_service.finalize(handle)

            elif task_status in (
                self.config.get_status_types().FAILED.value,
                self.config.get_status_types().CANCELLED.value,
            ):
                self.image_data.preprocessJob.status = task_status
                self.image_data.preprocessJob.completedDate = (
                    MetadataUtils.get_timestamp()
                )
                self.image_data.status = task_status
                logs = self._get_image_preprocess_logs(handle)
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
                # Release the execution's temporary resources
                self.execution_service.finalize(handle)
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
            # Optional server-side clip AOI ([w, s, e, n] EPSG:4326). When set,
            # prepare-imagery clips the pre/post mosaics to this box.
            "clip_bbox": self.image_data.clipBbox,
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
            f"Submitting preprocessing job for image layer id: {self.image_data.imageLayerId}"
        )
        task_id = self._pending_task_id()
        spec = build_imagery_job_spec(
            image_layer=self.image_data,
            execution_id=task_id,
            input_files=imagery_input_files,
            config=self.config,
            backend=self.image_data.computeBackend,
        )
        handle = self.execution_service.submit(
            spec, profile=compute_profile(IMAGERY_WORKLOAD)
        )
        self.logger.info(
            "Imagery preprocessing submitted for image layer %s: %s",
            self.image_data.imageLayerId,
            handle_log_fields(handle),
        )
        pending_job = self.image_data.preprocessJob
        self.image_data.preprocessJob = ImageryPreprocessJob(
            jobId=handle.providerJobId,
            taskId=handle.providerTaskId or handle.executionId,
            imageLayerId=self.image_data.imageLayerId,
            projectId=self.image_data.projectId,
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
            self.image_data.computeBackend = inherited
        self.image_data.status = (
            self.config.get_status_types().IN_PROGRESS.value
        )
        self._update_imagery_progress(
            f"Image preprocessing submitted with task id "
            f"{self.image_data.preprocessJob.taskId}",
            step=0,
        )
        self.queue.put_message(json.dumps(self.image_data.dict()))
        self.logger.info(
            f"InProgress message sent to queue for image layer {self.image_data.imageLayerId}"
        )
        return self.image_data

    def _read_task_output(
        self, handle: ComputeJobHandle, filename: str
    ) -> Optional[str]:
        """Return the text of a job output file, or ``None``.

        Reads the copy the compute backend still has first, then falls back to
        the copy uploaded to blob storage on completion. The node-local copy
        disappears as soon as the node is deallocated or preempted — which on
        autoscale pools happens the moment the task completes — so the blob
        copy is often the only one left by the time we look.
        """
        try:
            content = self.execution_service.read_output(handle, filename)
        except OutputNotAvailableError as exc:
            self.logger.info(
                "Output %s is not available from the compute backend for "
                "task %s: %s",
                filename,
                handle.executionId,
                exc,
            )
            content = None
        if content:
            return content

        task_id = handle.providerTaskId or handle.executionId
        self.logger.info(
            "%s not available from the compute backend for task %s; "
            "falling back to the uploaded copy in storage.",
            filename,
            task_id,
        )
        try:
            url = self.storage.get_file_remote_path(
                identifier=filename,
                extra_partition_keys=task_id,
                data_format=os.path.splitext(filename)[1].strip("."),
            )
            content = fetch_url_text(url)
        except Exception as e:
            # The fallback must never replace the original reason the file was
            # unreadable — callers decide whether a miss is fatal.
            self.logger.warning(
                "Fallback read of %s for task %s failed: %s",
                filename,
                task_id,
                e,
            )
            return None
        if not content:
            self.logger.warning(
                "%s for task %s is not available from the compute backend "
                "or storage.",
                filename,
                task_id,
            )
        return content

    def _get_image_preprocess_logs(self, handle: ComputeJobHandle):
        # Best-effort: the progress log is a nicety for the status dialog, so a
        # node that went away must not fail an otherwise successful layer.
        content = self._read_task_output(handle, "imagery_friendly.log")
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

    def _update_results_from_job(self, handle: ComputeJobHandle):
        """
        Update the image layer object with imagery processing results from the processed manifest file
        """
        content = self._read_task_output(handle, "imagery_manifest.json")
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
