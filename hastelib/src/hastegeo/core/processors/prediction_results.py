# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Eager interactive result publication and protected read-only resolution."""

import asyncio
import os
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any, Callable

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..models.prediction_results import (
    BuildingPredictionsRequest,
    ModelArtifactRequest,
    PredictionAttributes,
    ResultsRequest,
)
from ..models.projects import ImageLayer, Model
from ..utils.blob import BlobRange, read_blob_range
from ..utils.metadata import MetadataUtils
from ..utils.prediction_attrs import attrs_artifact_name
from ..utils.prediction_readiness import (
    artifact_api_url,
    raw_predictions_readiness,
    results_readiness,
)
from .building_predictions import write_building_predictions
from .metadata import MetadataProcessor
from .prediction_generations import (
    PredictionGenerationRepository,
    PredictionSupersededError,
)

MAX_ATTRIBUTES_BYTES = 256 * 1024**2
MODEL_ARTIFACT_FIELDS = {
    "gpkg": "gpkgUrl",
    "prediction_attrs": "predictionAttrsUrl",
    "sidecar": "featuresSidecarUrl",
    "geojson": "embeddingsGeoJSONUrl",
}


class PredictionRequestError(ValueError):
    """A validated request has an invalid association or prediction coverage."""


async def read_result_artifact(
    url: str, offset: int, length: int | None, config: Config
) -> BlobRange:
    if config.artifact_storage_type != "local":
        return await read_blob_range(url, offset, length)
    storage = UnifiedArtifactStorage(
        storage_type="local", **config.artifact_storage_config
    )
    relative = storage.resolve_artifact_path(url)
    path = Path(storage.get_file_path(relative))

    def read() -> BlobRange:
        stat = path.stat()
        with path.open("rb") as source:
            source.seek(offset)
            data = source.read() if length is None else source.read(length)
        return BlobRange(
            data,
            stat.st_size,
            "application/octet-stream",
            f"{stat.st_mtime_ns}-{stat.st_size}",
        )

    return await asyncio.to_thread(read)


def validate_uploaded_pair(
    storage: UnifiedArtifactStorage,
    gpkg_path: str,
    attrs_path: str,
    revision: str,
    flavor: str,
) -> PredictionAttributes:
    """Verify actual uploaded storage, not node files or generated URLs."""
    if (
        not storage.artifact_exists(gpkg_path)
        or storage.get_artifact_size(gpkg_path) <= 0
    ):
        raise FileNotFoundError("Uploaded prediction GeoPackage is missing")
    attributes = PredictionAttributes.model_validate_json(
        storage.read_artifact_bytes(attrs_path, MAX_ATTRIBUTES_BYTES)
    )
    if (
        attributes.predictionRevision != revision
        or attributes.flavor != flavor
    ):
        raise ValueError(
            "Uploaded prediction attributes do not match this generation"
        )
    return attributes


class PredictionResultsProcessor:
    def __init__(
        self,
        config: Config | None = None,
        processor_factory: Callable[..., MetadataProcessor] | None = None,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory or MetadataProcessor
        self.repository = PredictionGenerationRepository(
            self.config, self.processor_factory
        )

    def storage(self, project_id: str | None = None) -> UnifiedArtifactStorage:
        return UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            partition_key=project_id,
            **self.config.artifact_storage_config,
        )

    def layer(self, project_id: str, layer_id: str) -> ImageLayer:
        raw = self.processor_factory(
            data_type=self.config.get_metadata_types().IMAGELAYER.value,
            partition_key=project_id,
            config=self.config,
        ).load_strict(layer_id)
        if not raw:
            raise FileNotFoundError("Image layer not found")
        layer = ImageLayer.model_validate(raw)
        if layer.projectId != project_id or layer.imageLayerId != layer_id:
            raise FileNotFoundError(
                "Image layer does not belong to this project"
            )
        return layer

    def context(self, request: ResultsRequest) -> tuple[Model, ImageLayer]:
        model = self.repository.load(request.projectId, request.modelId)
        if model.imageLayerId != request.imageLayerId:
            raise PredictionRequestError(
                "Model does not belong to the requested image layer"
            )
        return model, self.layer(request.projectId, request.imageLayerId)

    def raw_context(self, request: ResultsRequest) -> tuple[Model, ImageLayer]:
        """Resolve a report's authoritative raw source without viewer gates."""
        model, layer = self.context(request)
        if not raw_predictions_readiness(model)["ready"]:
            raise FileNotFoundError(
                "No raw predictions available for this model"
            )
        return model, layer

    def save_building_predictions(
        self, request: BuildingPredictionsRequest
    ) -> dict[str, Any]:
        model, layer = self.context(request)
        baseline_revision = model.predictionRevision
        if model.modelType != "embedding":
            raise PredictionRequestError(
                "Interactive predictions require an embedding model"
            )
        revision = MetadataUtils.generate_id()
        if not request.predictions:
            with self.repository.lock(
                request.projectId, request.modelId
            ) as lease:
                model = self.repository.load(
                    request.projectId, request.modelId
                )
                if (
                    model.imageLayerId != request.imageLayerId
                    or model.modelType != "embedding"
                ):
                    raise PredictionRequestError("Model association changed")
                if model.predictionRevision != baseline_revision:
                    raise PredictionSupersededError(
                        "Prediction source generation changed before clear"
                    )
                self.repository.initialize(model, revision, clear=True)
                self.repository.save_locked(model, lease)
            return self.response(model, layer)
        if not layer.buildingFootprintsUrl:
            raise FileNotFoundError("Cached building footprints are missing")

        storage = self.storage(request.projectId)
        # Root-relative resolution works for both local file URLs and blobs.
        root_storage = self.storage()
        source_path = root_storage.resolve_artifact_path(
            layer.buildingFootprintsUrl
        )
        namespace = ["prediction_results", request.modelId, revision]
        gpkg_name = (
            self.config.get_artifact_types().BUILDING_PREDICTIONS_GPKG.value.substitute(
                modelName=request.modelId
            )
            + ".gpkg"
        )
        attrs_name = attrs_artifact_name(request.modelId)
        with TemporaryDirectory(dir=self.config.TEMP_DIR) as directory:
            # fetch_artifact is a prefix downloader on Blob and an exact-file
            # copier locally. Check the exact file after downloading.
            if self.config.artifact_storage_type == "local":
                source = root_storage.artifact_storage.get_file_path(
                    source_path
                )
                footprints = root_storage.fetch_artifact(
                    src_path=source, dst_path=directory
                )
                footprints = os.path.join(
                    footprints, os.path.basename(source_path)
                )
            else:
                root_storage.fetch_artifact(
                    src_path=source_path, dst_path=directory
                )
                footprints = os.path.join(directory, source_path)
            if not Path(footprints).is_file():
                raise FileNotFoundError(
                    "Cached building footprints are missing"
                )
            # GIS validates complete IDs/coverage before a good generation is
            # invalidated. The empty clear path never downloads feature data.
            try:
                artifacts = write_building_predictions(
                    footprints,
                    [
                        row.model_dump(exclude_none=True)
                        for row in request.predictions
                    ],
                    os.path.join(directory, gpkg_name),
                    os.path.join(directory, attrs_name),
                    prediction_revision=revision,
                )
            except ValueError:
                raise PredictionRequestError(
                    "Predictions must match the cached footprint source"
                ) from None
            with self.repository.lock(
                request.projectId, request.modelId
            ) as lease:
                model = self.repository.load(
                    request.projectId, request.modelId
                )
                if (
                    model.imageLayerId != request.imageLayerId
                    or model.modelType != "embedding"
                ):
                    raise PredictionRequestError("Model image layer changed")
                if model.predictionRevision != baseline_revision:
                    raise PredictionSupersededError(
                        "Prediction source generation changed during validation"
                    )
                self.repository.initialize(model, revision)
                self.repository.save_locked(model, lease)
            try:
                gpkg_path = storage.store_artifact(
                    artifact_name=gpkg_name,
                    src_path=artifacts.gpkg_path,
                    namespace=namespace,
                )
                attrs_path = storage.store_artifact(
                    artifact_name=attrs_name,
                    src_path=artifacts.attrs_path,
                    namespace=namespace,
                )
                try:
                    attributes = validate_uploaded_pair(
                        storage, gpkg_path, attrs_path, revision, "embedding"
                    )
                except ValueError:
                    raise RuntimeError(
                        "Uploaded prediction artifacts are invalid"
                    ) from None
                gpkg_url = storage.get_download_url(
                    identifier=gpkg_name, extra_partition_keys=namespace
                )
                attrs_url = storage.get_download_url(
                    identifier=attrs_name, extra_partition_keys=namespace
                )
                with self.repository.lock(
                    request.projectId, request.modelId
                ) as lease:
                    model = self.repository.load(
                        request.projectId, request.modelId
                    )
                    if model.predictionRevision != revision:
                        raise PredictionSupersededError(
                            "Prediction generation was superseded"
                        )
                    model.gpkgUrl = gpkg_url
                    model.predictionAttrsUrl = attrs_url
                    model.predictedBuildingCount = attributes.n
                    model.predictedAt = MetadataUtils.get_timestamp()
                    model.predictionState = "ready"
                    model.predictionReadyRevision = revision
                    model.predictionGpkgFilename = gpkg_name
                    model.predictionOutputPrefix = str(
                        PurePosixPath(
                            MetadataUtils.hash_string(request.projectId),
                            *namespace,
                        )
                    )
                    self.repository.save_locked(model, lease)
            except Exception:
                self.repository.fail(
                    request.projectId, request.modelId, revision
                )
                raise
        return self.response(model, layer)

    @staticmethod
    def response(model: Model, layer: ImageLayer) -> dict[str, Any]:
        readiness = results_readiness(model, layer)
        raw_ready = raw_predictions_readiness(model)["ready"]
        return {
            "count": model.predictedBuildingCount,
            "buildingCount": model.predictedBuildingCount,
            "predictedBuildingCount": model.predictedBuildingCount,
            "predictedAt": model.predictedAt,
            "predictionRevision": model.predictionRevision,
            "gpkgUrl": artifact_api_url(model, "gpkg") if raw_ready else None,
            "predictionAttrsUrl": (
                artifact_api_url(model, "prediction_attrs")
                if model.predictionAttrsUrl and raw_ready
                else None
            ),
            "predictionsReady": readiness["ready"],
            "predictionsReadiness": readiness,
            "rawPredictionsReady": raw_ready,
        }

    def list_models(
        self, project_id: str, layer_id: str
    ) -> list[dict[str, Any]]:
        layer = self.layer(project_id, layer_id)
        records = self.repository.metadata(
            project_id
        ).load_all_from_partition()
        output = []
        for raw in records:
            if raw.get("imageLayerId") != layer_id:
                continue
            model = self.repository.load(project_id, str(raw["modelId"]))
            data = model.model_dump()
            response = self.response(model, layer)
            # Keep legacy metadata URLs for existing consumers; readiness is
            # server-derived, while the visualizer uses only protected URLs.
            data.update(
                {
                    key: value
                    for key, value in response.items()
                    if key not in ("gpkgUrl", "predictionAttrsUrl")
                }
            )
            output.append(data)
        return output

    def resolve_artifact(
        self, request: ModelArtifactRequest
    ) -> tuple[str, bool]:
        model = None
        if request.modelId:
            model = self.repository.load(request.projectId, request.modelId)
            if (
                request.imageLayerId
                and request.imageLayerId != model.imageLayerId
            ):
                raise PredictionRequestError(
                    "Model does not belong to the requested image layer"
                )
        if request.kind == "footprint_pmtiles":
            layer = self.layer(
                request.projectId, request.imageLayerId or model.imageLayerId
            )
            url = layer.footprintPmtilesUrl
        else:
            if request.kind in ("gpkg", "prediction_attrs"):
                if (
                    request.predictionRevision
                    and request.predictionRevision != model.predictionRevision
                ):
                    raise FileNotFoundError(
                        "Prediction generation is no longer current"
                    )
                if not raw_predictions_readiness(model)["ready"]:
                    raise FileNotFoundError(
                        "Raw predictions are not available"
                    )
                if request.kind == "prediction_attrs" and (
                    not model.predictionRevision
                    or model.predictionReadyRevision
                    != model.predictionRevision
                ):
                    raise FileNotFoundError(
                        "Matching prediction attributes are unavailable"
                    )
            url = getattr(model, MODEL_ARTIFACT_FIELDS[request.kind])
        if not url:
            raise FileNotFoundError("Artifact is not available")
        # Always revalidate generations: a retired query cannot return another
        # generation's content from browser cache, even though storage is immutable.
        return url, request.kind in ("gpkg", "prediction_attrs")
