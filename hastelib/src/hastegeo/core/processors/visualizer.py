# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Assemble the results-viewer payload for BOTH prediction workflows.

The viewer used to be raster-only: it handed back TiTiler tile templates
over the two COGs the inference job writes (``_visualizer.tif`` and
``_predictions.tif``). The embedding workflow produces no rasters at
all — the interactive labeler posts per-building calls straight to a
GeoPackage — so an embedding model had nothing to show and, in practice,
no viewer entry point.

Both workflows *do* have vector artifacts, and they are the same two in
both cases:

* the building footprints as PMTiles — the layer's shared archive
  (``ImageLayer.footprintPmtilesUrl``) or, for an embedding model, the
  archive it already tiled for the labeler (``Model.pmtilesUrl``);
  :func:`~hastegeo.core.processors.prediction_tiles.resolve_tiles_url`
  is the seam that picks between them, and
* the model's columnar prediction attribute sidecar
  (``Model.predictionAttrsUrl``), keyed by the same row-index id the
  tiles carry.

So this module builds a *vector-first* payload: the two artifacts always
(as API-relative ``GetModelArtifact`` routes, never raw blob SAS URLs),
the rasters only when the model actually has them, and a readiness block
so the UI can say "still preparing" instead of drawing an empty map.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import quote, urlencode

from ..config import Config
from ..models.projects import ImageLayer, Model, Project
from ..models.visualizer import Imagery, PredictionsReadiness, Visualizer
from ..utils.model_readiness import REASON_READY, prediction_readiness
from ..utils.predictions import edited_prediction_versions
from .prediction_tiles import resolve_tiles_url

# The inference workflow writes a pre-coloured visualizer COG next to the
# raw prediction COG, sharing one container SAS. The raw one has never
# been stored on the Model, so it is still derived by swapping the
# suffix — but only when the suffix is actually there, so a differently
# named layer yields no layer instead of a URL that 404s every tile.
VISUALIZER_COG_SUFFIX = "_visualizer.tif"
PREDICTIONS_COG_SUFFIX = "_predictions.tif"

# TiTiler colormap overrides the embedded TIFF palette (whose alpha=0
# entry is silently dropped by TIFF). Maps pixel values 0/1 ->
# transparent, 2 -> green, 3 -> red, matching the inference.py palette.
PREDICTIONS_COLORMAP: Dict[str, List[int]] = {
    "0": [0, 0, 0, 0],
    "1": [0, 0, 0, 0],
    "2": [0, 255, 0, 255],
    "3": [255, 0, 0, 255],
}

TILE_PATH = "cog/tiles/WebMercatorQuad/{z}/{x}/{y}"

#: Artifacts are served through this route rather than as blob URLs: it
#: streams with Range support, managed identity and the app's auth, so
#: analysts outside the storage firewall allowlist can still read them.
MODEL_ARTIFACT_ROUTE = "GetModelArtifact"
FOOTPRINT_TILES_KIND = "footprint_pmtiles"
PREDICTION_ATTRS_KIND = "prediction_attrs"

#: Extra readiness reason: the model has predictions, but the browser
#: artifacts are still being built by the prediction-tiles job.
REASON_PREPARING = "preparing"


@dataclass
class PredictionInfo:
    """What the caller learned by opening the selected prediction file.

    Reading a GeoPackage is I/O, so the HTTP layer does it (it already
    downloads blobs) and passes the result in; this module stays a pure
    payload assembler that tests can drive with plain data.

    Attributes:
        version: Edited version that was read, ``None`` for the raw
            model output.
        flavor: ``"inference"`` or ``"embedding"``, from
            :func:`~hastegeo.core.utils.predictions.read_predictions`.
        supports_threshold: Whether re-thresholding the damage fraction
            is meaningful for this flavor.
        building_count: Rows in the prediction file.
        attrs_url: Blob URL of the attribute sidecar that describes the
            selected version. Empty when that version has no sidecar
            yet — the payload then reports "still preparing" rather than
            pointing the map at the raw model's classes.
        is_latest: Whether the selected version is the newest saved
            state of the model's predictions.
    """

    version: Optional[int] = None
    flavor: Optional[str] = None
    supports_threshold: Optional[bool] = None
    building_count: Optional[int] = None
    attrs_url: str = ""
    is_latest: bool = True


def model_artifact_url(
    project_id: str,
    model_id: str,
    kind: str,
    image_layer_id: Optional[str] = None,
    version: Optional[int] = None,
) -> str:
    """Build the API-relative ``GetModelArtifact`` route for one artifact.

    Relative on purpose: the function app does not know the client's API
    base URL (or its APIM subscription key), and the UI already funnels
    every call through its own ``buildUrl()``.

    ``version`` pins an edited-prediction revision; it is only meaningful
    for the per-version kinds (``prediction_attrs`` and ``gpkg``), so it
    is omitted for everything else.
    """
    params = [
        ("projectId", project_id or ""),
        ("modelId", model_id or ""),
        ("kind", kind),
    ]
    if image_layer_id:
        params.append(("imageLayerId", image_layer_id))
    if version is not None:
        params.append(("version", str(int(version))))
    return f"{MODEL_ARTIFACT_ROUTE}?{urlencode(params)}"


def _tile_url(
    titiler_endpoint: str,
    blob_url: str,
    colormap: Optional[Dict[str, List[int]]] = None,
) -> str:
    """Build a TiTiler XYZ template for one COG.

    The blob URL carries a SAS token, so it must be percent-encoded in
    full or TiTiler receives a mangled query string.
    """
    url = (
        f"{titiler_endpoint}{TILE_PATH}?scale=1&"
        f"url={quote(blob_url, safe='')}"
    )
    if colormap:
        url += "&colormap=" + quote(json.dumps(colormap), safe="")
    return url


def _study_area_bounds(study_area: Optional[Sequence[Any]]) -> Optional[list]:
    """Bounding box of the first study-area feature, if there is one."""
    if not study_area:
        return None
    feature = study_area[0]
    if isinstance(feature, dict):
        return feature.get("bbox")
    return getattr(feature, "bbox", None)


def raster_layer_urls(model: Model) -> Dict[str, Optional[str]]:
    """Return the model's two prediction COG URLs, if it has any.

    Only the trained-inference workflow writes rasters, and only the
    visualizer COG is stored on the Model; the raw prediction COG sits
    next to it under a sibling name.
    """
    visualizer_url = model.predictedDamageLayerUrl or ""
    if not visualizer_url:
        return {"visualizer": None, "predictions": None}
    predictions_url: Optional[str] = None
    if VISUALIZER_COG_SUFFIX in visualizer_url:
        predictions_url = visualizer_url.replace(
            VISUALIZER_COG_SUFFIX, PREDICTIONS_COG_SUFFIX
        )
    return {"visualizer": visualizer_url, "predictions": predictions_url}


def visualizer_readiness(
    model: Model,
    image_layer: ImageLayer,
    config: Optional[Config] = None,
    attrs_ready: Optional[bool] = None,
) -> PredictionsReadiness:
    """Report whether the viewer can draw this model's predictions.

    Two independent things have to be true, and the UI needs to tell
    them apart: the model must actually have predictions (workflow-aware
    rule in :mod:`hastegeo.core.utils.model_readiness`), and the two
    browser artifacts must have been built by the prediction-tiles job.
    The second is transient — the UI shows a "still preparing" state and
    polls — while the first usually is not.

    Args:
        model: The model being viewed.
        image_layer: Its image layer, which owns the footprint tiles.
        config: Optional config override.
        attrs_ready: Whether the sidecar for the *selected* prediction
            version exists. ``None`` falls back to the model-level
            sidecar, which describes the raw output. Passing the
            version's own answer is what stops the viewer from drawing
            raw classes while claiming to show an edit.
    """
    base = prediction_readiness(model, config=config)
    tiles_ready = bool(resolve_tiles_url(model, image_layer))
    if attrs_ready is None:
        attrs_ready = bool(model.predictionAttrsUrl)

    reason = base.reason
    detail = base.detail
    if base.ready and not (tiles_ready and attrs_ready):
        reason = REASON_PREPARING
        detail = (
            "Preparing this model's building predictions for display. "
            "This runs once per model and can take a few minutes."
        )
    elif base.ready:
        reason = REASON_READY
        detail = ""

    return PredictionsReadiness(
        ready=base.ready and tiles_ready and attrs_ready,
        reason=reason,
        detail=detail,
        workflow=base.workflow,
        status=base.status,
        tilesReady=tiles_ready,
        attrsReady=attrs_ready,
        predictionTilesStatus=model.predictionTilesStatus,
        predictionTilesStatusMessage=(
            model.predictionTilesStatusMessage or ""
        ),
    )


def build_visualizer_results(
    project: Project,
    image_layer: ImageLayer,
    model: Model,
    titiler_endpoint: str,
    study_area: Optional[Sequence[Any]] = None,
    predictions: Optional[PredictionInfo] = None,
    config: Optional[Config] = None,
) -> Visualizer:
    """Assemble the ``GetVisualizerResults`` payload.

    Args:
        project: Owning project (name and event date).
        image_layer: The layer whose imagery is shown, and which owns
            the shared footprint PMTiles.
        model: The model whose predictions are shown.
        titiler_endpoint: TiTiler base URL, trailing slash included.
        study_area: Label-project features drawn as the study area; the
            first feature's bbox also bounds the tile layers.
        predictions: What the caller read from the prediction
            GeoPackage. ``None`` when it could not be read — the payload
            then simply carries no flavor.
        config: Optional config override (tests inject a fake).

    Returns:
        A :class:`~hastegeo.core.models.visualizer.Visualizer`. Raster
        fields are ``None`` for any model without prediction COGs (every
        embedding model, and any inference model that has not produced
        them yet), so the map never gets a URL that 404s every tile.
    """
    info = predictions or PredictionInfo()
    bounds = _study_area_bounds(study_area)
    rasters = raster_layer_urls(model)
    # An edited version renders from ITS OWN sidecar, so readiness has to
    # be judged against that file and not the model-level one (which
    # always describes the raw output).
    selected_attrs_ready = bool(info.attrs_url) if info.version else None
    readiness = visualizer_readiness(
        model,
        image_layer,
        config=config,
        attrs_ready=selected_attrs_ready,
    )

    pre_event_url = (
        image_layer.preEventProcessedImageryUrl
        if image_layer.preEventImageryUrls
        else ""
    ) or ""
    post_event_url = image_layer.postEventProcessedImageryUrl or ""

    project_id = image_layer.projectId or project.projectId or ""
    model_id = model.modelId or ""
    # Only advertise the vector artifacts that exist. GetModelArtifact
    # reuses an embedding model's own PMTiles for the footprint_pmtiles
    # kind, which is exactly what resolve_tiles_url decides here.
    footprint_tiles_url = (
        model_artifact_url(
            project_id,
            model_id,
            FOOTPRINT_TILES_KIND,
            image_layer_id=image_layer.imageLayerId,
        )
        if readiness.tilesReady
        else None
    )
    # Pin the route to the selected version so switching versions is
    # just a different URL for the same renderer.
    prediction_attrs_url = (
        model_artifact_url(
            project_id,
            model_id,
            PREDICTION_ATTRS_KIND,
            version=info.version if info.version else None,
        )
        if readiness.attrsReady
        else None
    )

    return Visualizer(
        projectId=project_id,
        imageLayerId=image_layer.imageLayerId or "",
        modelId=model_id,
        projectName=project.name or "",
        studyArea=list(study_area or []),
        eventDate=project.eventDate,
        preDisasterImagery=Imagery(
            # With no pre-event imagery the viewer falls back to the
            # base Azure Map in the "pre" pane.
            url=(
                _tile_url(titiler_endpoint, pre_event_url)
                if pre_event_url
                else ""
            ),
            bounds=bounds,
        ),
        postDisasterImagery=Imagery(
            url=(
                _tile_url(titiler_endpoint, post_event_url)
                if post_event_url
                else ""
            ),
            bounds=bounds,
        ),
        predictedDamageLayer=(
            Imagery(
                url=_tile_url(titiler_endpoint, rasters["visualizer"]),
                bounds=bounds,
            )
            if rasters["visualizer"]
            else None
        ),
        predictionsLayer=(
            Imagery(
                url=_tile_url(
                    titiler_endpoint,
                    rasters["predictions"],
                    colormap=PREDICTIONS_COLORMAP,
                ),
                bounds=bounds,
            )
            if rasters["predictions"]
            else None
        ),
        footprintTilesUrl=footprint_tiles_url,
        predictionAttrsUrl=prediction_attrs_url,
        flavor=info.flavor,
        supportsThreshold=info.supports_threshold,
        buildingCount=info.building_count,
        predictionVersion=info.version,
        predictionVersionIsLatest=info.is_latest,
        predictionVersions=edited_prediction_versions(model),
        predictionsReady=readiness.ready,
        predictionsReadiness=readiness,
        sourceTypePreEvent=image_layer.sourceTypePreEvent,
        sourceTypePostEvent=image_layer.sourceTypePostEvent,
        imageryCaptureDatePreEvent=image_layer.imageryCaptureDatePreEvent,
        imageryCaptureDatePostEvent=image_layer.imageryCaptureDatePostEvent,
    )
