# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Prediction-tiles job: queue + execute the prediction editor's data prep.

The prediction editor needs every predicted building footprint of an
image layer in the browser. That means two derived artifacts:

* the layer's footprint PMTiles (built once per image layer, reused by
  every model on it), and
* the model's columnar prediction attribute sidecar.

Both are produced by ``hastegeo.workflows.prepare_prediction_tiles``,
which shells out to ``tippecanoe``. tippecanoe ships ONLY in the
training docker image (``docker/training/env/env.yml``), so this work
can never run inline in the Azure Functions app: the preprocessor drops
a message on the prediction-tiles queue and the postprocessor submits a
task to the training image through the unified runner, exactly like
``processors/embedding.py`` does for the embedding workflow.

State lives in ``Model.predictionTilesStatus`` rather than
``Model.status`` so preparing tiles never disturbs the model's own
train/inference lifecycle (same separation the zip flow uses with
``ModelArtifacts.zipStatus``).

Config JSON handed to the workflow::

    {
      "project_id": "...",
      "image_layer_id": "...",
      "model_id": "...",
      "output_dir": "outputs",
      "files": {
        "footprints": "inputs/<footprints>.gpkg",
        "predictions": "inputs/<predictions>.gpkg",
        "pmtiles": "footprints_<imageLayerId>.pmtiles",
        "attrs": "prediction_attrs_<modelId>.json"
      },
      "tiles": {"build_pmtiles": true},
      "store_artifacts": true
    }

Queue message (``prediction-edit-prep-queue``)::

    {
      "projectId": "...",
      "imageLayerId": "...",
      "modelId": "...",
      "sourceGpkgUrl": "...",
      "sourceFootprintsUrl": "...",
      "force": false
    }

The trigger treats the message as a *request* and reads the authoritative
state from metadata, so the postprocessor's own poll re-queues (which
carry the full model document) are handled by the same code path.

:func:`request_preparation` is the HTTP-side entry point (used by
``PutPreparePredictionTilesQueueMessage``): it decides whether anything
still has to be built and enqueues at most one job per model.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ..config import ArtifactTypes, Config
from ..data_layer.unified import UnifiedDataLayer
from ..models.projects import ImageLayer, Model, TrainingJob
from ..runners.unified_runner import UnifiedRunner
from ..utils.data import extract_from_url
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.queues import AzureQueueHandler

# Do not prefix with '$'. Replaced at runtime with the task working dir.
BATCH_JOB_WORKDIR = "AZ_BATCH_TASK_WORKING_DIR"
PREDICTION_TILES_PREFIX = "ptl"
MANIFEST_FILENAME = "prediction_tiles_manifest.json"
FRIENDLY_LOG_FILENAME = "prediction_tiles_friendly.log"


def pmtiles_artifact_name(image_layer_id: str) -> str:
    """Artifact name for a layer's footprint PMTiles archive."""
    return (
        ArtifactTypes.LAYER_FOOTPRINT_PMTILES.value.substitute(
            imageLayerId=image_layer_id
        )
        + ".pmtiles"
    )


def attrs_artifact_name(model_id: str) -> str:
    """Artifact name for a model's prediction attribute sidecar."""
    return (
        ArtifactTypes.PREDICTION_ATTRS.value.substitute(modelId=model_id)
        + ".json"
    )


def build_prep_message(
    project_id: str,
    image_layer_id: str,
    model_id: str,
    source_gpkg_url: Optional[str] = None,
    source_footprints_url: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Build a ``prediction-edit-prep-queue`` message payload.

    The message only carries identifiers; the queue trigger reads the
    authoritative state from metadata so that re-queued poll messages
    and fresh requests take the same code path.
    """
    return {
        "projectId": project_id,
        "imageLayerId": image_layer_id,
        "modelId": model_id,
        "sourceGpkgUrl": source_gpkg_url or "",
        "sourceFootprintsUrl": source_footprints_url or "",
        "force": bool(force),
    }


def enqueue_prediction_tiles(
    project_id: str,
    image_layer_id: str,
    model_id: str,
    source_gpkg_url: Optional[str] = None,
    source_footprints_url: Optional[str] = None,
    force: bool = False,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Put a preparation request on the prediction-edit prep queue.

    Convenience seam for the HTTP layer, which must never run
    ``tippecanoe`` inline. Returns the enqueued message.
    """
    if config is None:
        config = Config()
    message = build_prep_message(
        project_id=project_id,
        image_layer_id=image_layer_id,
        model_id=model_id,
        source_gpkg_url=source_gpkg_url,
        source_footprints_url=source_footprints_url,
        force=force,
    )
    queue_client = AzureQueueHandler(
        config.queue_config["queue_connection_string"],
        config.queue_config["prediction_edit_prep_queue_name"],
        config.queue_config["queue_account_url"],
    )
    queue_client.put_message(json.dumps(message), visibility_timeout=0)
    return message


def resolve_tiles_url(model: Model, image_layer: ImageLayer) -> Optional[str]:
    """Return the PMTiles archive the editor should read, if any.

    The embedding workflow already tiles the same footprints from the
    same PMTiles archive, keyed on the same integer row-index ``id``
    (see ``workflows/embed_buildings.py``), so those tiles are reused
    rather than rebuilt. Only trained-inference models need a layer
    level archive built for them.
    """
    return model.pmtilesUrl or image_layer.footprintPmtilesUrl


def needs_preparation(
    model: Model, image_layer: ImageLayer
) -> Tuple[bool, bool]:
    """Decide what still has to be built for this model/layer pair.

    Returns:
        ``(needs_pmtiles, needs_attrs)``. Footprint tiles are shared by
        every model on a layer, so they are only built when neither the
        model nor the layer already has a usable archive.
    """
    needs_pmtiles = not bool(resolve_tiles_url(model, image_layer))
    needs_attrs = not bool(model.predictionAttrsUrl)
    return needs_pmtiles, needs_attrs


class PredictionTilesUnavailableError(ValueError):
    """Nothing can be prepared for this model/layer pair as it stands.

    Raised when the raw inputs the job would tile do not exist yet (the
    model has no prediction GeoPackage, or the layer has no cached
    building footprints). The HTTP layer maps this to a 404: it is a
    missing prerequisite, not a malformed request.
    """


def request_preparation(
    model: Model,
    image_layer: ImageLayer,
    force: bool = False,
    config: Optional[Config] = None,
) -> Dict[str, Any]:
    """Decide whether to enqueue preparation, and do it if so.

    The API seam behind ``PutPreparePredictionTilesQueueMessage``. All of
    the decision-making lives here so the HTTP handler stays a thin
    wrapper: it loads the two documents, calls this, persists ``model``
    and serializes the returned dict.

    This is the *request* half of :class:`PredictionTilesPreprocessor`
    (which is driven from the queue side and returns only the model);
    the HTTP caller additionally needs to know whether a job was
    actually queued and what the UI should poll for.

    Args:
        model: The model whose attribute sidecar is needed. Mutated in
            place — the caller persists it.
        image_layer: The model's image layer, which owns the shared
            footprint PMTiles.
        force: Rebuild even when both artifacts already exist, or when a
            job is already in flight. Used after predictions are
            regenerated, which leaves stale artifacts behind.
        config: Optional config override (tests inject a fake).

    Returns:
        ``{"modelId", "queued", "tilesReady", "attrsReady", "status",
        "statusMessage"}``. ``tilesReady``/``attrsReady`` describe the
        state *now*, so a caller that polls sees them flip to ``True``
        once the queued job finishes.

    Raises:
        PredictionTilesUnavailableError: when the model has no raw
            prediction GeoPackage or the layer has no cached building
            footprints, i.e. there is nothing to tile.
    """
    if config is None:
        config = Config()
    statuses = config.get_status_types()
    logger = Logger.get_logger(__name__)

    if not model.gpkgUrl:
        raise PredictionTilesUnavailableError(
            f"Model {model.modelId} has no prediction GeoPackage "
            "(gpkgUrl); run inference before preparing prediction tiles."
        )
    if not image_layer.buildingFootprintsUrl:
        raise PredictionTilesUnavailableError(
            f"Image layer {image_layer.imageLayerId} has no cached "
            "building footprints; prediction tiles cannot be built "
            "without them."
        )

    needs_pmtiles, needs_attrs = needs_preparation(model, image_layer)
    in_flight = model.predictionTilesStatus in (
        statuses.PENDING.value,
        statuses.IN_PROGRESS.value,
    )

    def _state(queued: bool) -> Dict[str, Any]:
        return {
            "modelId": model.modelId,
            "queued": queued,
            "tilesReady": not needs_pmtiles,
            "attrsReady": not needs_attrs,
            "status": model.predictionTilesStatus,
            "statusMessage": model.predictionTilesStatusMessage or "",
        }

    if not force and not needs_pmtiles and not needs_attrs:
        # Both artifacts exist: record that and skip the queue rather
        # than pay for a redundant Batch task. Only the transition is
        # recorded — an editor that re-opens a prepared model must not
        # grow the status message a line at a time.
        if model.predictionTilesStatus != statuses.COMPLETED.value:
            model.predictionTilesStatus = statuses.COMPLETED.value
            model.predictionTilesStatusMessage = (
                MetadataUtils.append_status_message(
                    model.predictionTilesStatusMessage,
                    "Prediction tiles already available",
                )
            )
        return _state(False)

    if not force and in_flight:
        # A job is already queued or running for this model. Re-queueing
        # would submit a second Batch task for the same artifacts; the
        # caller just polls the status it already has.
        logger.info(
            "Prediction tiles for model %s already %s; not re-queueing",
            model.modelId,
            model.predictionTilesStatus,
        )
        return _state(False)

    model.predictionTilesStatus = statuses.PENDING.value
    model.predictionTilesStatusMessage = MetadataUtils.append_status_message(
        "", "Queued for prediction tile preparation"
    )
    enqueue_prediction_tiles(
        project_id=model.projectId,
        image_layer_id=image_layer.imageLayerId,
        model_id=model.modelId,
        source_gpkg_url=model.gpkgUrl,
        source_footprints_url=image_layer.buildingFootprintsUrl,
        force=force,
        config=config,
    )
    logger.info(
        "Queued prediction tiles for model %s (pmtiles=%s, attrs=%s, "
        "force=%s)",
        model.modelId,
        needs_pmtiles or force,
        needs_attrs or force,
        force,
    )
    return _state(True)


class PredictionTilesPreprocessor:
    """Validate a request and enqueue the prediction-tiles job."""

    def __init__(
        self,
        model: Model,
        image_layer: Optional[ImageLayer] = None,
        config: Optional[Config] = None,
    ) -> None:
        if config is None:
            config = Config()
        self.config = config
        self.model_data = model
        self.image_layer = image_layer
        self.logger = Logger.get_logger(__name__)
        self.queue_client = AzureQueueHandler(
            config.queue_config["queue_connection_string"],
            config.queue_config["prediction_edit_prep_queue_name"],
            config.queue_config["queue_account_url"],
        )

    def queue_for_processing(self, force: bool = False) -> Model:
        """Queue the model for tile/sidecar preparation.

        Args:
            force: Rebuild even when both artifacts already exist (used
                after predictions are regenerated).

        Returns:
            The updated model. When nothing has to be built the model is
            marked COMPLETED and no message is enqueued.

        Raises:
            ValueError: when the model has no prediction GeoPackage or
                the layer has no cached building footprints — without
                either of those there is nothing to tile.
        """
        if self.image_layer is None:
            raise ValueError(
                "PredictionTilesPreprocessor requires the model's image "
                "layer to decide whether footprint tiles are needed."
            )
        if not self.model_data.gpkgUrl:
            raise ValueError(
                f"Model {self.model_data.modelId} has no prediction "
                "GeoPackage (gpkgUrl); run inference before preparing "
                "prediction tiles."
            )
        if not self.image_layer.buildingFootprintsUrl:
            raise ValueError(
                f"Image layer {self.image_layer.imageLayerId} has no "
                "cached building footprints; prediction tiles cannot be "
                "built without them."
            )

        needs_pmtiles, needs_attrs = needs_preparation(
            self.model_data, self.image_layer
        )
        if not force and not needs_pmtiles and not needs_attrs:
            self.model_data.predictionTilesStatus = (
                self.config.get_status_types().COMPLETED.value
            )
            self.model_data.predictionTilesStatusMessage = (
                MetadataUtils.append_status_message(
                    self.model_data.predictionTilesStatusMessage,
                    "Prediction tiles already available",
                )
            )
            return self.model_data

        self.model_data.predictionTilesStatus = (
            self.config.get_status_types().PENDING.value
        )
        self.model_data.predictionTilesStatusMessage = (
            MetadataUtils.append_status_message(
                "", "Queued for prediction tile preparation"
            )
        )
        self.queue_client.put_message(
            json.dumps(
                build_prep_message(
                    project_id=self.model_data.projectId,
                    image_layer_id=self.image_layer.imageLayerId,
                    model_id=self.model_data.modelId,
                    source_gpkg_url=self.model_data.gpkgUrl,
                    source_footprints_url=(
                        self.image_layer.buildingFootprintsUrl
                    ),
                    force=force,
                )
            ),
            visibility_timeout=0,
        )
        self.logger.info(
            "Queued prediction tiles for model %s (pmtiles=%s, attrs=%s)",
            self.model_data.modelId,
            needs_pmtiles or force,
            needs_attrs or force,
        )
        return self.model_data


class PredictionTilesPostprocessor:
    """Submit, poll and finalize the prediction-tiles Batch task."""

    def __init__(
        self,
        model: Model,
        image_layer: ImageLayer,
        config: Optional[Config] = None,
    ) -> None:
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
            config.queue_config["prediction_edit_prep_queue_name"],
            config.queue_config["queue_account_url"],
        )

    def _poll_message(self) -> str:
        """Message that brings this model back for another status poll."""
        footprints_url = self.image_layer.buildingFootprintsUrl
        return json.dumps(
            build_prep_message(
                project_id=self.model_data.projectId,
                image_layer_id=self.image_layer.imageLayerId,
                model_id=self.model_data.modelId,
                source_gpkg_url=self.model_data.gpkgUrl,
                source_footprints_url=footprints_url,
            )
        )

    def process(self) -> Model:
        """Advance the job state machine by one step.

        The caller persists both ``self.model_data`` and
        ``self.image_layer``: the footprint tiles belong to the layer,
        the attribute sidecar to the model.
        """
        self.logger.info(
            "%s.process: model %s prediction tiles status %s",
            self.__class__.__name__,
            self.model_data.modelId,
            self.model_data.predictionTilesStatus,
        )
        statuses = self.config.get_status_types()

        if self.model_data.predictionTilesStatus == statuses.PENDING.value:
            self._update_progress("Submitting prediction tile job")
            self.model_data = self._execute_job()

        elif (
            self.model_data.predictionTilesStatus == statuses.IN_PROGRESS.value
        ):
            job = self.model_data.predictionTilesJob
            if job is None:
                self.model_data.predictionTilesStatus = statuses.FAILED.value
                self._update_progress(
                    "Prediction tile job reference is missing; cannot "
                    "poll for completion"
                )
                return self.model_data

            task_status = self.runner.get_task_status(
                job_id=job.jobId, task_id=job.taskId
            )
            self.logger.info(
                "Task status for prediction tiles of model %s is %s",
                self.model_data.modelId,
                task_status,
            )

            if task_status == statuses.COMPLETED.value:
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                try:
                    self._update_results_from_job()
                    self.model_data.predictionTilesStatus = task_status
                except Exception as error:
                    self.logger.error(
                        "Error finalizing prediction tiles for model "
                        f"{self.model_data.modelId}: {error}",
                        stack_info=True,
                    )
                    self.model_data.predictionTilesStatus = (
                        statuses.FAILED.value
                    )
                    job.status = statuses.FAILED.value
                    self._update_progress(
                        f"Prediction tile job failed: {error}"
                    )
                self._replay_friendly_logs()
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)

            elif task_status == statuses.FAILED.value:
                self.model_data.predictionTilesStatus = task_status
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                self._replay_friendly_logs()
                self._update_progress("Prediction tile job failed")
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)
            else:
                self.model_data.predictionTilesStatus = task_status
                job.status = task_status
                self.queue_client.put_message(self._poll_message())

        return self.model_data

    # ── submission ────────────────────────────────────────────────────
    def _execute_job(self) -> Model:
        statuses = self.config.get_status_types()
        try:
            input_files = self._create_job_config()
            config_path = input_files["config"]["file_path"]
            command = (
                f'"mkdir -p ${BATCH_JOB_WORKDIR} '
                f"&& cd ${BATCH_JOB_WORKDIR} "
                "&& python -m hastegeo.workflows.prepare_prediction_tiles "
                f'--config ${BATCH_JOB_WORKDIR}/{config_path}"'
            )
            job_id = self.config.get_azure_batch_config()[
                "training_batch_job_id"
            ][:64]
            task_id = (
                f"{PREDICTION_TILES_PREFIX}-{MetadataUtils.generate_id()}"
            )
            output_prefix = (
                f"{MetadataUtils.hash_string(self.model_data.projectId)}"
                f"/{task_id}"
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
            self.model_data.predictionTilesJob = TrainingJob(
                jobId=job_id,
                taskId=task_id,
                modelId=self.model_data.modelId,
                projectId=self.model_data.projectId,
                status=statuses.IN_PROGRESS.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
            self.model_data.predictionTilesStatus = statuses.IN_PROGRESS.value
            self._update_progress(
                f"Prediction tiles submitted with task id {task_id}"
            )
            self.queue_client.put_message(self._poll_message())
        except Exception as error:
            self.logger.error(
                "Error submitting prediction tiles for model "
                f"{self.model_data.modelId}: {error}",
                stack_info=True,
            )
            self.model_data.predictionTilesStatus = statuses.FAILED.value
            self._update_progress(f"Prediction tile job failed: {error}")
        return self.model_data

    def _create_job_config(self) -> Dict[str, Dict[str, str]]:
        """Write the workflow config and describe the task input files."""
        filename_pattern = (
            rf"{MetadataUtils.hash_string(self.model_data.projectId)}/(.*)\?+"
        )
        plain_url_pattern = r"(.*)\?+"

        footprints_url = self.image_layer.buildingFootprintsUrl
        predictions_url = self.model_data.gpkgUrl
        if not footprints_url:
            raise ValueError("Image layer has no building footprints.")
        if not predictions_url:
            raise ValueError("Model has no prediction GeoPackage.")

        footprints_fn = (
            f"inputs/{extract_from_url(footprints_url, filename_pattern)}"
        )
        predictions_fn = (
            f"inputs/{extract_from_url(predictions_url, filename_pattern)}"
        )

        needs_pmtiles, _ = needs_preparation(self.model_data, self.image_layer)
        pmtiles_name = pmtiles_artifact_name(self.model_data.imageLayerId)
        attrs_name = attrs_artifact_name(self.model_data.modelId)

        workflow_config: Dict[str, Any] = {
            "project_id": self.model_data.projectId,
            "image_layer_id": self.model_data.imageLayerId,
            "model_id": self.model_data.modelId,
            "output_dir": "outputs",
            # Relative to the task working dir: the command cd's into
            # $AZ_BATCH_TASK_WORKING_DIR before running the workflow.
            "files": {
                "footprints": footprints_fn,
                "predictions": predictions_fn,
                "pmtiles": pmtiles_name,
                "attrs": attrs_name,
            },
            "tiles": {"build_pmtiles": needs_pmtiles},
            "store_artifacts": True,
        }
        self.storage.save(
            identifier=self.model_data.modelId,
            data=workflow_config,
            data_type=(
                self.config.get_metadata_types().PREDICTION_TILES_CONFIG.value
            ),
            data_format="json",
        )
        config_filepath = self.storage.get_file_remote_path(
            self.model_data.modelId,
            self.config.get_metadata_types().PREDICTION_TILES_CONFIG.value,
            data_format="json",
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
            "predictions": {
                "http_url": extract_from_url(
                    predictions_url, plain_url_pattern
                ),
                "file_path": predictions_fn,
            },
        }

    # ── finalization ──────────────────────────────────────────────────
    def _update_results_from_job(self) -> None:
        """Persist artifact URLs and counts from the task manifest."""
        job = self.model_data.predictionTilesJob
        content = self.runner.get_filecontent_from_task(
            job_id=job.jobId,
            task_id=job.taskId,
            filename=MANIFEST_FILENAME,
        )
        if not content:
            raise FileNotFoundError(
                "Prediction tiles manifest not found for model "
                f"{self.model_data.modelId}"
            )
        manifest = json.loads(content)

        attrs_url = manifest.get("attrs_url") or self._artifact_url(
            manifest.get("attrs_filename", "")
        )
        if not attrs_url:
            raise ValueError(
                "Prediction tiles manifest carries no attribute sidecar "
                f"for model {self.model_data.modelId}"
            )
        self.model_data.predictionAttrsUrl = attrs_url

        if manifest.get("pmtiles_built"):
            pmtiles_url = manifest.get("pmtiles_url") or self._artifact_url(
                manifest.get("pmtiles_filename", "")
            )
            if not pmtiles_url:
                raise ValueError(
                    "Prediction tiles manifest reports tiles were built "
                    "but carries no PMTiles URL for image layer "
                    f"{self.model_data.imageLayerId}"
                )
            self.image_layer.footprintPmtilesUrl = pmtiles_url

        self.model_data.predictedBuildingCount = int(
            manifest.get("building_count", 0)
        )
        self.model_data.predictedAt = MetadataUtils.get_timestamp()
        self._update_progress(
            "Prepared prediction attributes for "
            f"{self.model_data.predictedBuildingCount} buildings"
        )

    def _artifact_url(self, filename: str) -> str:
        """Resolve a task output filename to a downloadable URL."""
        if not filename:
            return ""
        return self.storage.get_file_remote_path(
            identifier=filename,
            extra_partition_keys=f"{self.model_data.predictionTilesJob.taskId}",
            data_format=os.path.splitext(filename)[1].strip("."),
        )

    def _replay_friendly_logs(self) -> None:
        for timestamp, message in self._get_friendly_logs():
            if message not in (
                self.model_data.predictionTilesStatusMessage or ""
            ):
                self._update_progress(message, timestamp=timestamp)

    def _get_friendly_logs(self) -> List[Tuple[str, str]]:
        job = self.model_data.predictionTilesJob
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
        self.model_data.predictionTilesStatusMessage = (
            MetadataUtils.append_status_message(
                self.model_data.predictionTilesStatusMessage,
                message,
                timestamp=timestamp,
            )
        )
