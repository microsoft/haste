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

Two scopes share this machinery:

* **model-scoped** — the historic path: build the layer's PMTiles when
  they are still missing *and* the model's attribute sidecar. State
  lives on the ``Model``.
* **layer-only** — no ``modelId``: build just the shared footprint
  PMTiles for an image layer, skipping the sidecar entirely. Kicked off
  by ``processors/imagery.py`` as soon as a layer's footprints are
  cached, so the tiles are already there by the time the first model is
  edited. State lives on the ``ImageLayer``
  (``footprintTilesStatus``/``footprintTilesJob``) — there is no model
  to write to.

Both scopes write the same deterministic artifact name
(``footprints_${imageLayerId}.pmtiles``), so a model-scoped job that
starts while a layer-only job is still running simply repeats the tiling
and overwrites the archive with an identical one — wasteful in a narrow
window, never inconsistent.

Config JSON handed to the workflow (``model_id``/``files.predictions``/
``files.attrs`` are omitted in layer-only mode)::

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
      "versions": [
        {
          "version": 1,
          "predictions": "inputs/<edited v1>.gpkg",
          "attrs": "prediction_attrs_<modelId>_v1.json"
        }
      ],
      "store_artifacts": true
    }

``versions`` is the **backfill** list: one entry per saved edited
version (``Model.editedPredictions``) that has no sidecar yet. Each gets
its own ``ArtifactTypes.PREDICTION_ATTRS_VERSION`` payload built from
that version's own GeoPackage, which is what lets the viewer switch
versions by swapping a URL. The list is derived from the model document
at submit time, so versions that already have a sidecar are skipped and
re-running the job is a no-op for them.

Queue message (``prediction-edit-prep-queue``)::

    {
      "projectId": "...",
      "imageLayerId": "...",
      "modelId": "...",
      "sourceGpkgUrl": "...",
      "sourceFootprintsUrl": "...",
      "force": false,
      "backfillVersions": true
    }

An empty ``modelId`` (and, with it, an empty ``sourceGpkgUrl``) selects
the layer-only mode, in which ``backfillVersions`` is meaningless (there
is no model to read versions from).

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
from typing import Any, Dict, List, Optional, Tuple, Union

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

# The document a prediction-tiles job records its state on: the Model in
# model-scoped mode, the ImageLayer when only the shared footprint tiles
# are being built.
PredictionTilesTarget = Union[Model, ImageLayer]


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


def version_attrs_artifact_name(model_id: str, version: int) -> str:
    """Artifact name for ONE edited version's attribute sidecar.

    Same template as
    ``hastegeo.core.utils.prediction_attrs.version_attrs_artifact_name``
    — which the Functions app uses at save time — but derived here from
    ``ArtifactTypes`` directly, because this module is imported by the
    queue app, which must not pull in fiona.
    """
    return (
        ArtifactTypes.PREDICTION_ATTRS_VERSION.value.substitute(
            modelId=model_id, version=int(version)
        )
        + ".json"
    )


def versions_needing_attrs(model: Model) -> List[Dict[str, Any]]:
    """Return this model's saved versions that still have no sidecar.

    Oldest first. A version whose GeoPackage exists without a matching
    sidecar cannot be drawn by the map at all, so these are exactly the
    revisions a backfill run has to rebuild. Versions that already have
    one never appear here, which is what makes the backfill idempotent.
    """
    entries: List[Dict[str, Any]] = []
    for entry in model.editedPredictions or []:
        gpkg_url = getattr(entry, "gpkgUrl", None)
        attrs_url = getattr(entry, "predictionAttrsUrl", None)
        version = getattr(entry, "version", None)
        if version is None or not gpkg_url or attrs_url:
            continue
        entries.append(
            {
                "version": int(version),
                "gpkgUrl": str(gpkg_url),
            }
        )
    return sorted(entries, key=lambda entry: entry["version"])


def build_prep_message(
    project_id: str,
    image_layer_id: str,
    model_id: Optional[str] = None,
    source_gpkg_url: Optional[str] = None,
    source_footprints_url: Optional[str] = None,
    force: bool = False,
    backfill_versions: bool = True,
) -> Dict[str, Any]:
    """Build a ``prediction-edit-prep-queue`` message payload.

    The message only carries identifiers; the queue trigger reads the
    authoritative state from metadata so that re-queued poll messages
    and fresh requests take the same code path.

    Args:
        project_id: Owning project.
        image_layer_id: Layer whose footprints get tiled.
        model_id: Model whose attribute sidecar is needed. Omit (or pass
            ``None``) to request the layer's footprint PMTiles alone —
            the mode imagery prep uses at layer-creation time, when no
            model exists yet.
        source_gpkg_url: The model's prediction GeoPackage. Meaningless
            (and empty) in layer-only mode.
        source_footprints_url: The layer's cached footprints GeoPackage.
        force: Rebuild even when the artifacts already exist.
        backfill_versions: Also (re)build the attribute sidecar of every
            saved edited version that has none. Ignored in layer-only
            mode, where there is no model to read versions from.
    """
    return {
        "projectId": project_id,
        "imageLayerId": image_layer_id,
        "modelId": model_id or "",
        "sourceGpkgUrl": source_gpkg_url or "",
        "sourceFootprintsUrl": source_footprints_url or "",
        "force": bool(force),
        "backfillVersions": bool(backfill_versions),
    }


def enqueue_prediction_tiles(
    project_id: str,
    image_layer_id: str,
    model_id: Optional[str] = None,
    source_gpkg_url: Optional[str] = None,
    source_footprints_url: Optional[str] = None,
    force: bool = False,
    config: Optional[Config] = None,
    backfill_versions: bool = True,
) -> Dict[str, Any]:
    """Put a preparation request on the prediction-edit prep queue.

    Convenience seam for the HTTP layer and for imagery prep, neither of
    which may run ``tippecanoe`` inline. Omitting ``model_id`` requests
    the layer's shared footprint PMTiles only. Returns the enqueued
    message.
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
        backfill_versions=backfill_versions,
    )
    queue_client = AzureQueueHandler(
        config.queue_config["queue_connection_string"],
        config.queue_config["prediction_edit_prep_queue_name"],
        config.queue_config["queue_account_url"],
    )
    queue_client.put_message(json.dumps(message), visibility_timeout=0)
    return message


def resolve_tiles_url(model: Model, image_layer: ImageLayer) -> Optional[str]:
    """Return the PMTiles archive a map should read, if any.

    Footprint geometry belongs to the image layer, not to a model: every
    model trained on a layer draws the same buildings. Both workflows
    therefore share one archive, built once when the layer's footprints
    are cached.

    ``model`` is accepted so callers can pass the pair without caring
    which one owns the tiles.
    """
    del model
    return image_layer.footprintPmtilesUrl


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


def layer_needs_footprint_tiles(image_layer: ImageLayer) -> bool:
    """Report whether a layer-only tiling job is worth queueing.

    Used by imagery prep, which has no model in hand: the tiles can only
    be built once the footprints GeoPackage is cached, and there is no
    point rebuilding an archive the layer already has.
    """
    return bool(image_layer.buildingFootprintsUrl) and not bool(
        image_layer.footprintPmtilesUrl
    )


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
    backfill_versions: bool = True,
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
        backfill_versions: Also rebuild the attribute sidecar of every
            saved edited version that has none — a job is queued for
            that alone when the model's own artifacts are already there.
            This is how versions saved before per-version sidecars
            existed become renderable.

    Returns:
        ``{"modelId", "queued", "tilesReady", "attrsReady",
        "versionsPending", "status", "statusMessage"}``.
        ``tilesReady``/``attrsReady`` describe the state *now*, so a
        caller that polls sees them flip to ``True`` once the queued job
        finishes; ``versionsPending`` counts the saved versions that
        still have no sidecar and drops to 0 the same way.

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
    pending_versions = (
        versions_needing_attrs(model) if backfill_versions else []
    )
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
            "versionsPending": len(pending_versions),
            "status": model.predictionTilesStatus,
            "statusMessage": model.predictionTilesStatusMessage or "",
        }

    nothing_outstanding = (
        not needs_pmtiles and not needs_attrs and not pending_versions
    )
    if not force and nothing_outstanding:
        # Every artifact exists: record that and skip the queue rather
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
        backfill_versions=backfill_versions,
    )
    logger.info(
        "Queued prediction tiles for model %s (pmtiles=%s, attrs=%s, "
        "versions=%s, force=%s)",
        model.modelId,
        needs_pmtiles or force,
        needs_attrs or force,
        [entry["version"] for entry in pending_versions],
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
        # A saved version without a sidecar cannot be drawn, so it is
        # outstanding work exactly like a missing model-level sidecar.
        pending_versions = versions_needing_attrs(self.model_data)
        if (
            not force
            and not needs_pmtiles
            and not needs_attrs
            and not pending_versions
        ):
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
            "Queued prediction tiles for model %s (pmtiles=%s, attrs=%s, "
            "versions=%s)",
            self.model_data.modelId,
            needs_pmtiles or force,
            needs_attrs or force,
            [entry["version"] for entry in pending_versions],
        )
        return self.model_data


class PredictionTilesPostprocessor:
    """Submit, poll and finalize the prediction-tiles Batch task.

    Runs in one of two scopes:

    * **model-scoped** (``model`` given): builds the attribute sidecar,
      plus the layer's PMTiles when they are still missing. Job state
      lives on the ``Model``.
    * **layer-only** (``model is None``): builds just the layer's shared
      footprint PMTiles, which is what imagery prep asks for at
      layer-creation time. Job state lives on the ``ImageLayer`` and no
      model document is read or written.

    A model-scoped run also backfills the attribute sidecar of every
    saved edited version that lacks one (``backfill_versions``). The
    input list comes from the model document at submit time, so a
    version that already has a sidecar is never rebuilt and re-running
    the job is a no-op for it.
    """

    def __init__(
        self,
        model: Optional[Model],
        image_layer: ImageLayer,
        config: Optional[Config] = None,
        backfill_versions: bool = True,
    ) -> None:
        if config is None:
            config = Config()
        if image_layer is None:
            raise ValueError(
                "PredictionTilesPostprocessor requires the image layer "
                "that owns the footprint tiles."
            )
        self.config = config
        self.model_data = model
        self.image_layer = image_layer
        # No model -> layer-only mode: footprint tiles alone, no sidecar.
        self.layer_only = model is None
        self.backfill_versions = bool(backfill_versions)
        self.project_id = (
            image_layer.projectId if self.layer_only else model.projectId
        )
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
            config.queue_config["prediction_edit_prep_queue_name"],
            config.queue_config["queue_account_url"],
        )

    # ── scope-aware state accessors ───────────────────────────────────
    # The job's status/reference/log live on whichever document owns the
    # work, so every state transition below goes through these instead of
    # touching a specific document.
    @property
    def target(self) -> PredictionTilesTarget:
        """The document this job's state is recorded on."""
        return self.image_layer if self.layer_only else self.model_data

    @property
    def target_id(self) -> str:
        """Identifier of that document, for logs and task naming."""
        if self.layer_only:
            return self.image_layer.imageLayerId
        return self.model_data.modelId

    @property
    def status(self) -> Optional[str]:
        if self.layer_only:
            return self.image_layer.footprintTilesStatus
        return self.model_data.predictionTilesStatus

    @status.setter
    def status(self, value: str) -> None:
        if self.layer_only:
            self.image_layer.footprintTilesStatus = value
        else:
            self.model_data.predictionTilesStatus = value

    @property
    def job(self) -> Optional[TrainingJob]:
        if self.layer_only:
            return self.image_layer.footprintTilesJob
        return self.model_data.predictionTilesJob

    @job.setter
    def job(self, value: TrainingJob) -> None:
        if self.layer_only:
            self.image_layer.footprintTilesJob = value
        else:
            self.model_data.predictionTilesJob = value

    @property
    def status_message(self) -> str:
        if self.layer_only:
            return self.image_layer.footprintTilesStatusMessage or ""
        return self.model_data.predictionTilesStatusMessage or ""

    @status_message.setter
    def status_message(self, value: str) -> None:
        if self.layer_only:
            self.image_layer.footprintTilesStatusMessage = value
        else:
            self.model_data.predictionTilesStatusMessage = value

    def _poll_message(self) -> str:
        """Message that brings this job back for another status poll."""
        footprints_url = self.image_layer.buildingFootprintsUrl
        return json.dumps(
            build_prep_message(
                project_id=self.project_id,
                image_layer_id=self.image_layer.imageLayerId,
                model_id=None if self.layer_only else self.model_data.modelId,
                source_gpkg_url=(
                    None if self.layer_only else self.model_data.gpkgUrl
                ),
                source_footprints_url=footprints_url,
                backfill_versions=self.backfill_versions,
            )
        )

    def process(self) -> PredictionTilesTarget:
        """Advance the job state machine by one step.

        Returns:
            The document that owns this job's state — the ``Model`` in
            model-scoped mode, the ``ImageLayer`` in layer-only mode. In
            model-scoped mode the caller persists ``self.image_layer``
            too: the footprint tiles belong to the layer, the attribute
            sidecar to the model.
        """
        self.logger.info(
            "%s.process: %s %s prediction tiles status %s",
            self.__class__.__name__,
            "image layer" if self.layer_only else "model",
            self.target_id,
            self.status,
        )
        statuses = self.config.get_status_types()

        if self.status == statuses.PENDING.value:
            self._update_progress("Submitting prediction tile job")
            self._execute_job()

        elif self.status == statuses.IN_PROGRESS.value:
            job = self.job
            if job is None:
                self.status = statuses.FAILED.value
                self._update_progress(
                    "Prediction tile job reference is missing; cannot "
                    "poll for completion"
                )
                return self.target

            task_status = self.runner.get_task_status(
                job_id=job.jobId, task_id=job.taskId
            )
            self.logger.info(
                "Task status for prediction tiles of %s is %s",
                self.target_id,
                task_status,
            )

            if task_status == statuses.COMPLETED.value:
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                try:
                    self._update_results_from_job()
                    self.status = task_status
                except Exception as error:
                    self.logger.error(
                        "Error finalizing prediction tiles for "
                        f"{self.target_id}: {error}",
                        stack_info=True,
                    )
                    self.status = statuses.FAILED.value
                    job.status = statuses.FAILED.value
                    self._update_progress(
                        f"Prediction tile job failed: {error}"
                    )
                self._replay_friendly_logs()
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)

            elif task_status == statuses.FAILED.value:
                self.status = task_status
                job.status = task_status
                job.completedDate = MetadataUtils.get_timestamp()
                self._replay_friendly_logs()
                self._update_progress("Prediction tile job failed")
                self.runner.cleanup_task(job_id=job.jobId, task_id=job.taskId)
            else:
                self.status = task_status
                job.status = task_status
                self.queue_client.put_message(self._poll_message())

        return self.target

    # ── submission ────────────────────────────────────────────────────
    def _execute_job(self) -> PredictionTilesTarget:
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
                f"{MetadataUtils.hash_string(self.project_id)}" f"/{task_id}"
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
            self.job = TrainingJob(
                jobId=job_id,
                taskId=task_id,
                modelId=None if self.layer_only else self.model_data.modelId,
                projectId=self.project_id,
                status=statuses.IN_PROGRESS.value,
                creationDate=MetadataUtils.get_timestamp(),
            )
            self.status = statuses.IN_PROGRESS.value
            self._update_progress(
                f"Prediction tiles submitted with task id {task_id}"
            )
            self.queue_client.put_message(self._poll_message())
        except Exception as error:
            self.logger.error(
                "Error submitting prediction tiles for "
                f"{self.target_id}: {error}",
                stack_info=True,
            )
            self.status = statuses.FAILED.value
            self._update_progress(f"Prediction tile job failed: {error}")
        return self.target

    def _create_job_config(self) -> Dict[str, Dict[str, str]]:
        """Write the workflow config and describe the task input files.

        In layer-only mode neither the prediction GeoPackage nor the
        sidecar is referenced: the task tiles the footprints and stops.
        In model-scoped mode the config additionally lists every saved
        edited version that still lacks a sidecar, so the task rebuilds
        those from the versions' own GeoPackages.
        """
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

        image_layer_id = self.image_layer.imageLayerId
        pmtiles_name = pmtiles_artifact_name(image_layer_id)
        files: Dict[str, str] = {
            "footprints": footprints_fn,
            "pmtiles": pmtiles_name,
        }
        workflow_config: Dict[str, Any] = {
            "project_id": self.project_id,
            "image_layer_id": image_layer_id,
            "output_dir": "outputs",
            # Relative to the task working dir: the command cd's into
            # $AZ_BATCH_TASK_WORKING_DIR before running the workflow.
            "files": files,
            "store_artifacts": True,
        }

        predictions_url = None
        predictions_fn = ""
        version_inputs: List[Dict[str, Any]] = []
        if self.layer_only:
            # Nothing to reuse and nothing to join: the whole point of
            # this job is to produce the layer's archive.
            workflow_config["tiles"] = {"build_pmtiles": True}
            config_identifier = image_layer_id
        else:
            predictions_url = self.model_data.gpkgUrl
            if not predictions_url:
                raise ValueError("Model has no prediction GeoPackage.")
            predictions_fn = (
                f"inputs/{extract_from_url(predictions_url, filename_pattern)}"
            )
            needs_pmtiles, _ = needs_preparation(
                self.model_data, self.image_layer
            )
            files["predictions"] = predictions_fn
            files["attrs"] = attrs_artifact_name(self.model_data.modelId)
            workflow_config["model_id"] = self.model_data.modelId
            workflow_config["tiles"] = {"build_pmtiles": needs_pmtiles}
            config_identifier = self.model_data.modelId

            # Backfill inputs: one edited GeoPackage per version that
            # has no sidecar yet. Reading the model document here (and
            # not the queue message) is what keeps this idempotent.
            pending = (
                versions_needing_attrs(self.model_data)
                if self.backfill_versions
                else []
            )
            for entry in pending:
                version = int(entry["version"])
                version_url = entry["gpkgUrl"]
                version_fn = (
                    "inputs/"
                    f"{extract_from_url(version_url, filename_pattern)}"
                )
                version_inputs.append(
                    {
                        "version": version,
                        "url": version_url,
                        "file_path": version_fn,
                    }
                )
            workflow_config["versions"] = [
                {
                    "version": entry["version"],
                    "predictions": entry["file_path"],
                    "attrs": version_attrs_artifact_name(
                        self.model_data.modelId, entry["version"]
                    ),
                }
                for entry in version_inputs
            ]

        self.storage.save(
            identifier=config_identifier,
            data=workflow_config,
            data_type=(
                self.config.get_metadata_types().PREDICTION_TILES_CONFIG.value
            ),
            data_format="json",
        )
        config_filepath = self.storage.get_file_remote_path(
            config_identifier,
            self.config.get_metadata_types().PREDICTION_TILES_CONFIG.value,
            data_format="json",
        )
        config_fn = (
            f"inputs/{extract_from_url(config_filepath, filename_pattern)}"
        )

        input_files: Dict[str, Dict[str, str]] = {
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
        if predictions_url:
            input_files["predictions"] = {
                "http_url": extract_from_url(
                    predictions_url, plain_url_pattern
                ),
                "file_path": predictions_fn,
            }
        for entry in version_inputs:
            input_files[f"predictions_v{entry['version']}"] = {
                "http_url": extract_from_url(entry["url"], plain_url_pattern),
                "file_path": entry["file_path"],
            }
        return input_files

    # ── finalization ──────────────────────────────────────────────────
    def _update_results_from_job(self) -> None:
        """Persist artifact URLs and counts from the task manifest."""
        job = self.job
        content = self.runner.get_filecontent_from_task(
            job_id=job.jobId,
            task_id=job.taskId,
            filename=MANIFEST_FILENAME,
        )
        if not content:
            raise FileNotFoundError(
                "Prediction tiles manifest not found for " f"{self.target_id}"
            )
        manifest = json.loads(content)

        if manifest.get("pmtiles_built"):
            pmtiles_url = manifest.get("pmtiles_url") or self._artifact_url(
                manifest.get("pmtiles_filename", "")
            )
            if not pmtiles_url:
                raise ValueError(
                    "Prediction tiles manifest reports tiles were built "
                    "but carries no PMTiles URL for image layer "
                    f"{self.image_layer.imageLayerId}"
                )
            self.image_layer.footprintPmtilesUrl = pmtiles_url

        if self.layer_only:
            # No sidecar, no model document: the layer's tiles are the
            # entire deliverable, so a manifest without them is a failure.
            if not self.image_layer.footprintPmtilesUrl:
                raise ValueError(
                    "Layer-only prediction tile job produced no PMTiles "
                    f"for image layer {self.image_layer.imageLayerId}"
                )
            self._update_progress(
                "Prepared footprint tiles for "
                f"{int(manifest.get('building_count', 0))} buildings"
            )
            return

        attrs_url = manifest.get("attrs_url") or self._artifact_url(
            manifest.get("attrs_filename", "")
        )
        if not attrs_url:
            raise ValueError(
                "Prediction tiles manifest carries no attribute sidecar "
                f"for model {self.model_data.modelId}"
            )
        self.model_data.predictionAttrsUrl = attrs_url

        self.model_data.predictedBuildingCount = int(
            manifest.get("building_count", 0)
        )
        self.model_data.predictedAt = MetadataUtils.get_timestamp()
        self._update_progress(
            "Prepared prediction attributes for "
            f"{self.model_data.predictedBuildingCount} buildings"
        )
        self._record_version_attrs(manifest)

    def _record_version_attrs(self, manifest: Dict[str, Any]) -> None:
        """Attach each backfilled sidecar URL to its version entry.

        A version whose sidecar could not be built keeps an empty
        ``predictionAttrsUrl``, so the next preparation request picks it
        up again instead of the model silently claiming a renderable
        version it does not have.
        """
        records = manifest.get("version_attrs") or []
        if not records:
            return
        by_version = {
            int(entry.version): entry
            for entry in (self.model_data.editedPredictions or [])
            if getattr(entry, "version", None) is not None
        }
        backfilled: List[int] = []
        for record in records:
            try:
                version = int(record.get("version"))
            except (TypeError, ValueError):
                continue
            entry = by_version.get(version)
            if entry is None:
                self.logger.warning(
                    "Prediction tiles manifest reports a sidecar for "
                    "version %s, which model %s no longer has",
                    version,
                    self.model_data.modelId,
                )
                continue
            url = record.get("url") or self._artifact_url(
                record.get("filename", "")
            )
            if not url:
                self.logger.warning(
                    "No sidecar URL for version %s of model %s: %s",
                    version,
                    self.model_data.modelId,
                    record.get("error") or "not built",
                )
                continue
            entry.predictionAttrsUrl = url
            backfilled.append(version)
        if backfilled:
            self._update_progress(
                "Prepared prediction attributes for edited version(s) "
                + ", ".join(str(version) for version in sorted(backfilled))
            )

    def _artifact_url(self, filename: str) -> str:
        """Resolve a task output filename to a downloadable URL."""
        if not filename:
            return ""
        return self.storage.get_file_remote_path(
            identifier=filename,
            extra_partition_keys=f"{self.job.taskId}",
            data_format=os.path.splitext(filename)[1].strip("."),
        )

    def _replay_friendly_logs(self) -> None:
        for timestamp, message in self._get_friendly_logs():
            if message not in self.status_message:
                self._update_progress(message, timestamp=timestamp)

    def _get_friendly_logs(self) -> List[Tuple[str, str]]:
        job = self.job
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
        self.status_message = MetadataUtils.append_status_message(
            self.status_message,
            message,
            timestamp=timestamp,
        )
