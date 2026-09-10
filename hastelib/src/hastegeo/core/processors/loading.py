# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Route-specific loading processors."""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from azure.core.exceptions import ResourceNotFoundError

from ..config import Config
from ..models.loading import (
    ActiveJob,
    ActiveJobIndicator,
    ActiveJobs,
    LabelingImageLayer,
    LabelingWorkspace,
)
from ..models.projects import ImageLayer, LabelProject, Project
from .metadata import MetadataProcessor

_TERMINAL_STATUSES = frozenset(
    {"processed", "completed", "trained", "failed", "cancelled"}
)


def _is_active_status(status: Any) -> bool:
    return (
        isinstance(status, str)
        and bool(status.strip())
        and status.strip().casefold() not in _TERMINAL_STATUSES
    )


def assemble_active_jobs(
    projects: Sequence[Mapping[str, Any]],
    records_by_project: Mapping[
        str, tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    ],
) -> ActiveJobs:
    """Build compact dashboard jobs from image-layer and model records."""
    jobs: list[ActiveJob] = []
    for project in projects:
        project_id = str(project.get("projectId") or "")
        if not project_id:
            continue
        project_name = str(project.get("name") or "Project")
        image_layers, models = records_by_project.get(project_id, ([], []))

        for layer in image_layers:
            layer_id = str(layer.get("imageLayerId") or "")
            if not layer_id or not _is_active_status(layer.get("status")):
                continue
            layer_name = str(layer.get("name") or "Image layer")
            jobs.append(
                ActiveJob(
                    key=f"imagery-{project_id}-{layer_id}",
                    kind="Imagery",
                    projectName=project_name,
                    name=layer_name,
                    target=f"/project/{project_id}/{layer_id}",
                    indicator=ActiveJobIndicator(
                        id=f"ongoingImagery-{project_id}-{layer_id}",
                        currentStep=layer.get("currentStep") or 0,
                        totalSteps=layer.get("totalSteps") or 0,
                        progressPct=layer.get("progressPct") or 0.0,
                        status=str(layer["status"]),
                        statusMessage=str(layer.get("statusMessage") or ""),
                        prefix="Imagery",
                        contextLabel=f"Image Layer: {layer_name}",
                    ),
                )
            )

        for model in models:
            model_id = str(model.get("modelId") or "")
            layer_id = str(model.get("imageLayerId") or "")
            if not model_id or not layer_id:
                continue
            model_name = str(model.get("name") or "Model")
            target = f"/project/{project_id}/{layer_id}"
            if _is_active_status(model.get("status")):
                jobs.append(
                    ActiveJob(
                        key=f"training-{project_id}-{model_id}",
                        kind="Training",
                        projectName=project_name,
                        name=model_name,
                        target=target,
                        indicator=ActiveJobIndicator(
                            id=f"ongoingTraining-{project_id}-{model_id}",
                            currentStep=model.get("currentStep") or 0,
                            totalSteps=model.get("totalSteps") or 0,
                            progressPct=model.get("progressPct") or 0.0,
                            status=str(model["status"]),
                            statusMessage=str(
                                model.get("statusMessage") or ""
                            ),
                            prefix="Training",
                            contextLabel=f"Model: {model_name} - Training",
                        ),
                    )
                )
            if _is_active_status(model.get("inferenceStatus")):
                jobs.append(
                    ActiveJob(
                        key=f"inference-{project_id}-{model_id}",
                        kind="Inference",
                        projectName=project_name,
                        name=model_name,
                        target=target,
                        indicator=ActiveJobIndicator(
                            id=f"ongoingInference-{project_id}-{model_id}",
                            currentStep=model.get("inferenceCurrentStep") or 0,
                            totalSteps=model.get("inferenceTotalSteps") or 0,
                            progressPct=model.get("inferenceProgressPct")
                            or 0.0,
                            status=str(model["inferenceStatus"]),
                            statusMessage=str(
                                model.get("inferenceStatusMessage") or ""
                            ),
                            prefix="Inference",
                            contextLabel=f"Model: {model_name} - Inference",
                        ),
                    )
                )

    jobs.sort(key=lambda job: job.key)
    return ActiveJobs(jobs=jobs)


class LabelingWorkspaceProcessor:
    """Load the minimum records for one standard labeling workspace."""

    def __init__(
        self,
        project_id: str,
        image_layer_id: str,
        config: Config | None = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
    ) -> None:
        self.project_id = project_id
        self.image_layer_id = image_layer_id
        self.config = config or Config()
        self.processor_factory = processor_factory

    def _processor(self, data_type: str) -> MetadataProcessor:
        return self.processor_factory(
            data_type=data_type,
            partition_key=self.project_id,
            config=self.config,
        )

    async def load(self) -> LabelingWorkspace:
        """Load project and layer concurrently, then resolve labels by key."""
        types = self.config.get_metadata_types()
        project_task = asyncio.to_thread(
            self._processor(types.PROJECT.value).load, self.project_id
        )
        layer_task = asyncio.to_thread(
            self._processor(types.IMAGELAYER.value).load,
            self.image_layer_id,
        )
        try:
            raw_project, raw_layer = await asyncio.gather(
                project_task, layer_task
            )
        except ResourceNotFoundError as error:
            raise FileNotFoundError(
                "Labeling workspace records were not found"
            ) from error
        project = Project(**raw_project)
        image_layer = ImageLayer(**raw_layer)
        if (
            project.projectId != self.project_id
            or image_layer.imageLayerId != self.image_layer_id
            or image_layer.projectId != self.project_id
        ):
            raise FileNotFoundError("Labeling workspace records do not match")
        label_project = await self._load_label_project(image_layer)
        return LabelingWorkspace(
            labelProject=label_project,
            imageLayer=LabelingImageLayer(
                imageLayerId=self.image_layer_id,
                name=image_layer.name,
                sourceTypePostEvent=image_layer.sourceTypePostEvent,
            ),
            eventTypes=project.eventTypes or [],
            primaryClasses=project.primaryClasses or [],
        )

    async def _load_label_project(
        self, image_layer: ImageLayer
    ) -> LabelProject:
        labels = self._processor(self.config.get_metadata_types().LABELS.value)
        if image_layer.labelProjectId:
            try:
                raw_label = await asyncio.to_thread(
                    labels.load, image_layer.labelProjectId
                )
                if (
                    raw_label.get("projectId") == self.project_id
                    and raw_label.get("imageLayerId") == self.image_layer_id
                    and raw_label.get("labelprojectId")
                    == image_layer.labelProjectId
                ):
                    return LabelProject(**raw_label)
            except (FileNotFoundError, ResourceNotFoundError):
                pass

        raw_labels = await asyncio.to_thread(labels.load_all_from_partition)
        raw_label = next(
            (
                label
                for label in raw_labels
                if label.get("projectId") == self.project_id
                and label.get("imageLayerId") == self.image_layer_id
            ),
            None,
        )
        if raw_label is None:
            raise FileNotFoundError(
                f"Label project for image layer {self.image_layer_id} not found"
            )
        return LabelProject(**raw_label)


class ActiveJobsProcessor:
    """Load active jobs without assembling complete project details."""

    def __init__(
        self,
        config: Config | None = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.config = config or Config()
        self.processor_factory = processor_factory
        self.max_concurrency = max_concurrency

    def _processor(
        self, data_type: str, partition_key: str | None = None
    ) -> MetadataProcessor:
        return self.processor_factory(
            data_type=data_type,
            partition_key=partition_key,
            config=self.config,
        )

    async def load(self) -> ActiveJobs:
        """Load candidate project partitions with bounded concurrency."""
        types = self.config.get_metadata_types()
        try:
            stats = await asyncio.to_thread(
                self._processor(types.PROJECT.value).load, "stats"
            )
        except ResourceNotFoundError as error:
            raise FileNotFoundError(
                "Project statistics were not found"
            ) from error
        projects = [
            project
            for project in stats.get("projects", [])
            if project.get("projectId")
            and (
                (project.get("imageLayerCount") or 0) > 0
                or bool(project.get("imageLayerStats"))
                or (project.get("modelsCount") or 0) > 0
                or bool(project.get("modelIds"))
            )
        ]
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def load_project(
            project: Mapping[str, Any],
        ) -> tuple[str, tuple[list[dict[str, Any]], list[dict[str, Any]]],]:
            project_id = str(project["projectId"])
            async with semaphore:
                results = await asyncio.gather(
                    (
                        asyncio.to_thread(
                            self._processor(
                                types.IMAGELAYER.value, project_id
                            ).load_all_from_partition
                        )
                        if (project.get("imageLayerCount") or 0) > 0
                        or project.get("imageLayerStats")
                        else asyncio.sleep(0, result=[])
                    ),
                    (
                        asyncio.to_thread(
                            self._processor(
                                types.MODEL.value, project_id
                            ).load_all_from_partition
                        )
                        if (project.get("modelsCount") or 0) > 0
                        or project.get("modelIds")
                        else asyncio.sleep(0, result=[])
                    ),
                    return_exceptions=True,
                )
                errors = [
                    result
                    for result in results
                    if isinstance(result, BaseException)
                ]
                if errors:
                    raise errors[0]
                layers, models = results
            return project_id, (layers, models)

        results = await asyncio.gather(
            *(load_project(project) for project in projects),
            return_exceptions=True,
        )
        errors = [
            result for result in results if isinstance(result, BaseException)
        ]
        if errors:
            raise errors[0]
        return assemble_active_jobs(projects, dict(results))
