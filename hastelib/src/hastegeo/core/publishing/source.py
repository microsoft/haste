from pathlib import PurePosixPath
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

from ..artifact_storage.unified_artifact_storage import UnifiedArtifactStorage
from ..config import ArtifactTypes, Config
from ..models.projects import ImageLayer, Model, Project
from ..models.publishing import (
    ArtifactBundle,
    ArtifactKind,
    PublishDatasetOptions,
    PublishRequest,
    SourceArtifact,
)
from ..processors.metadata import MetadataProcessor
from ..utils.metadata import MetadataUtils


class PublishingSourceNotFoundError(FileNotFoundError):
    """Raised when a requested project, layer, or model does not exist."""


class PublishingSourceNotEligibleError(RuntimeError):
    """Raised when inference has not produced a publishable result."""


class PublishingArtifactUnavailableError(RuntimeError):
    """Raised when a requested or supporting artifact is unavailable."""


# Source-type dropdown values that carry no imagery-provider meaning (the
# "Unknown" option and bring-your-own / processing-profile placeholders).
# Excluded from provider attribution so they don't surface as bogus STAC
# providers. "mercy_corps" is a processing profile, not an imagery vendor.
_NON_PROVIDER_SOURCE_TYPES = frozenset(
    {"", "n/a", "na", "none", "unknown", "rgb/no_processing", "mercy_corps"}
)


def _imagery_sources(image_layer: ImageLayer) -> list:
    """Distinct imagery source types for provider attribution, in order.

    Pulls the pre/post-event source types (and the legacy ``sourceType``) from
    the image layer, preserving order and dropping blanks/duplicates and
    non-provider placeholders (e.g. ``n/a``, ``rgb/no_processing``).
    """
    sources: list = []
    seen = set()
    for value in (
        image_layer.sourceTypePreEvent,
        image_layer.sourceTypePostEvent,
        image_layer.sourceType,
    ):
        if not value:
            continue
        normalized = value.strip()
        key = normalized.lower()
        if key in _NON_PROVIDER_SOURCE_TYPES or key in seen:
            continue
        seen.add(key)
        sources.append(normalized)
    return sources


ARTIFACT_FIELDS: Dict[ArtifactKind, Tuple[str, str, str]] = {
    ArtifactKind.GPKG: (
        "model",
        "gpkgUrl",
        "application/geopackage+sqlite3",
    ),
    ArtifactKind.VALID_MASK: (
        "layer",
        "validAreaMaskUrl",
        "application/geo+json",
    ),
    ArtifactKind.FOOTPRINTS: (
        "layer",
        "buildingFootprintsUrl",
        "application/geopackage+sqlite3",
    ),
    ArtifactKind.PROCESSED_COG: (
        "layer",
        "postEventProcessedImageryUrl",
        "image/tiff; application=geotiff; profile=cloud-optimized",
    ),
}


class PublishingSourceResolver:
    """Resolve publishable source metadata into verified storage artifacts."""

    def __init__(
        self,
        config: Optional[Config] = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
        artifact_storage: Optional[UnifiedArtifactStorage] = None,
    ) -> None:
        self.config = config or Config()
        self.processor_factory = processor_factory
        self.artifact_storage = artifact_storage or UnifiedArtifactStorage(
            storage_type=self.config.artifact_storage_type,
            **self.config.artifact_storage_config,
        )

    def _load_source(
        self,
        project_id: str,
        image_layer_id: str,
        model_id: str,
    ) -> Tuple[Project, ImageLayer, Model]:
        metadata_types = self.config.get_metadata_types()
        try:
            project = Project(
                **self.processor_factory(
                    data_type=metadata_types.PROJECT.value,
                    partition_key=project_id,
                    config=self.config,
                ).load(project_id)
            )
            image_layer = ImageLayer(
                **self.processor_factory(
                    data_type=metadata_types.IMAGELAYER.value,
                    partition_key=project_id,
                    config=self.config,
                ).load(image_layer_id)
            )
            model = Model(
                **self.processor_factory(
                    data_type=metadata_types.MODEL.value,
                    partition_key=project_id,
                    config=self.config,
                ).load(model_id)
            )
        except FileNotFoundError as error:
            raise PublishingSourceNotFoundError(str(error)) from error

        if image_layer.projectId != project_id:
            raise PublishingSourceNotFoundError(
                "Image layer does not belong to the requested project"
            )
        if (
            model.projectId != project_id
            or model.imageLayerId != image_layer_id
        ):
            raise PublishingSourceNotFoundError(
                "Model does not belong to the requested project and image layer"
            )
        completed = self.config.get_status_types().COMPLETED.value
        # Embedding models signal completion via `status`; trained/inference
        # models via `inferenceStatus`. Gate on the field that actually applies.
        if model.modelType == "embedding":
            is_complete = model.status == completed
        else:
            is_complete = model.inferenceStatus == completed
        if not is_complete:
            raise PublishingSourceNotEligibleError(
                "Model must be Processed before publishing"
            )
        return project, image_layer, model

    def ensure_project_exists(self, project_id: str) -> None:
        metadata_types = self.config.get_metadata_types()
        try:
            self.processor_factory(
                data_type=metadata_types.PROJECT.value,
                partition_key=project_id,
                config=self.config,
            ).load(project_id)
        except FileNotFoundError as error:
            raise PublishingSourceNotFoundError(str(error)) from error

    def _available_artifacts(
        self, image_layer: ImageLayer, model: Model
    ) -> list[SourceArtifact]:
        sources = {"layer": image_layer, "model": model}
        expected_paths = self._expected_artifact_paths(image_layer, model)
        artifacts = []
        for kind, (
            source_name,
            field_name,
            media_type,
        ) in ARTIFACT_FIELDS.items():
            location = getattr(sources[source_name], field_name)
            if not location:
                continue
            try:
                source_path = self.artifact_storage.resolve_artifact_path(
                    location
                )
                if source_path not in expected_paths.get(kind, set()):
                    continue
                if not self.artifact_storage.artifact_exists(source_path):
                    continue
                size_bytes = self.artifact_storage.get_artifact_size(
                    source_path
                )
                source_etag = self.artifact_storage.get_artifact_etag(
                    source_path
                )
            except (FileNotFoundError, ValueError):
                continue
            artifacts.append(
                SourceArtifact(
                    kind=kind,
                    sourcePath=source_path,
                    mediaType=media_type,
                    sizeBytes=size_bytes,
                    sourceEtag=source_etag,
                )
            )
        return artifacts

    @staticmethod
    def _completed_preprocess_task(image_layer: ImageLayer) -> Optional[str]:
        job = image_layer.preprocessJob
        if (
            image_layer.status != "Processed"
            or job is None
            or job.status != "Processed"
            or job.projectId != image_layer.projectId
            or job.imageLayerId != image_layer.imageLayerId
            or not job.taskId
        ):
            return None
        return str(job.taskId)

    @classmethod
    def _expected_layer_output_path(
        cls,
        image_layer: ImageLayer,
        artifact_type,
        extension: str,
    ) -> Optional[str]:
        task_id = cls._completed_preprocess_task(image_layer)
        if task_id is None:
            return None
        project_id = str(image_layer.projectId)
        file_name = (
            artifact_type.value.substitute(
                projectId=project_id,
                imageLayerId=str(image_layer.imageLayerId),
            )
            + extension
        )
        return str(
            PurePosixPath(
                MetadataUtils.hash_string(project_id),
                task_id,
                file_name,
            )
        )

    def resolve_layer_output(
        self,
        image_layer: ImageLayer,
        location: Optional[str],
        artifact_type,
        extension: str,
    ) -> str:
        expected_path = self._expected_layer_output_path(
            image_layer, artifact_type, extension
        )
        if expected_path is None:
            raise PublishingSourceNotEligibleError(
                "Image layer preprocessing must be Processed"
            )
        if not location:
            raise PublishingArtifactUnavailableError(
                "Required image layer output is unavailable"
            )
        source_path = self.artifact_storage.resolve_artifact_path(location)
        if source_path != expected_path:
            raise PublishingArtifactUnavailableError(
                "Image layer output does not match its preprocessing job"
            )
        if not self.artifact_storage.artifact_exists(source_path):
            raise PublishingArtifactUnavailableError(
                "Required image layer output is unavailable"
            )
        return source_path

    def resolve_layer_artifact(
        self, image_layer: ImageLayer, kind: ArtifactKind
    ) -> SourceArtifact:
        if kind not in {
            ArtifactKind.VALID_MASK,
            ArtifactKind.FOOTPRINTS,
            ArtifactKind.PROCESSED_COG,
        }:
            raise ValueError("Artifact kind is not owned by an image layer")
        _, field_name, media_type = ARTIFACT_FIELDS[kind]
        artifact_type_and_extension = {
            ArtifactKind.VALID_MASK: (
                ArtifactTypes.VALID_AREA_MASK,
                ".geojson",
            ),
            ArtifactKind.FOOTPRINTS: (
                ArtifactTypes.BUILDING_FOOTPRINTS,
                ".gpkg",
            ),
            ArtifactKind.PROCESSED_COG: (
                ArtifactTypes.POST_EVENT_PROCESSED_COG,
                ".tif",
            ),
        }
        artifact_type, extension = artifact_type_and_extension[kind]
        source_path = self.resolve_layer_output(
            image_layer,
            getattr(image_layer, field_name),
            artifact_type,
            extension,
        )
        return SourceArtifact(
            kind=kind,
            sourcePath=source_path,
            mediaType=media_type,
            sizeBytes=self.artifact_storage.get_artifact_size(source_path),
            sourceEtag=self.artifact_storage.get_artifact_etag(source_path),
        )

    @staticmethod
    def _expected_artifact_paths(
        image_layer: ImageLayer, model: Model
    ) -> Dict[ArtifactKind, Set[str]]:
        project_id = str(image_layer.projectId)
        project_prefix = MetadataUtils.hash_string(project_id)
        image_layer_id = str(image_layer.imageLayerId)
        expected: Dict[ArtifactKind, Set[str]] = {
            kind: set() for kind in ArtifactKind
        }

        preprocess_task_id = (
            PublishingSourceResolver._completed_preprocess_task(image_layer)
        )
        if preprocess_task_id:
            task_prefix = PurePosixPath(project_prefix, preprocess_task_id)
            layer_artifacts = {
                ArtifactKind.VALID_MASK: (
                    ArtifactTypes.VALID_AREA_MASK.value.substitute(
                        projectId=project_id,
                        imageLayerId=image_layer_id,
                    )
                    + ".geojson"
                ),
                ArtifactKind.FOOTPRINTS: (
                    ArtifactTypes.BUILDING_FOOTPRINTS.value.substitute(
                        projectId=project_id,
                        imageLayerId=image_layer_id,
                    )
                    + ".gpkg"
                ),
                ArtifactKind.PROCESSED_COG: (
                    ArtifactTypes.POST_EVENT_PROCESSED_COG.value.substitute(
                        projectId=project_id,
                        imageLayerId=image_layer_id,
                    )
                    + ".tif"
                ),
            }
            for kind, file_name in layer_artifacts.items():
                expected[kind].add(str(task_prefix / file_name))

        if (
            model.modelType == "embedding"
            and model.status == "Processed"
            and model.embeddingJob is not None
            and model.embeddingJob.status == "Processed"
            and model.embeddingJob.projectId == project_id
            and str(model.embeddingJob.modelId) == str(model.modelId)
            and model.embeddingJob.taskId
        ):
            file_name = (
                ArtifactTypes.BUILDING_PREDICTIONS_GPKG.value.substitute(
                    modelName=str(model.modelId)
                )
                + ".gpkg"
            )
            expected[ArtifactKind.GPKG].add(
                str(PurePosixPath(project_prefix, file_name))
            )
        elif model.currentInferenceTaskId:
            current_jobs = [
                job
                for job in model.inferenceJobs or []
                if job.taskId == model.currentInferenceTaskId
                and job.projectId == project_id
                and str(job.modelId) == str(model.modelId)
                and job.status == "Processed"
            ]
            expected_output_path = str(
                PurePosixPath(project_prefix, model.currentInferenceTaskId)
            )
            if (
                len(current_jobs) == 1
                and model.inferenceOutputPath == expected_output_path
            ):
                file_name = (
                    ArtifactTypes.INFERENCE_GPKG.value.substitute(
                        modelName=str(model.name)
                    )
                    + ".gpkg"
                )
                if PurePosixPath(file_name).name == file_name:
                    expected[ArtifactKind.GPKG].update(
                        {
                            str(
                                PurePosixPath(expected_output_path, file_name)
                            ),
                            str(
                                PurePosixPath(
                                    expected_output_path,
                                    "inference",
                                    file_name,
                                )
                            ),
                        }
                    )

        return expected

    def resolve_options(
        self,
        project_id: str,
        image_layer_id: str,
        model_id: str,
    ) -> PublishDatasetOptions:
        project, image_layer, model = self._load_source(
            project_id, image_layer_id, model_id
        )
        available_artifacts = self._available_artifacts(image_layer, model)
        if not available_artifacts:
            raise PublishingSourceNotEligibleError(
                "Model has no available publishable artifacts"
            )
        project_name = project.name or project_id
        image_layer_name = image_layer.name or image_layer_id
        return PublishDatasetOptions(
            projectId=project_id,
            projectName=project_name,
            imageLayerId=image_layer_id,
            imageLayerName=image_layer_name,
            modelId=model_id,
            modelName=model.name or model_id,
            defaultName=f"{project_name} – {image_layer_name}",
            imagerySources=_imagery_sources(image_layer),
            availableArtifacts=available_artifacts,
        )

    def resolve_bundle(
        self,
        request: PublishRequest,
        supporting_kinds: Iterable[ArtifactKind] = (),
        options: Optional[PublishDatasetOptions] = None,
    ) -> ArtifactBundle:
        options = options or self.resolve_options(
            str(request.projectId), request.imageLayerId, request.modelId
        )
        available = {
            artifact.kind: artifact for artifact in options.availableArtifacts
        }
        selected = []
        for kind in request.artifacts:
            if kind not in available:
                raise PublishingArtifactUnavailableError(
                    f"Requested artifact is unavailable: {kind.value}"
                )
            selected.append(available[kind])

        selected_kinds = set(request.artifacts)
        supporting = []
        for kind in sorted(set(supporting_kinds), key=lambda item: item.value):
            if kind not in available:
                raise PublishingArtifactUnavailableError(
                    f"Required supporting artifact is unavailable: {kind.value}"
                )
            if kind not in selected_kinds:
                supporting.append(available[kind])
        return ArtifactBundle(
            selectedArtifacts=selected,
            supportingArtifacts=supporting,
        )
