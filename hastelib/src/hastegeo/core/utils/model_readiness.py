# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""One rule for "does this model have predictions a reader can use?".

HASTE finishes a model two different ways, and the two record completion
on *different* fields:

* **trained inference** (label -> train -> infer) runs on Azure Batch and
  reports through ``Model.inferenceStatus``; its predictions land in
  ``Model.gpkgUrl`` (plus the ``_visualizer.tif`` COG in
  ``Model.predictedDamageLayerUrl``).
* **embedding** (``Model.modelType == "embedding"``) never runs
  inference: the interactive labeler trains in the browser and posts its
  per-building calls to ``PutBuildingPredictions``. Completion shows up
  on ``Model.status``, and the unambiguous "has predictions" signal is
  ``Model.predictedBuildingCount`` — clearing the labels re-writes a
  valid all-zero GeoPackage, so ``gpkgUrl`` alone cannot tell a cleared
  model from a finished one.

Every consumer that re-derived this rule locally got a slightly
different answer (the results button, the embedding row, and
``publishing/source.py`` each had their own). This module holds the one
rule they all defer to; the API surfaces it as ``predictionsReady`` on
the model payloads the UI already fetches.

The functions accept either a :class:`~hastegeo.core.models.projects.Model`
or the raw metadata ``dict`` the storage layer returns, because the API
handles both shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, MutableMapping, Optional, Union

from ..config import Config

#: ``Model.modelType`` value of the browser-labeling workflow.
EMBEDDING_MODEL_TYPE = "embedding"

#: Which workflow produced (or will produce) a model's predictions.
WORKFLOW_EMBEDDING = "embedding"
WORKFLOW_INFERENCE = "inference"

#: Machine-readable ``reason`` codes. The UI branches on these; the
#: matching ``detail`` string is what it shows the analyst.
REASON_READY = "ready"
REASON_NOT_PROCESSED = "not_processed"
REASON_NO_PREDICTIONS = "no_predictions"
REASON_NO_BUILDINGS = "no_buildings"

#: A Model instance or the raw metadata dict for one.
ModelLike = Union[Mapping[str, Any], Any]


def model_field(model: ModelLike, name: str) -> Any:
    """Read one field from a Model instance or a raw metadata dict.

    Returns ``None`` when the field is absent, so callers can tell
    "never set" from "set to zero/empty".
    """
    if isinstance(model, Mapping):
        return model.get(name)
    return getattr(model, name, None)


def model_workflow(model: ModelLike) -> str:
    """Classify a model as ``"embedding"`` or ``"inference"``."""
    model_type = model_field(model, "modelType") or "trained"
    if str(model_type).lower() == EMBEDDING_MODEL_TYPE:
        return WORKFLOW_EMBEDDING
    return WORKFLOW_INFERENCE


def completion_status(model: ModelLike) -> Optional[str]:
    """Return the status value that decides completion for this model.

    Embedding models signal completion on ``status``; trained models on
    ``inferenceStatus``. Gating on the wrong one is why the two
    workflows used to disagree about which models had results.
    """
    if model_workflow(model) == WORKFLOW_EMBEDDING:
        return model_field(model, "status")
    return model_field(model, "inferenceStatus")


def model_is_complete(
    model: ModelLike, config: Optional[Config] = None
) -> bool:
    """Report whether the model's producing job finished successfully.

    This is the publishing eligibility rule
    (``hastegeo.core.publishing.source``), lifted out so the readiness
    helper and the publisher cannot drift apart. It says nothing about
    whether any artifact was actually written — see
    :func:`prediction_readiness` for that.
    """
    statuses = (config or Config).get_status_types()
    return completion_status(model) == statuses.COMPLETED.value


@dataclass(frozen=True)
class PredictionReadiness:
    """Whether a model's predictions can be read, and why not if not.

    Attributes:
        ready: ``True`` only when a reader can load predictions now.
        reason: One of the ``REASON_*`` codes, for UI branching.
        detail: Human-readable sentence for the "not ready" state.
        workflow: ``"embedding"`` or ``"inference"``.
        status: The workflow-relevant status value that was checked.
    """

    ready: bool
    reason: str
    detail: str
    workflow: str
    status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an HTTP payload."""
        return {
            "ready": self.ready,
            "reason": self.reason,
            "detail": self.detail,
            "workflow": self.workflow,
            "status": self.status,
        }


def prediction_readiness(
    model: ModelLike, config: Optional[Config] = None
) -> PredictionReadiness:
    """Decide whether this model has per-building predictions to read.

    Both workflows must clear two bars: the producing job finished
    (:func:`model_is_complete`), and it left an artifact behind.

    The artifact check differs per workflow on purpose:

    * embedding — ``gpkgUrl`` plus a positive ``predictedBuildingCount``.
      A count of ``0`` means the analyst cleared the labels, which still
      writes a valid GeoPackage. A count of ``None`` predates the field,
      so those models fall back to "a GeoPackage exists" rather than
      being wrongly reported as empty.
    * inference — ``gpkgUrl`` or the ``_visualizer.tif`` COG in
      ``predictedDamageLayerUrl``; older models have only the raster.
    """
    workflow = model_workflow(model)
    status = completion_status(model)

    if not model_is_complete(model, config=config):
        return PredictionReadiness(
            ready=False,
            reason=REASON_NOT_PROCESSED,
            detail=(
                "This model has not finished processing yet."
                if workflow == WORKFLOW_EMBEDDING
                else "Inference has not finished for this model yet."
            ),
            workflow=workflow,
            status=status,
        )

    gpkg_url = model_field(model, "gpkgUrl") or ""

    if workflow == WORKFLOW_EMBEDDING:
        if not gpkg_url:
            return PredictionReadiness(
                ready=False,
                reason=REASON_NO_PREDICTIONS,
                detail=(
                    "No predictions have been saved from the interactive "
                    "labeler for this model."
                ),
                workflow=workflow,
                status=status,
            )
        building_count = model_field(model, "predictedBuildingCount")
        if building_count is not None and int(building_count) <= 0:
            return PredictionReadiness(
                ready=False,
                reason=REASON_NO_BUILDINGS,
                detail=(
                    "The saved predictions for this model contain no "
                    "buildings; label some buildings and save again."
                ),
                workflow=workflow,
                status=status,
            )
        return PredictionReadiness(
            ready=True,
            reason=REASON_READY,
            detail="",
            workflow=workflow,
            status=status,
        )

    raster_url = model_field(model, "predictedDamageLayerUrl") or ""
    if not gpkg_url and not raster_url:
        return PredictionReadiness(
            ready=False,
            reason=REASON_NO_PREDICTIONS,
            detail="Inference produced no prediction outputs.",
            workflow=workflow,
            status=status,
        )
    return PredictionReadiness(
        ready=True,
        reason=REASON_READY,
        detail="",
        workflow=workflow,
        status=status,
    )


def predictions_ready(
    model: ModelLike, config: Optional[Config] = None
) -> bool:
    """Boolean shorthand for :func:`prediction_readiness`."""
    return prediction_readiness(model, config=config).ready


def annotate_predictions_ready(
    model_data: MutableMapping[str, Any], config: Optional[Config] = None
) -> MutableMapping[str, Any]:
    """Stamp ``predictionsReady`` onto a model payload, in place.

    The API calls this on every model document it hands the UI so the
    rows never have to re-derive readiness client-side. Returns the same
    mapping for use in a comprehension.
    """
    model_data["predictionsReady"] = predictions_ready(
        model_data, config=config
    )
    return model_data
