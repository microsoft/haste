# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Imagery(BaseModel):
    url: str = Field(default="")
    tms: bool = Field(default=False)
    attribution: str = Field(default="AI For Good Lab")
    minZoom: int = Field(default=12)
    maxNativeZoom: int = Field(default=20)
    maxZoom: int = Field(default=21)
    # Optional because a project with no study-area polygon has no bbox
    # to bound the tiles with; the map then falls back to its own view.
    bounds: Optional[list] = Field(default_factory=list)


class PredictionsReadiness(BaseModel):
    """Why the viewer can (or cannot) draw this model's predictions yet.

    ``ready`` is the vector path's readiness: the model has predictions
    *and* the two browser artifacts (footprint PMTiles + attribute
    sidecar) exist. When it is ``False`` the UI shows ``detail`` — a
    "still preparing" or "not processed" message — instead of an empty
    map.
    """

    ready: bool = Field(default=False)
    # Machine-readable code the UI branches on: "ready", "not_processed",
    # "no_predictions", "no_buildings" or "preparing".
    reason: str = Field(default="")
    detail: str = Field(default="")
    # "embedding" or "inference".
    workflow: str = Field(default="")
    # The workflow-relevant model status that was checked.
    status: Optional[str] = Field(default=None)
    tilesReady: bool = Field(default=False)
    attrsReady: bool = Field(default=False)
    predictionTilesStatus: Optional[str] = Field(default=None)
    predictionTilesStatusMessage: str = Field(default="")


class Visualizer(BaseModel):
    projectId: str = Field(default="")
    imageLayerId: str = Field(default="")
    modelId: str = Field(default="")
    projectName: str = Field(default="")
    studyArea: list = Field(default_factory=list)
    eventDate: Optional[str] = Field(default=None)
    predictedDamageImageryDownloadUrl: str = Field(default="")
    preDisasterImagery: Imagery = Field(default_factory=Imagery)
    postDisasterImagery: Imagery = Field(default_factory=Imagery)
    # ── Raster prediction layers (trained-inference workflow only) ──────
    # Both are TiTiler tile templates over COGs the inference job wrote.
    # The embedding workflow produces no rasters at all, so these are
    # None there — an empty tile URL would just 404 every tile request.
    predictedDamageLayer: Optional[Imagery] = Field(default=None)
    predictionsLayer: Optional[Imagery] = Field(default=None)
    # ── Vector prediction layer (both workflows) ────────────────────────
    # API-relative GetModelArtifact routes, not blob URLs: the artifacts
    # stream through the function app (auth + Range + managed identity),
    # and the UI turns them into absolute URLs with its own buildUrl().
    footprintTilesUrl: Optional[str] = Field(default=None)
    predictionAttrsUrl: Optional[str] = Field(default=None)
    # Prediction flavor, from hastegeo.core.utils.predictions. The
    # embedding producer's damage fraction is a degenerate 0/1 copy of
    # `damaged`, so re-thresholding it is meaningless there.
    flavor: Optional[str] = Field(default=None)
    supportsThreshold: Optional[bool] = Field(default=None)
    buildingCount: Optional[int] = Field(default=None)
    # Which prediction GeoPackage was read: an analyst-edited version
    # number, or None for the raw model output.
    predictionVersion: Optional[int] = Field(default=None)
    # Model.editedPredictions, newest version first, so the viewer can
    # offer a version switch without a second round trip.
    predictionVersions: List[Dict[str, Any]] = Field(default_factory=list)
    predictionsReady: bool = Field(default=False)
    predictionsReadiness: PredictionsReadiness = Field(
        default_factory=PredictionsReadiness
    )
    sourceTypePreEvent: Optional[str] = Field(default=None)
    sourceTypePostEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePreEvent: Optional[str] = Field(default=None)
    imageryCaptureDatePostEvent: Optional[str] = Field(default=None)
