# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Pure raw-generation readiness; no downloads, mutation, jobs, or queues."""

from typing import Any
from urllib.parse import urlencode

from ..models.projects import ImageLayer, Model


def prediction_flavor(model: Model) -> str:
    return "embedding" if model.modelType == "embedding" else "inference"


def _readiness(ready: bool, reason: str, detail: str) -> dict[str, Any]:
    return {"ready": ready, "reason": reason, "detail": detail}


def raw_predictions_readiness(model: Model) -> dict[str, Any]:
    if model.predictedBuildingCount == 0:
        return _readiness(False, "empty", "No saved building predictions.")
    if model.predictionRevision:
        if (
            model.predictionState != "ready"
            or model.predictionReadyRevision != model.predictionRevision
        ):
            return _readiness(
                False,
                model.predictionState or "generation_mismatch",
                "The current prediction generation is not available.",
            )
    else:
        status = (
            model.status
            if model.modelType == "embedding"
            else model.inferenceStatus
        )
        if status != "Processed":
            return _readiness(
                False,
                "not_processed",
                "Model must be Processed before predictions are available.",
            )
    if not model.gpkgUrl:
        return _readiness(
            False, "missing_predictions", "Run predictions or inference."
        )
    return _readiness(True, "ready", "Raw predictions are available.")


def results_readiness(model: Model, layer: ImageLayer) -> dict[str, Any]:
    raw = raw_predictions_readiness(model)
    if not raw["ready"]:
        return raw
    if not model.predictionAttrsUrl or not model.predictionRevision:
        return _readiness(
            False,
            "missing_attributes",
            "Rerun predictions or inference to create result attributes.",
        )
    if model.predictionReadyRevision != model.predictionRevision:
        return _readiness(
            False,
            "generation_mismatch",
            "Prediction attributes are out of date.",
        )
    if not layer.footprintPmtilesUrl:
        return _readiness(
            False,
            "missing_footprint_tiles",
            "Layer footprint tiles are not yet available.",
        )
    return _readiness(True, "ready", "Prediction results are available.")


def artifact_api_url(model: Model, kind: str) -> str:
    params = {
        "projectId": model.projectId,
        "imageLayerId": model.imageLayerId,
        "modelId": model.modelId,
        "kind": kind,
    }
    if kind in ("gpkg", "prediction_attrs") and model.predictionRevision:
        params["predictionRevision"] = model.predictionRevision
    return "/api/GetModelArtifact?" + urlencode(params)
