# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Build and track an image layer's shared footprint vector tiles.

Every map that draws a layer's buildings needs the same PMTiles archive of
that layer's cached footprints. Geometry belongs to the layer, so the
archive is built once — when imagery prep finishes caching the footprints
— and shared by every model trained on it.

``tippecanoe`` ships only in the training docker image, so the work cannot
run inline in an Azure Functions handler. This module is the seam:

* :func:`enqueue_footprint_tiles` puts an identifiers-only message on the
  footprint-tiles queue. Imagery prep calls it; nothing waits on it.
* :class:`FootprintTilesPreprocessor` is driven from the queue trigger and
  walks one job through submit -> poll -> finalize, recording state on the
  ``ImageLayer`` itself (``footprintTilesStatus`` / ``footprintTilesJob``
  / ``footprintTilesStatusMessage``) and the resulting archive on
  ``ImageLayer.footprintPmtilesUrl``.

The queue message carries identifiers only. Authoritative state is read
from metadata, so a fresh request and the preprocessor's own poll messages
take the same path and a duplicate message is a no-op rather than a second
container job.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.footprint_tiles import FootprintTilesRequest
from ..models.projects import ImageLayer, TrainingJob
from ..runners.unified_runner import UnifiedRunner
from ..utils.blob import fetch_url_text
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler
from .metadata import MetadataProcessor

# Do not prefix with '$'. Replaced at runtime with the task working dir.
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
FOOTPRINT_TILES_PREFIX = "ftl"
MANIFEST_FILENAME = "footprint_tiles_manifest.json"
FRIENDLY_LOG_FILENAME = "footprint_tiles_friendly.log"
FOOTPRINT_TILE_FIELDS = {
    "footprintPmtilesUrl",
    "footprintTilesJob",
    "footprintTilesStatus",
    "footprintTilesStatusMessage",
    "footprintTilesRequestId",
}


def pmtiles_artifact_name(image_layer_id: str) -> str:
    """Artifact name for a layer's footprint PMTiles archive."""
    return (
        ArtifactTypes.LAYER_FOOTPRINT_PMTILES.value.substitute(
            imageLayerId=image_layer_id
        )
        + ".pmtiles"
    )


def layer_needs_footprint_tiles(image_layer: ImageLayer) -> bool:
    """Report whether a tiling job is worth queueing for this layer.

    Tiles can only be built once the footprints GeoPackage is cached, and
    there is no point rebuilding an archive the layer already has.
    """
    return bool(image_layer.buildingFootprintsUrl) and not bool(
        image_layer.footprintPmtilesUrl
    )


def build_tiles_message(
    project_id: str,
    image_layer_id: str,
    force: bool = False,
    request_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a footprint-tiles queue message payload.

    Carries identifiers only; the trigger reads the authoritative state
    from metadata so a re-queued poll message and a fresh request take
    the same code path.
    """
    return FootprintTilesRequest(
        projectId=project_id,
        imageLayerId=image_layer_id,
        force=force,
        requestId=request_id or MetadataUtils.generate_id(),
        taskId=task_id,
    ).model_dump(exclude_none=True)


def enqueue_footprint_tiles(
    project_id: str,
    image_layer_id: str,
    force: bool = False,
    config: Optional[Config] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Put a tiling request on the footprint-tiles queue.

    Convenience seam for imagery prep, which may not run ``tippecanoe``
    inline. Returns the enqueued message.
    """
    if config is None:
        config = Config()
    message = build_tiles_message(
        project_id=project_id,
        image_layer_id=image_layer_id,
        force=force,
        request_id=request_id,
    )
    queue_client = AzureQueueHandler(
        config.queue_config["queue_connection_string"],
        config.queue_config["footprint_tiles_queue_name"],
        config.queue_config["queue_account_url"],
    )
    queue_client.put_message(json.dumps(message), visibility_timeout=0)
    return message


def request_preparation(
    image_layer: ImageLayer,
    force: bool = False,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Decide whether to enqueue a tiling job, and do it if so.

    The caller supplies an authoritative, already-persisted image layer.
    Persist PENDING before publishing, and never save the caller's stale
    snapshot after publishing: a consumer may already have advanced it.
    Queue failures are recorded as FAILED (unless a consumer advanced the
    request despite an ambiguous send failure), then propagated.

    Returns:
        ``{"imageLayerId", "queued", "tilesReady", "status",
        "statusMessage"}``.

    Raises:
        ValueError: when the layer has no cached building footprints, so
            there is nothing to tile.
    """
    if config is None:
        config = Config()
    statuses = config.get_status_types()
    metadata = MetadataProcessor(
        data_type=config.get_metadata_types().IMAGELAYER.value,
        partition_key=image_layer.projectId,
        config=config,
    )

    if not image_layer.buildingFootprintsUrl:
        raise ValueError(
            f"Image layer {image_layer.imageLayerId} has no cached "
            "building footprints; footprint tiles cannot be built "
            "without them."
        )

    needs_tiles = layer_needs_footprint_tiles(image_layer)
    in_flight = image_layer.footprintTilesStatus in (
        statuses.PENDING.value,
        statuses.IN_PROGRESS.value,
    )

    def _state(queued: bool) -> Dict[str, Any]:
        return {
            "imageLayerId": image_layer.imageLayerId,
            "queued": queued,
            "tilesReady": not layer_needs_footprint_tiles(image_layer),
            "status": image_layer.footprintTilesStatus,
            "statusMessage": image_layer.footprintTilesStatusMessage or "",
        }

    if in_flight:
        # Force is not cancellation. Duplicates must keep the active job,
        # even while a forced rebuild still has the old archive available.
        return _state(False)

    if not force and not needs_tiles:
        # The archive already exists: record the transition once rather
        # than paying for a redundant container job.
        if image_layer.footprintTilesStatus != statuses.COMPLETED.value:
            image_layer.footprintTilesStatus = statuses.COMPLETED.value
            image_layer.footprintTilesStatusMessage = (
                MetadataUtils.append_status_message(
                    image_layer.footprintTilesStatusMessage,
                    "Footprint tiles already available",
                )
            )
            _save_tiles(metadata, image_layer)
        return _state(False)

    _initialize_request(image_layer, MetadataUtils.generate_id(), config)
    _save_tiles(metadata, image_layer)
    try:
        enqueue_footprint_tiles(
            project_id=image_layer.projectId,
            image_layer_id=image_layer.imageLayerId,
            force=force,
            request_id=image_layer.footprintTilesRequestId,
            config=config,
        )
    except Exception:
        current = metadata.load(image_layer.imageLayerId)
        if (
            current
            and current.get("footprintTilesRequestId")
            == image_layer.footprintTilesRequestId
            and current.get("footprintTilesStatus") == statuses.PENDING.value
        ):
            image_layer.footprintTilesStatus = statuses.FAILED.value
            image_layer.footprintTilesStatusMessage = (
                MetadataUtils.append_status_message(
                    image_layer.footprintTilesStatusMessage,
                    "Could not queue footprint tiles; request preparation "
                    "again to retry",
                )
            )
            _save_tiles(metadata, image_layer)
        raise
    return _state(True)


def _initialize_request(
    image_layer: ImageLayer, request_id: str, config: Config
) -> None:
    image_layer.footprintTilesRequestId = request_id
    image_layer.footprintTilesJob = None
    image_layer.footprintTilesStatus = config.get_status_types().PENDING.value
    image_layer.footprintTilesStatusMessage = (
        MetadataUtils.append_status_message(
            "", "Queued for footprint tile preparation"
        )
    )


def _save_tiles(metadata: MetadataProcessor, image_layer: ImageLayer) -> None:
    # MetadataProcessor merges top-level fields. Do not overwrite imagery
    # or label work with a snapshot taken by the footprint consumer.
    metadata.save(
        image_layer.imageLayerId,
        image_layer.model_dump(include=FOOTPRINT_TILE_FIELDS),
    )


def process_tiles_request(
    request: FootprintTilesRequest, config: Optional[Config] = None
) -> Optional[ImageLayer]:
    """Load authoritative state, advance it, save, then publish a poll.

    Fresh/failed layers can be recovered by an identifiers-only request;
    ready layers require force. Task-specific polls never initialize work
    and stale polls are discarded. Invalid requests (including layers with
    no cached footprints) raise; deleted layers are a no-op.

    Metadata uses the existing read/merge/write contract, not CAS. Ordering
    prevents our own fast consumers/stale outer saves from losing state;
    this is not a cross-worker lock or an atomic Batch/metadata transaction.
    """
    if config is None:
        config = Config()
    if not request.requestId:
        raise ValueError("A stable request identity is required")
    metadata = MetadataProcessor(
        data_type=config.get_metadata_types().IMAGELAYER.value,
        partition_key=request.projectId,
        config=config,
    )
    try:
        record = metadata.load(request.imageLayerId)
    except FileNotFoundError:
        return None
    if not record:
        return None
    layer = ImageLayer.model_validate(record)
    if (
        layer.projectId != request.projectId
        or layer.imageLayerId != request.imageLayerId
    ):
        raise ValueError("Footprint request does not match layer metadata")

    statuses = config.get_status_types()
    in_flight = layer.footprintTilesStatus in (
        statuses.PENDING.value,
        statuses.IN_PROGRESS.value,
    )
    if request.taskId:
        if (
            not in_flight
            or not layer.footprintTilesJob
            or layer.footprintTilesJob.taskId != request.taskId
        ):
            return layer
    elif not in_flight:
        if layer.footprintTilesRequestId == request.requestId:
            return layer  # Terminal redelivery, including force.
        if layer.footprintPmtilesUrl and not request.force:
            return layer

    if not layer.buildingFootprintsUrl:
        raise ValueError("Image layer has no cached building footprints")
    if not in_flight:
        _initialize_request(layer, request.requestId, config)
        _save_tiles(metadata, layer)
    elif not layer.footprintTilesRequestId:
        # Adopt legacy PENDING/IN_PROGRESS work without resetting its job.
        # Its first validated delivery must also be idempotent at terminal
        # state, especially if this delivery requested force.
        layer.footprintTilesRequestId = request.requestId
        _save_tiles(metadata, layer)

    processor = FootprintTilesPreprocessor(layer, config=config)
    output = processor.process()
    _save_tiles(metadata, output)
    if output.footprintTilesStatus == statuses.IN_PROGRESS.value:
        # A failed send propagates for queue retry. The saved task reference
        # makes that retry a poll rather than a second task submission.
        processor.queue_client.put_message(processor._poll_message())
    return output


class FootprintTilesPreprocessor:
    """Submit, poll and finalize one layer's footprint tiling job.

    Mirrors the other container-job preprocessors: ``process()`` advances
    the state machine by exactly one step and returns the image layer,
    which the caller persists.
    """

    def __init__(
        self,
        image_layer: ImageLayer,
        config: Optional[Config] = None,
    ) -> None:
        if config is None:
            config = Config()
        if image_layer is None:
            raise ValueError(
                "FootprintTilesPreprocessor requires an image layer."
            )
        self.config = config
        self.image_layer = image_layer
        self.project_id = image_layer.projectId
        self.storage = UnifiedDataLayer(
            storage_type=config.storage_type,
            partition_key=self.project_id,
            **config.storage_config,
        )
        self.logger = Logger.get_logger(__name__)
        self.runner = UnifiedRunner(
            runner_type=config.runner_type,
            config=self.config,
            pool_id=self.config.get_azure_batch_config()["training_pool_id"],
            candidate_pool_ids=self.config.get_azure_batch_config()[
                "training_pool_ids"
            ],
        )
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["footprint_tiles_queue_name"],
            config.queue_config["queue_account_url"],
        )

    @property
    def layer_id(self) -> str:
        return self.image_layer.imageLayerId

    def _poll_message(self) -> str:
        """Message that brings this job back for another status poll."""
        return json.dumps(
            build_tiles_message(
                project_id=self.project_id,
                image_layer_id=self.layer_id,
                request_id=self.image_layer.footprintTilesRequestId,
                task_id=self.image_layer.footprintTilesJob.taskId,
            )
        )

    def process(self) -> ImageLayer:
        """Advance the job state machine by one step."""
        self.logger.info(
            "FootprintTilesPreprocessor.process: image layer %s status %s",
            self.layer_id,
            self.image_layer.footprintTilesStatus,
        )
        statuses = self.config.get_status_types()
        status = self.image_layer.footprintTilesStatus

        if (
            status == statuses.PENDING.value
            and self.image_layer.footprintTilesJob is None
        ):
            self._update_progress("Submitting footprint tile job")
            self._execute_job()

        elif status in (
            statuses.PENDING.value,
            statuses.IN_PROGRESS.value,
        ):
            job = self.image_layer.footprintTilesJob
            if job is None:
                self.image_layer.footprintTilesStatus = statuses.FAILED.value
                self._update_progress(
                    "Footprint tile job reference is missing; cannot poll "
                    "for completion"
                )
                return self.image_layer

            task_status = self.runner.get_task_status(
                job_id=job.jobId, task_id=job.taskId
            )
            self.logger.info(
                "Task status for footprint tiles of %s is %s",
                self.layer_id,
                task_status,
            )

            if task_status == statuses.COMPLETED.value:
                try:
                    self._update_results_from_job()
                    self.image_layer.footprintTilesStatus = task_status
                except (FileNotFoundError, ValueError) as error:
                    self.logger.error(
                        "Invalid footprint tile manifest (%s)",
                        type(error).__name__,
                    )
                    self.image_layer.footprintTilesStatus = (
                        statuses.FAILED.value
                    )
                    self._update_progress(
                        "Footprint tile job failed: missing or invalid manifest"
                    )
                # Retrieval failures must leave both the layer and job
                # active, with no cleanup, so the queue delivery can retry.
                job.status = self.image_layer.footprintTilesStatus
                job.completedDate = MetadataUtils.get_timestamp()
                self._replay_friendly_logs()
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)

            elif task_status == statuses.FAILED.value:
                self.image_layer.footprintTilesStatus = task_status
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                self._replay_friendly_logs()
                self._update_progress("Footprint tile job failed")
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)
            else:
                # A queued Batch task is still an active submission, not
                # a fresh PENDING layer that should be submitted again.
                self.image_layer.footprintTilesStatus = (
                    statuses.IN_PROGRESS.value
                )
                job.status = task_status

        return self.image_layer

    def _execute_job(self) -> ImageLayer:
        statuses = self.config.get_status_types()
        input_files = self._create_job_config()
        config_path = input_files["config"]["file_path"]
        command = (
            f'"mkdir -p ${BATCH_JOB_WORKDIR} '
            f"&& cd ${BATCH_JOB_WORKDIR} "
            "&& python -m hastegeo.workflows.prepare_footprint_tiles "
            f'--config ${BATCH_JOB_WORKDIR}/{config_path}"'
        )
        job_id = self.config.get_azure_batch_config()["training_batch_job_id"][
            :64
        ]
        task_id = f"{FOOTPRINT_TILES_PREFIX}-{MetadataUtils.generate_id()}"
        output_prefix = (
            f"{MetadataUtils.hash_string(self.project_id)}/{task_id}"
        )
        job_id, task_id = self.runner.add_task(
            job_id=job_id,
            task_id=task_id,
            output_prefix=output_prefix,
            resource_files_for_upload=input_files,
            file_pattern=f"${BATCH_JOB_WORKDIR}/outputs/*.*",
            command=command,
            image_name=self.config.get_azure_batch_config()["docker_image"],
        )
        self.image_layer.footprintTilesJob = TrainingJob(
            jobId=job_id,
            taskId=task_id,
            modelId=None,
            projectId=self.project_id,
            status=statuses.IN_PROGRESS.value,
            creationDate=MetadataUtils.get_timestamp(),
        )
        self.image_layer.footprintTilesStatus = statuses.IN_PROGRESS.value
        self._update_progress(
            f"Footprint tiles submitted with task id {task_id}"
        )
        return self.image_layer

    def _create_job_config(self) -> Dict[str, Dict[str, str]]:
        """Write the workflow config and describe the task input files."""
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.project_id)}/(.*)\?+"
        )
        plain_url_pattern = r"(.*)\?+"

        footprints_url = self.image_layer.buildingFootprintsUrl
        if not footprints_url:
            raise ValueError("Image layer has no building footprints.")
        footprints_fn = (
            f"inputs/{extract_from_url(footprints_url, filename_pattern)}"
        )

        workflow_config: Dict[str, Any] = {
            "project_id": self.project_id,
            "image_layer_id": self.layer_id,
            "output_dir": "outputs",
            # Relative to the task working dir: the command cd's into
            # $AZ_BATCH_TASK_WORKING_DIR before running the workflow.
            "files": {
                "footprints": footprints_fn,
                "pmtiles": pmtiles_artifact_name(self.layer_id),
            },
            "store_artifacts": True,
        }

        config_type = (
            self.config.get_metadata_types().FOOTPRINT_TILES_CONFIG.value
        )
        self.storage.save(
            identifier=self.layer_id,
            data=workflow_config,
            data_type=config_type,
            data_format="json",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.layer_id, config_type, data_format="json"
        )
        config_fn = (
            f"inputs/{extract_from_url(config_filepath, filename_pattern)}"
        )

        return {
            "config": {
                "http_url": extract_from_url(
                    config_filepath, plain_url_pattern
                ),
                "file_path": config_fn,
            },
            "footprints": {
                "http_url": extract_from_url(
                    footprints_url, plain_url_pattern
                ),
                "file_path": footprints_fn,
            },
        }

    def _update_results_from_job(self) -> None:
        """Persist the archive URL and count from the task manifest."""
        content = self._read_task_output(MANIFEST_FILENAME, required=True)
        if not content:
            raise FileNotFoundError(
                f"Footprint tiles manifest not found for {self.layer_id}"
            )
        manifest = json.loads(content)

        pmtiles_url = manifest.get("pmtiles_url") or self._artifact_url(
            manifest.get("pmtiles_filename", "")
        )
        if not pmtiles_url:
            raise ValueError(
                "Footprint tiles manifest carries no PMTiles URL for image "
                f"layer {self.layer_id}"
            )
        self.image_layer.footprintPmtilesUrl = pmtiles_url
        self._update_progress(
            "Prepared footprint tiles for "
            f"{int(manifest.get('building_count', 0))} buildings"
        )

    def _artifact_url(self, filename: str) -> str:
        """Resolve a task output filename to a downloadable URL."""
        if not filename:
            return ""
        try:
            return self.storage.get_file_remote_path(
                identifier=filename,
                extra_partition_keys=(
                    f"{self.image_layer.footprintTilesJob.taskId}"
                ),
                data_format=os.path.splitext(filename)[1].strip("."),
            )
        except Exception as error:
            # Resolving either the manifest or its archive is a retrieval
            # operation, not manifest validation (even for ValueError).
            raise RuntimeError(
                "Footprint task output URL resolution failed "
                f"({type(error).__name__})"
            ) from None

    def _replay_friendly_logs(self) -> None:
        for timestamp, message in self._get_friendly_logs():
            if message not in (
                self.image_layer.footprintTilesStatusMessage or ""
            ):
                self._update_progress(message, timestamp=timestamp)

    def _read_task_output(
        self, filename: str, *, required: bool = False
    ) -> Optional[str]:
        """Read node output, then its uploaded copy after node deallocation.

        Only confirmed absence is a missing required output. Retrieval
        failures must retry, not turn a successful Batch task into a
        terminal failure. Friendly logs remain entirely best effort.
        """
        job = self.image_layer.footprintTilesJob
        try:
            content = self.runner.get_filecontent_from_task(
                job_id=job.jobId,
                task_id=job.taskId,
                filename=filename,
            )
            if content:
                return content
            return fetch_url_text(
                self._artifact_url(filename), strict=required
            )
        except Exception as error:
            # URLs and SDK exception text can contain credentials.
            if required:
                # Keep even ValueError/FileNotFoundError from URL resolution
                # out of the terminal manifest-validation failure path.
                raise RuntimeError(
                    "Required footprint task output retrieval failed "
                    f"({type(error).__name__})"
                ) from None
            self.logger.warning(
                "Optional footprint task output unavailable (%s)",
                type(error).__name__,
            )
            return None

    def _get_friendly_logs(self) -> List[Tuple[str, str]]:
        content = self._read_task_output(FRIENDLY_LOG_FILENAME)
        logs: List[Tuple[str, str]] = []
        if content:
            for record in content.splitlines():
                if not record:
                    continue
                parts = record.split("|", 1)
                if len(parts) == 2:
                    logs.append((parts[0], parts[1]))
        return logs

    def _update_progress(
        self, message: str, timestamp: Optional[str] = None
    ) -> None:
        self.image_layer.footprintTilesStatusMessage = (
            MetadataUtils.append_status_message(
                self.image_layer.footprintTilesStatusMessage or "",
                message,
                timestamp=timestamp,
            )
        )
