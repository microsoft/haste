# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Project-details loading and response assembly."""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..config import Config
from .metadata import MetadataProcessor


class ProjectDetailsProcessor:
    """Load and assemble one project's API detail response."""

    def __init__(
        self,
        project_id: str,
        config: Config | None = None,
        processor_factory: Callable[
            ..., MetadataProcessor
        ] = MetadataProcessor,
    ) -> None:
        self.project_id = project_id
        self.config = config or Config()
        self.processor_factory = processor_factory

    def _processor(self, data_type: str) -> MetadataProcessor:
        return self.processor_factory(
            data_type=data_type,
            partition_key=self.project_id,
            config=self.config,
        )

    def _load(self, data_type: str, key: str) -> dict[str, Any]:
        return self._processor(data_type).load(key)

    def _load_partition(self, data_type: str) -> list[dict[str, Any]]:
        return self._processor(data_type).load_all_from_partition()

    def _load_map(
        self, data_type: str, keys: Sequence[str]
    ) -> dict[str, dict[str, Any] | None]:
        return self._processor(data_type).load_map(keys)

    def _load_train_label_urls(
        self, models: Sequence[Mapping[str, Any]]
    ) -> dict[str, str | None]:
        model_ids = [
            model["modelId"] for model in models if not model.get("labelsUrl")
        ]
        if not model_ids:
            return {}

        processor = self._processor(
            self.config.get_metadata_types().TRAIN_LABELS.value
        )
        try:
            existing_keys = set(processor.list_keys(data_format="geojson"))
        except NotImplementedError:
            urls = {}
            for model_id in model_ids:
                try:
                    urls[model_id] = processor.export(
                        model_id, data_format="geojson"
                    )
                except (FileNotFoundError, NotImplementedError):
                    urls[model_id] = None
            return urls

        urls = {}
        for model_id in model_ids:
            if model_id not in existing_keys:
                urls[model_id] = None
                continue
            try:
                urls[model_id] = processor.build_url(
                    model_id, data_format="geojson"
                )
            except NotImplementedError:
                urls[model_id] = None
        return urls

    async def load(self, include_models: bool) -> dict[str, Any]:
        """Load project metadata concurrently and assemble the response."""
        types = self.config.get_metadata_types()
        project = await asyncio.to_thread(
            self._load, types.PROJECT.value, self.project_id
        )

        partition_types = [types.IMAGELAYER.value, types.LABELS.value]
        if include_models:
            partition_types.append(types.MODEL.value)
        partition_results = await asyncio.gather(
            *(
                asyncio.to_thread(self._load_partition, data_type)
                for data_type in partition_types
            )
        )
        image_layers = partition_results[0]
        label_projects = partition_results[1]
        models = partition_results[2] if include_models else []

        image_layer_ids = [
            image_layer["imageLayerId"] for image_layer in image_layers
        ]
        validation_task = asyncio.to_thread(
            self._load_map, types.VALIDATION.value, image_layer_ids
        )

        if include_models:
            model_ids = [model["modelId"] for model in models]
            (
                validation_by_layer,
                artifacts_by_model,
                train_label_urls_by_model,
            ) = await asyncio.gather(
                validation_task,
                asyncio.to_thread(
                    self._load_map, types.MODEL_ARTIFACTS.value, model_ids
                ),
                asyncio.to_thread(self._load_train_label_urls, models),
            )
        else:
            validation_by_layer = await validation_task
            artifacts_by_model = {}
            train_label_urls_by_model = {}

        return assemble_project_details(
            project=project,
            image_layers=image_layers,
            models=models,
            label_projects=label_projects,
            artifacts_by_model=artifacts_by_model,
            validation_by_layer=validation_by_layer,
            train_label_urls_by_model=train_label_urls_by_model,
            include_models=include_models,
        )


def assemble_project_details(
    project: Mapping[str, Any],
    image_layers: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]],
    label_projects: Sequence[Mapping[str, Any]],
    artifacts_by_model: Mapping[str, Mapping[str, Any] | None],
    validation_by_layer: Mapping[str, Mapping[str, Any] | None],
    train_label_urls_by_model: Mapping[str, str | None],
    include_models: bool,
) -> dict[str, Any]:
    """Assemble the API response from already-loaded metadata records."""
    models_by_layer: dict[str | None, list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for model in models:
        models_by_layer[model.get("imageLayerId")].append(model)

    labels_by_layer: dict[str, Mapping[str, Any]] = {}
    for label_project in label_projects:
        image_layer_id = label_project.get("imageLayerId")
        if (
            image_layer_id is not None
            and image_layer_id not in labels_by_layer
        ):
            labels_by_layer[image_layer_id] = label_project

    assembled_layers: list[dict[str, Any]] = []
    for stored_image_layer in image_layers:
        image_layer = dict(stored_image_layer)
        image_layer_id = image_layer["imageLayerId"]

        if include_models:
            layer_models = sorted(
                models_by_layer.get(image_layer_id, []),
                key=lambda model: model["creationDate"],
                reverse=True,
            )
            assembled_models = []
            for stored_model in layer_models:
                model = dict(stored_model)
                model_id = model["modelId"]
                model["artifacts"] = artifacts_by_model.get(model_id)
                if not model.get("labelsUrl"):
                    model["labelsUrl"] = train_label_urls_by_model.get(
                        model_id
                    )
                assembled_models.append(model)
            image_layer["models"] = assembled_models
            image_layer["modelCount"] = len(assembled_models)

        label_project = labels_by_layer.get(image_layer_id)
        if label_project is not None:
            labels = label_project.get("labels")
            image_layer["labelProjectCount"] = (
                len(labels) if labels is not None else 0
            )
            if not image_layer.get("labelsUrl"):
                image_layer["labelsUrl"] = None

        validation = validation_by_layer.get(image_layer_id)
        validation_labels = validation.get("labels") if validation else None
        image_layer["validationLabelCount"] = len(validation_labels or {})
        assembled_layers.append(image_layer)

    assembled_project = dict(project)
    assembled_project["imageLayer"] = sorted(
        assembled_layers,
        key=lambda image_layer: image_layer["creationDate"],
        reverse=True,
    )
    assembled_project["imageLayerCount"] = len(assembled_layers)
    return assembled_project
