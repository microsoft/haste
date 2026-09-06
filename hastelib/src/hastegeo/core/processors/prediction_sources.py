# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Request-local raw/saved source selection. No reads mutate model pointers."""

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

from ..models.prediction_edits import EditedPredictionVersion
from ..models.projects import ImageLayer, Model
from ..utils.prediction_readiness import (
    prediction_flavor,
    raw_predictions_readiness,
)


@dataclass(frozen=True)
class PredictionSource:
    predictionVersion: int
    predictionRevision: str | None
    currentPredictionRevision: str | None
    gpkgUrl: str | None
    predictionAttrsUrl: str | None
    flavor: str
    buildingCount: int | None
    editedCount: int = 0
    threshold: float = 0.0
    unknownThreshold: float = 0.0

    @property
    def is_edited(self) -> bool:
        return self.predictionVersion > 0

    def descriptor(self) -> dict[str, Any]:
        return {
            "predictionVersion": self.predictionVersion,
            "predictionRevision": self.predictionRevision,
            "currentPredictionRevision": self.currentPredictionRevision,
            "isEdited": self.is_edited,
            "flavor": self.flavor,
            "threshold": self.threshold,
            "unknownThreshold": self.unknownThreshold,
        }


def find_edited_version(model: Model, version: int) -> EditedPredictionVersion:
    matches = [
        entry
        for entry in model.editedPredictions or []
        if entry.version == version
    ]
    if not matches:
        raise FileNotFoundError("Prediction version not found")
    if len(matches) != 1:
        raise RuntimeError("Duplicate prediction version metadata")
    return matches[0]


def resolve_prediction_source(
    model: Model,
    version: int | None = None,
    *,
    default: Literal["raw", "latest_current"] = "raw",
    prediction_revision: str | None = None,
) -> PredictionSource:
    if version is None:
        matching = [
            entry.version
            for entry in model.editedPredictions or []
            if model.predictionRevision is not None
            and entry.sourcePredictionRevision == model.predictionRevision
        ]
        version = (
            max(matching, default=0) if default == "latest_current" else 0
        )
    if version == 0:
        if (
            prediction_revision is not None
            and prediction_revision != model.predictionRevision
        ):
            raise FileNotFoundError(
                "Raw prediction generation is no longer current"
            )
        available = raw_predictions_readiness(model)["ready"]
        return PredictionSource(
            0,
            model.predictionRevision,
            model.predictionRevision,
            model.gpkgUrl if available else None,
            model.predictionAttrsUrl
            if (
                available
                and model.predictionReadyRevision == model.predictionRevision
            )
            else None,
            prediction_flavor(model),
            model.predictedBuildingCount,
        )
    entry = find_edited_version(model, version)
    if (
        prediction_revision is not None
        and prediction_revision != entry.sourcePredictionRevision
    ):
        raise FileNotFoundError(
            "Prediction version does not match this generation"
        )
    return PredictionSource(
        entry.version,
        entry.sourcePredictionRevision,
        model.predictionRevision,
        entry.gpkgUrl or None,
        entry.predictionAttrsUrl,
        entry.flavor or prediction_flavor(model),
        entry.buildingCount,
        entry.editedCount,
        entry.threshold if entry.threshold is not None else 0.0,
        entry.unknownThreshold if entry.unknownThreshold is not None else 0.0,
    )


def prediction_source_url(
    model: Model, source: PredictionSource, kind: str
) -> str:
    params: dict[str, Any] = {
        "projectId": model.projectId,
        "imageLayerId": model.imageLayerId,
        "modelId": model.modelId,
        "kind": kind,
        "version": source.predictionVersion,
    }
    if source.predictionRevision is not None:
        params["predictionRevision"] = source.predictionRevision
    return "/api/GetModelArtifact?" + urlencode(params)


def source_readiness(
    model: Model, layer: ImageLayer, source: PredictionSource
) -> dict[str, Any]:
    attrs_ready = bool(source.predictionAttrsUrl and source.predictionRevision)
    tiles_ready = bool(layer.footprintPmtilesUrl)
    reason, detail = "ready", "Prediction results are available."
    if not source.is_edited and not raw_predictions_readiness(model)["ready"]:
        raw = raw_predictions_readiness(model)
        reason, detail = raw["reason"], raw["detail"]
    elif not source.gpkgUrl:
        reason, detail = (
            "missing_predictions",
            "Prediction GeoPackage is unavailable.",
        )
    elif source.buildingCount == 0:
        reason, detail = "empty", "No predicted buildings."
    elif not attrs_ready:
        reason, detail = (
            "missing_attributes",
            "Matching prediction attributes are unavailable; no automatic backfill is performed.",
        )
    elif not tiles_ready:
        reason, detail = (
            "missing_footprint_tiles",
            "Layer footprint tiles are not yet available.",
        )
    return {
        "ready": reason == "ready",
        "reason": reason,
        "detail": detail,
        "attrsReady": attrs_ready,
        "tilesReady": tiles_ready,
    }


def prediction_versions(
    model: Model, layer: ImageLayer | None = None
) -> list[dict[str, Any]]:
    versions = []
    for entry in sorted(
        model.editedPredictions or [],
        key=lambda item: item.version,
        reverse=True,
    ):
        source = resolve_prediction_source(model, entry.version)
        data = entry.model_dump(mode="json", exclude={"sourceGpkgUrl"})
        data["predictionRevision"] = source.predictionRevision
        data["gpkgUrl"] = (
            prediction_source_url(model, source, "gpkg")
            if source.gpkgUrl
            else None
        )
        data["predictionAttrsUrl"] = (
            prediction_source_url(model, source, "prediction_attrs")
            if source.predictionAttrsUrl
            else None
        )
        data["isCurrentGeneration"] = (
            source.predictionRevision is not None
            and source.predictionRevision == model.predictionRevision
        )
        data["downloadReady"] = bool(source.gpkgUrl)
        if layer is not None:
            readiness = source_readiness(model, layer, source)
            data["predictionsReady"] = readiness["ready"]
            data["predictionsReadiness"] = readiness
        versions.append(data)
    return versions
