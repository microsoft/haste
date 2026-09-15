# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Existing catalog storage with explicit inference compatibility."""

from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import Config
from ..models.pretrained_inference import CatalogInferenceSpec
from ..models.projects import ImageLayer, Model
from ..models.training import CatalogModel
from ..utils.catalog_lock import catalog_lock
from ..utils.label_classes import normalize_class_name
from ..utils.logs import Logger
from ..utils.metadata import MetadataUtils
from ..utils.source_types import normalize_source_type
from .catalog_metadata import CatalogMetadataProcessor


class CatalogConflictError(ValueError):
    pass


class ModelCatalogProcessor:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.metadata = CatalogMetadataProcessor(
            self.config.get_metadata_types().MODEL_CATALOG.value,
            config=self.config,
        )
        self.artifacts = UnifiedArtifactStorage(
            self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )

    def records(self) -> list[dict[str, Any]]:
        try:
            document = self.metadata.load("index")
        except FileNotFoundError:
            return []
        records = (document or {}).get("modelCatalog", [])
        if not isinstance(records, list) or not all(
            isinstance(row, dict) for row in records
        ):
            raise RuntimeError("Invalid catalog document")
        return records

    def find(self, name: str) -> CatalogModel:
        matches = [
            record
            for record in self.records()
            if record.get("baseModelName", "").casefold() == name.casefold()
        ]
        if not matches:
            raise FileNotFoundError("Catalog model not found")
        if len(matches) != 1:
            raise CatalogConflictError("Ambiguous catalog model")
        return CatalogModel.model_validate(matches[0])

    def layer(self, project_id: str, layer_id: str) -> ImageLayer:
        record = CatalogMetadataProcessor(
            self.config.get_metadata_types().IMAGELAYER.value,
            project_id,
            self.config,
        ).load(layer_id)
        layer = ImageLayer.model_validate(record)
        if layer.projectId != project_id or layer.imageLayerId != layer_id:
            raise ValueError("Image layer does not belong to this project")
        return layer

    def resolve_spec(self, entry: CatalogModel) -> CatalogInferenceSpec:
        if (
            entry.capabilities is not None
            and "inference" not in entry.capabilities
        ):
            raise ValueError(
                "This catalog model is available for training only"
            )
        if entry.inferenceSpec is not None:
            spec = entry.inferenceSpec.model_copy(deep=True)
            if entry.source == "haste":
                current = self._legacy_spec(entry)
                if (
                    spec.checkpointFilePath != current.checkpointFilePath
                    or spec.experimentConfig != current.experimentConfig
                ):
                    raise ValueError(
                        "The source recipe changed; re-register this catalog model"
                    )
        else:
            spec = self._legacy_spec(entry)
        for path in (spec.checkpointFilePath, spec.backboneConfigPath):
            if path:
                relative = self.artifacts.resolve_artifact_path(path)
                if not self.artifacts.artifact_exists(relative):
                    raise FileNotFoundError(
                        "A required catalog asset is unavailable"
                    )
        if (
            spec.checkpointEtag
            and self.artifacts.get_artifact_etag(spec.checkpointFilePath)
            != spec.checkpointEtag
        ):
            raise ValueError(
                "The catalog checkpoint changed; re-register its recipe"
            )
        return spec

    def inference_image(self, spec: CatalogInferenceSpec) -> str:
        settings = self.config.get_azure_batch_config()
        image = settings[
            (
                "transformer_inference_docker_image"
                if spec.adapter == "dinov3_upernet"
                else "docker_image"
            )
        ]
        if not image:
            raise ValueError("A transformer inference image is not configured")
        return image

    def _legacy_spec(self, entry: CatalogModel) -> CatalogInferenceSpec:
        if entry.source != "haste" or not entry.projectId or not entry.modelId:
            raise ValueError(
                "This external model has no supported inference recipe"
            )
        model = Model.model_validate(
            CatalogMetadataProcessor(
                self.config.get_metadata_types().MODEL.value,
                entry.projectId,
                self.config,
            ).load(entry.modelId)
        )
        if (
            model.projectId != entry.projectId
            or model.modelId != entry.modelId
        ):
            raise ValueError("Catalog source model identity mismatch")
        if (
            model.modelType not in (None, "trained")
            or model.status != "Processed"
        ):
            raise ValueError(
                "The source HASTE model is not a completed trained model"
            )
        if not entry.checkpointFilePath or not model.checkpointPath:
            raise ValueError("The source checkpoint is unavailable")
        checkpoint = self.artifacts.resolve_artifact_path(
            entry.checkpointFilePath
        )
        current = self.artifacts.resolve_artifact_path(
            f"{model.checkpointPath.rstrip('/')}/last.ckpt"
        )
        if checkpoint != current:
            raise ValueError(
                "The source model changed; re-register its matching inference recipe"
            )
        experiment = CatalogMetadataProcessor(
            self.config.get_metadata_types().EXPERIMENT_CONFIG.value,
            entry.projectId,
            self.config,
        ).load(entry.modelId, data_format="yaml")
        imagery = experiment.get("imagery") or {}
        inference = {
            key: value
            for key, value in (experiment.get("inference") or {}).items()
            if value is not None
        }
        classes = (experiment.get("labels") or {}).get("classes") or []
        if (
            len(classes) < 3
            or normalize_class_name(classes[2]) != "damaged building"
        ):
            raise ValueError(
                "The checkpoint label layout is not compatible with HASTE damage outputs"
            )
        return CatalogInferenceSpec(
            adapter="legacy_haste",
            checkpointFilePath=checkpoint,
            checkpointEtag=self.artifacts.get_artifact_etag(checkpoint),
            inputKind="raw",
            numChannels=imagery.get("num_channels"),
            normalizationMeans=imagery.get("normalization_means"),
            normalizationStds=imagery.get("normalization_stds"),
            experimentConfig=deepcopy(experiment),
            patchSize=inference.get("patch_size", 256),
            padding=inference.get("padding", 64),
            batchSize=inference.get("batch_size", 1),
        )

    @staticmethod
    def compatible_layer(
        spec: CatalogInferenceSpec, layer: ImageLayer
    ) -> None:
        if layer.workflowType not in (None, "standard"):
            raise ValueError(
                "Catalog inference is available on standard image layers only"
            )
        if layer.status != "Processed":
            raise ValueError(
                "Finish imagery processing before running inference"
            )
        if not layer.buildingFootprintsUrl:
            raise ValueError("The layer has no cached building footprints")
        image = (
            layer.postEventProcessedImageryUrl
            if spec.inputKind == "rgb"
            else layer.postEventMosaicCogImageryUrl
        )
        if not image:
            raise ValueError("The layer has no compatible post-event imagery")
        if spec.inputKind == "raw" and layer.normalizationMeans:
            if len(layer.normalizationMeans) < spec.numChannels:
                raise ValueError(
                    "The layer has fewer bands than the source checkpoint requires"
                )

    def list(
        self,
        capability: str | None = None,
        layer: ImageLayer | None = None,
        event_types: list[str] | None = None,
        imagery_source: str | None = None,
    ) -> list[dict[str, Any]]:
        if capability not in (None, "training", "inference"):
            raise ValueError("Unknown catalog capability")
        output = []
        for raw in self.records():
            try:
                entry = CatalogModel.model_validate(raw)
            except ValidationError as error:
                raise RuntimeError("Invalid catalog entry") from error
            if (
                capability == "training"
                and entry.capabilities is not None
                and "training" not in entry.capabilities
            ):
                continue
            # Provider/event matching belongs to the legacy fine-tuning picker,
            # not to generic RGB inference eligibility.
            if capability != "inference":
                if event_types and not {
                    x.casefold() for x in event_types
                }.intersection(x.casefold() for x in entry.eventTypes or []):
                    continue
                if imagery_source and normalize_source_type(
                    entry.imagerySource or ""
                ) != normalize_source_type(imagery_source):
                    continue
            row = entry.model_dump(mode="json")
            try:
                spec = self.resolve_spec(entry)
                self.inference_image(spec)
                if layer:
                    self.compatible_layer(spec, layer)
                row["inferenceReady"] = True
                row["inferenceReadiness"] = {
                    "ready": True,
                    "reason": "ready",
                    "detail": "Ready for inference",
                }
            except (ValueError, FileNotFoundError) as error:
                row["inferenceReady"] = False
                detail = (
                    "The catalog inference recipe is invalid"
                    if isinstance(error, ValidationError)
                    else str(error)
                )
                row["inferenceReadiness"] = {
                    "ready": False,
                    "reason": "incompatible",
                    "detail": detail,
                }
            output.append(row)
        return sorted(
            output,
            key=lambda row: row.get("cataloguedDate") or "",
            reverse=True,
        )

    def add(
        self, entry: CatalogModel, *, idempotent: bool = False
    ) -> CatalogModel:
        with catalog_lock(self.config):
            records = self.records()
            existing = next(
                (
                    row
                    for row in records
                    if row.get("baseModelName", "").casefold()
                    == entry.baseModelName.casefold()
                ),
                None,
            )
            if existing:
                old = CatalogModel.model_validate(existing)
                fields = {"cataloguedDate", "cataloguedByUser", "usedByModels"}
                if idempotent and old.model_dump(
                    exclude=fields
                ) == entry.model_dump(exclude=fields):
                    return old
                raise CatalogConflictError(
                    "A model with this name already exists in the catalog"
                )
            if entry.modelId and any(
                row.get("modelId") == entry.modelId for row in records
            ):
                raise CatalogConflictError(
                    "This source model is already catalogued"
                )
            entry = entry.model_copy(deep=True)
            entry.cataloguedDate = (
                entry.cataloguedDate or MetadataUtils.get_timestamp()
            )
            if entry.source == "haste":
                if not entry.projectId or not entry.modelId:
                    raise ValueError(
                        "HASTE catalog entries require a source project and model"
                    )
                source = Model.model_validate(
                    CatalogMetadataProcessor(
                        self.config.get_metadata_types().MODEL.value,
                        entry.projectId,
                        self.config,
                    ).load(entry.modelId)
                )
                if source.status != "Processed" or not source.checkpointPath:
                    raise ValueError(
                        "Only completed HASTE models with a checkpoint can be catalogued"
                    )
                entry.checkpointFilePath = (
                    entry.checkpointFilePath
                    or f"{source.checkpointPath}/last.ckpt"
                )
                if entry.inferenceSpec is None and entry.capabilities is None:
                    try:
                        entry.inferenceSpec = self.resolve_spec(entry)
                    except (ValueError, FileNotFoundError) as error:
                        Logger.get_logger(__name__).info(
                            "Catalog entry remains training-only (%s)",
                            type(error).__name__,
                        )
                        entry.capabilities = ["training"]
                    else:
                        entry.capabilities = ["training", "inference"]
            elif not entry.checkpointFilePath:
                raise ValueError(
                    "External catalog entries require a checkpoint"
                )
            if entry.inferenceSpec:
                self.resolve_spec(entry)
            records.append(entry.model_dump(mode="json"))
            self.metadata.save("index", {"modelCatalog": records})
            return entry

    def delete(self, name: str | None, model_id: str | None) -> dict[str, Any]:
        if not name and not model_id:
            raise ValueError("A catalog name or source model ID is required")
        with catalog_lock(self.config):
            records = self.records()
            matches = [
                row
                for row in records
                if (
                    name
                    and row.get("baseModelName", "").casefold()
                    == name.casefold()
                )
                or (model_id and row.get("modelId") == model_id)
            ]
            if not matches:
                raise FileNotFoundError("Catalog model not found")
            if len(matches) != 1:
                raise CatalogConflictError("Ambiguous catalog model")
            removed = matches[0]
            self.metadata.save(
                "index",
                {
                    "modelCatalog": [
                        row for row in records if row is not removed
                    ]
                },
            )
            return removed
