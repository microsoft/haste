# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Paired prediction outputs on Model, using ordinary metadata load/save.

The final re-read rejects known superseded writes; it is not CAS or a
transaction. GIS/upload failure leaves the last successful pair untouched.
"""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

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

MAX_ATTRIBUTES_BYTES = 64 * 1024**2


class PredictionRequestError(ValueError):
    """Invalid model/layer association or prediction coverage."""


class PredictionSupersededError(RuntimeError):
    """Model changed before this output could be published."""


def fetch_prediction_file(
    storage: UnifiedArtifactStorage,
    location: str,
    directory: str,
    max_bytes: int | None = None,
) -> Path:
    """Adapt the existing Local/Blob fetch interface for one expected file."""
    relative = storage.resolve_artifact_path(location)
    if not storage.artifact_exists(relative):
        raise FileNotFoundError("Prediction artifact is missing")
    if (
        max_bytes is not None
        and storage.get_artifact_size(relative) > max_bytes
    ):
        raise ValueError("Prediction attributes exceed the download limit")
    storage.fetch_artifact(
        src_path=storage.get_file_path(relative), dst_path=directory
    )
    path = Path(directory, relative)
    if not path.is_file():  # Local fetch copies the basename into directory.
        path = Path(directory, Path(relative).name)
    if not path.is_file():
        raise FileNotFoundError("Prediction artifact was not downloaded")
    return path


def validate_uploaded_pair(
    storage: UnifiedArtifactStorage,
    gpkg_path: str,
    attrs_path: str,
    revision: str,
    flavor: str,
) -> PredictionAttributes:
    """Check uploaded storage, not a runner's local success status."""
    if (
        not storage.artifact_exists(gpkg_path)
        or storage.get_artifact_size(gpkg_path) <= 0
    ):
        raise FileNotFoundError("Uploaded prediction GeoPackage is missing")
    with TemporaryDirectory() as directory:
        path = fetch_prediction_file(
            storage, attrs_path, directory, MAX_ATTRIBUTES_BYTES
        )
        with path.open("rb") as stream:
            content = stream.read(MAX_ATTRIBUTES_BYTES + 1)
        if len(content) > MAX_ATTRIBUTES_BYTES:
            raise ValueError("Prediction attributes exceed the download limit")
    attrs = PredictionAttributes.model_validate_json(content)
    if attrs.predictionRevision != revision or attrs.flavor != flavor:
        raise ValueError("Prediction attributes do not match this output")
    return attrs


async def read_result_artifact(
    url: str, offset: int, length: int | None, config: Config
) -> BlobRange:
    if config.artifact_storage_type != "local":
        return await read_blob_range(url, offset, length)
    storage = UnifiedArtifactStorage("local", **config.artifact_storage_config)
    path = Path(storage.get_file_path(storage.resolve_artifact_path(url)))

    def read() -> BlobRange:
        stat = path.stat()
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read() if length is None else stream.read(length)
        return BlobRange(
            data,
            stat.st_size,
            "application/octet-stream",
            f"{stat.st_mtime_ns}-{stat.st_size}",
        )

    return await asyncio.to_thread(read)


class PredictionResultsProcessor:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()

    def metadata(
        self, project_id: str, kind: str = "model"
    ) -> MetadataProcessor:
        return MetadataProcessor(kind, project_id, self.config)

    def model(self, project_id: str, model_id: str) -> Model:
        record = self.metadata(project_id).load(model_id)
        if not record:
            raise FileNotFoundError("Model not found")
        model = Model.model_validate(record)
        if model.projectId != project_id or model.modelId != model_id:
            raise PredictionRequestError(
                "Model does not belong to this project"
            )
        return model

    def layer(self, project_id: str, layer_id: str) -> ImageLayer:
        record = self.metadata(
            project_id, self.config.get_metadata_types().IMAGELAYER.value
        ).load(layer_id)
        if not record:
            raise FileNotFoundError("Image layer not found")
        layer = ImageLayer.model_validate(record)
        if layer.projectId != project_id or layer.imageLayerId != layer_id:
            raise PredictionRequestError(
                "Image layer does not belong to this project"
            )
        return layer

    def context(self, request: ResultsRequest) -> tuple[Model, ImageLayer]:
        model = self.model(request.projectId, request.modelId)
        if model.imageLayerId != request.imageLayerId:
            raise PredictionRequestError("Model does not belong to this layer")
        return model, self.layer(request.projectId, request.imageLayerId)

    def _publish(self, baseline: Model, fields: dict[str, Any]) -> Model:
        current = self.model(baseline.projectId, baseline.modelId)
        if (
            current.imageLayerId != baseline.imageLayerId
            or current.predictionRevision != baseline.predictionRevision
        ):
            raise PredictionSupersededError(
                "Model predictions changed before publication"
            )
        self.metadata(current.projectId).save(current.modelId, fields)
        return current.model_copy(update=fields)

    def save_building_predictions(
        self, request: BuildingPredictionsRequest
    ) -> dict[str, Any]:
        model, layer = self.context(request)
        if model.modelType != "embedding":
            raise PredictionRequestError(
                "Interactive predictions require an embedding model"
            )
        revision = MetadataUtils.generate_id()
        fields = dict(
            gpkgUrl=None,
            predictionAttrsUrl=None,
            predictedBuildingCount=0,
            predictionRevision=revision,
        )
        if request.predictions:
            if not layer.buildingFootprintsUrl:
                raise FileNotFoundError(
                    "Cached building footprints are missing"
                )
            storage = UnifiedArtifactStorage(
                self.config.artifact_storage_type,
                **self.config.artifact_storage_config,
            )
            namespace = [
                MetadataUtils.hash_string(model.projectId),
                "predictions",
                model.modelId,
                revision,
            ]
            gpkg_name = f"building_predictions_{model.modelId}.gpkg"
            attrs_name = attrs_artifact_name(model.modelId)
            with TemporaryDirectory(dir=self.config.TEMP_DIR) as directory:
                footprints = fetch_prediction_file(
                    storage, layer.buildingFootprintsUrl, directory
                )
                try:
                    output = write_building_predictions(
                        str(footprints),
                        [
                            row.model_dump(exclude_none=True)
                            for row in request.predictions
                        ],
                        str(Path(directory, gpkg_name)),
                        str(Path(directory, attrs_name)),
                        prediction_revision=revision,
                    )
                except ValueError:
                    raise PredictionRequestError(
                        "Predictions must cover the cached footprints with valid IDs"
                    ) from None
                gpkg = storage.store_artifact(
                    gpkg_name, src_path=output.gpkg_path, namespace=namespace
                )
                attrs = storage.store_artifact(
                    attrs_name, src_path=output.attrs_path, namespace=namespace
                )
                count = validate_uploaded_pair(
                    storage, gpkg, attrs, revision, "embedding"
                ).n
            fields.update(
                gpkgUrl=storage.get_download_url(
                    identifier=gpkg_name, extra_partition_keys=namespace
                ),
                predictionAttrsUrl=storage.get_download_url(
                    identifier=attrs_name, extra_partition_keys=namespace
                ),
                predictedBuildingCount=count,
            )
        fields["predictedAt"] = MetadataUtils.get_timestamp()
        return self.response(self._publish(model, fields), layer)

    @staticmethod
    def response(model: Model, layer: ImageLayer) -> dict[str, Any]:
        raw_ready = raw_predictions_readiness(model)["ready"]
        readiness = results_readiness(model, layer)
        return {
            "count": model.predictedBuildingCount,
            "buildingCount": model.predictedBuildingCount,
            "predictedBuildingCount": model.predictedBuildingCount,
            "predictedAt": model.predictedAt,
            "predictionRevision": model.predictionRevision,
            "gpkgUrl": artifact_api_url(model, "gpkg") if raw_ready else None,
            "predictionAttrsUrl": artifact_api_url(model, "prediction_attrs")
            if raw_ready and model.predictionAttrsUrl
            else None,
            "predictionsReady": readiness["ready"],
            "predictionsReadiness": readiness,
            "rawPredictionsReady": raw_ready,
        }

    def list_models(
        self, project_id: str, layer_id: str
    ) -> list[dict[str, Any]]:
        layer = self.layer(project_id, layer_id)
        rows = self.metadata(project_id).load_all_from_partition()
        for row in rows:
            if row.get("imageLayerId") == layer_id:
                state = self.response(Model.model_validate(row), layer)
                row.update(
                    {
                        k: v
                        for k, v in state.items()
                        if k not in ("gpkgUrl", "predictionAttrsUrl")
                    }
                )
        return [row for row in rows if row.get("imageLayerId") == layer_id]

    def resolve_artifact(
        self, request: ModelArtifactRequest
    ) -> tuple[str, bool]:
        model = (
            self.model(request.projectId, request.modelId)
            if request.modelId
            else None
        )
        if (
            model
            and request.imageLayerId
            and model.imageLayerId != request.imageLayerId
        ):
            raise PredictionRequestError("Model does not belong to this layer")
        if request.kind == "footprint_pmtiles":
            url = self.layer(
                request.projectId, request.imageLayerId or model.imageLayerId
            ).footprintPmtilesUrl
        else:
            if request.kind in ("gpkg", "prediction_attrs"):
                if (
                    request.predictionRevision
                    and request.predictionRevision != model.predictionRevision
                ):
                    raise FileNotFoundError(
                        "Prediction output is no longer current"
                    )
                if not raw_predictions_readiness(model)["ready"]:
                    raise FileNotFoundError("Raw predictions are unavailable")
            field = {
                "gpkg": "gpkgUrl",
                "prediction_attrs": "predictionAttrsUrl",
                "sidecar": "featuresSidecarUrl",
                "geojson": "embeddingsGeoJSONUrl",
            }[request.kind]
            url = getattr(model, field)
        if not url:
            raise FileNotFoundError("Artifact is unavailable")
        return url, request.kind in ("gpkg", "prediction_attrs")
