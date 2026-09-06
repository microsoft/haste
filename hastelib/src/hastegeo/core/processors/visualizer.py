# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Read-only common results contract for standard and embedding models."""

import json
from urllib.parse import quote

from ..models.prediction_results import ResultsRequest
from ..models.projects import ImageLayer, LabelProject, Model, Project
from ..models.visualizer import Imagery, Visualizer
from ..utils.prediction_readiness import artifact_api_url, prediction_flavor
from .metadata import MetadataProcessor
from .prediction_results import PredictionResultsProcessor


def build_visualizer(
    model: Model,
    layer: ImageLayer,
    project: Project,
    labels: LabelProject,
    titiler_endpoint: str,
) -> Visualizer:
    bounds = labels.features[0].bbox or [] if labels.features else []

    def raster(url: str | None, colormap: str = "") -> Imagery:
        tile_url = (
            f"{titiler_endpoint}cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}"
            f"?scale=1&url={quote(url, safe='')}{colormap}"
            if url
            else ""
        )
        return Imagery(url=tile_url, bounds=bounds)

    flavor = prediction_flavor(model)
    predicted_url = (
        model.predictedDamageLayerUrl if flavor == "inference" else None
    )
    classified_url = (
        predicted_url.replace("_visualizer.tif", "_predictions.tif")
        if predicted_url
        else None
    )
    colormap = "&colormap=" + quote(
        json.dumps(
            {
                "0": [0, 0, 0, 0],
                "1": [0, 0, 0, 0],
                "2": [0, 255, 0, 255],
                "3": [255, 0, 0, 255],
            }
        ),
        safe="",
    )
    results = PredictionResultsProcessor.response(model, layer)
    return Visualizer(
        projectId=project.projectId,
        imageLayerId=layer.imageLayerId,
        modelId=model.modelId,
        projectName=project.name or "",
        eventDate=project.eventDate,
        studyArea=labels.features or [],
        preDisasterImagery=raster(layer.preEventProcessedImageryUrl),
        postDisasterImagery=raster(layer.postEventProcessedImageryUrl),
        predictedDamageLayer=raster(predicted_url) if predicted_url else None,
        predictionsLayer=raster(classified_url, colormap)
        if classified_url
        else None,
        footprintTilesUrl=artifact_api_url(model, "footprint_pmtiles")
        if layer.footprintPmtilesUrl
        else None,
        predictionAttrsUrl=results["predictionAttrsUrl"],
        gpkgUrl=results["gpkgUrl"],
        predictionRevision=model.predictionRevision,
        flavor=flavor,
        supportsThreshold=flavor == "inference",
        buildingCount=model.predictedBuildingCount,
        predictionsReady=results["predictionsReady"],
        predictionsReadiness=results["predictionsReadiness"],
        rawPredictionsReady=results["rawPredictionsReady"],
        sourceTypePreEvent=layer.sourceTypePreEvent,
        sourceTypePostEvent=layer.sourceTypePostEvent,
        imageryCaptureDatePreEvent=layer.imageryCaptureDatePreEvent,
        imageryCaptureDatePostEvent=layer.imageryCaptureDatePostEvent,
    )


class VisualizerProcessor(PredictionResultsProcessor):
    def load(self, request: ResultsRequest) -> Visualizer:
        model, layer = self.context(request)
        metadata_types = self.config.get_metadata_types()
        raw_project = MetadataProcessor(
            data_type=metadata_types.PROJECT.value,
            partition_key=request.projectId,
            config=self.config,
        ).load_strict(request.projectId)
        if not raw_project:
            raise FileNotFoundError("Project not found")
        project = Project.model_validate(raw_project)
        if project.projectId != request.projectId:
            raise FileNotFoundError("Project not found")
        raw_labels = MetadataProcessor(
            data_type=metadata_types.LABELS.value,
            partition_key=request.projectId,
            config=self.config,
        ).load_all_from_partition()
        labels = next(
            (
                LabelProject.model_validate(item)
                for item in raw_labels
                if item.get("imageLayerId") == request.imageLayerId
            ),
            LabelProject(),
        )
        return build_visualizer(
            model, layer, project, labels, self.config.titiler_endpoint
        )
