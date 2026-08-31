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
from ..models.projects import ImageLayer, TrainingJob
from ..runners.unified_runner import UnifiedRunner
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler

# Do not prefix with '$'. Replaced at runtime with the task working dir.
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
FOOTPRINT_TILES_PREFIX = "ftl"
MANIFEST_FILENAME = "footprint_tiles_manifest.json"
FRIENDLY_LOG_FILENAME = "footprint_tiles_friendly.log"


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
    source_footprints_url: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Build a footprint-tiles queue message payload.

    Carries identifiers only; the trigger reads the authoritative state
    from metadata so a re-queued poll message and a fresh request take
    the same code path.
    """
    return {
        "projectId": project_id,
        "imageLayerId": image_layer_id,
        "sourceFootprintsUrl": source_footprints_url or "",
        "force": bool(force),
    }


def enqueue_footprint_tiles(
    project_id: str,
    image_layer_id: str,
    source_footprints_url: Optional[str] = None,
    force: bool = False,
    config: Optional[Config] = None,
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
        source_footprints_url=source_footprints_url,
        force=force,
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

    Mutates ``image_layer`` in place when a job is queued; the caller
    persists it.

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
    logger = Logger.get_logger(__name__)

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
        return _state(False)

    if not force and in_flight:
        # A job is already queued or running for this layer. Re-queueing
        # would submit a second task for the same archive.
        logger.info(
            "Footprint tiles for image layer %s already %s; not re-queueing",
            image_layer.imageLayerId,
            image_layer.footprintTilesStatus,
        )
        return _state(False)

    image_layer.footprintTilesStatus = statuses.PENDING.value
    image_layer.footprintTilesStatusMessage = (
        MetadataUtils.append_status_message(
            "", "Queued for footprint tile preparation"
        )
    )
    enqueue_footprint_tiles(
        project_id=image_layer.projectId,
        image_layer_id=image_layer.imageLayerId,
        source_footprints_url=image_layer.buildingFootprintsUrl,
        force=force,
        config=config,
    )
    logger.info(
        "Queued footprint tiles for image layer %s (force=%s)",
        image_layer.imageLayerId,
        force,
    )
    return _state(True)


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
                source_footprints_url=(self.image_layer.buildingFootprintsUrl),
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

        if status == statuses.PENDING.value:
            self._update_progress("Submitting footprint tile job")
            self._execute_job()

        elif status == statuses.IN_PROGRESS.value:
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
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                try:
                    self._update_results_from_job()
                    self.image_layer.footprintTilesStatus = task_status
                except Exception as error:
                    self.logger.error(
                        "Error finalizing footprint tiles for "
                        f"{self.layer_id}: {error}",
                        stack_info=True,
                    )
                    self.image_layer.footprintTilesStatus = (
                        statuses.FAILED.value
                    )
                    job.status = statuses.FAILED.value
                    self._update_progress(
                        f"Footprint tile job failed: {error}"
                    )
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
                self.image_layer.footprintTilesStatus = task_status
                job.status = task_status
                self.queue_client.put_message(self._poll_message())

        return self.image_layer

    def _execute_job(self) -> ImageLayer:
        statuses = self.config.get_status_types()
        try:
            input_files = self._create_job_config()
            config_path = input_files["config"]["file_path"]
            command = (
                f'"mkdir -p ${BATCH_JOB_WORKDIR} '
                f"&& cd ${BATCH_JOB_WORKDIR} "
                "&& python -m hastegeo.workflows.prepare_footprint_tiles "
                f'--config ${BATCH_JOB_WORKDIR}/{config_path}"'
            )
            job_id = self.config.get_azure_batch_config()[
                "training_batch_job_id"
            ][:64]
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
                image_name=self.config.get_azure_batch_config()[
                    "docker_image"
                ],
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
            self.queue_client.put_message(self._poll_message())
        except Exception as error:
            self.logger.error(
                f"Error submitting footprint tiles for {self.layer_id}: "
                f"{error}",
                stack_info=True,
            )
            self.image_layer.footprintTilesStatus = statuses.FAILED.value
            self._update_progress(f"Footprint tile job failed: {error}")
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
        job = self.image_layer.footprintTilesJob
        content = self.runner.get_filecontent_from_task(
            job_id=job.jobId,
            task_id=job.taskId,
            filename=MANIFEST_FILENAME,
        )
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
        return self.storage.get_file_remote_path(
            identifier=filename,
            extra_partition_keys=(
                f"{self.image_layer.footprintTilesJob.taskId}"
            ),
            data_format=os.path.splitext(filename)[1].strip("."),
        )

    def _replay_friendly_logs(self) -> None:
        for timestamp, message in self._get_friendly_logs():
            if message not in (
                self.image_layer.footprintTilesStatusMessage or ""
            ):
                self._update_progress(message, timestamp=timestamp)

    def _get_friendly_logs(self) -> List[Tuple[str, str]]:
        job = self.image_layer.footprintTilesJob
        content = self.runner.get_filecontent_from_task(
            job_id=job.jobId,
            task_id=job.taskId,
            filename=FRIENDLY_LOG_FILENAME,
        )
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
