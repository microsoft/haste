# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Request-boundary rules for persisted workflow state."""

from collections.abc import Collection, Mapping
from typing import Any

IMAGE_LAYER_SERVER_MANAGED_FIELDS = frozenset(
    {
        "buildingFootprintsUrl",
        "creationDate",
        "currentStep",
        "imageryPath",
        "labelProject",
        "labelProjectCount",
        "labelsUrl",
        "modelCount",
        "models",
        "normalizationMeans",
        "normalizationStds",
        "postEventMosaicCogImageryUrl",
        "postEventPreviewUrls",
        "postEventProcessedImageryUrl",
        "preEventMosaicCogImageryUrl",
        "preEventPreviewUrls",
        "preEventProcessedImageryUrl",
        "preprocessJob",
        "previewSourceImageryUrls",
        "processedImageryUrls",
        "progressPct",
        "rawImageryUrls",
        "status",
        "statusMessage",
        "totalSteps",
        "validAreaMaskUrl",
    }
)

INFERENCE_SERVER_MANAGED_FIELDS = frozenset(
    {
        "currentInferenceTaskId",
        "gpkgUrl",
        "inferenceCurrentStep",
        "inferenceJobs",
        "inferenceProgressPct",
        "inferenceStatus",
        "inferenceStatusMessage",
        "inferenceTotalSteps",
        "inferenceUid",
        "predictedDamageLayerUrl",
    }
)


def changed_server_managed_fields(
    payload: Mapping[str, Any],
    protected_fields: Collection[str],
    existing: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return protected fields supplied for create or changed during update."""
    supplied = set(payload).intersection(protected_fields)
    if existing is None:
        return sorted(supplied)
    return sorted(
        field for field in supplied if payload[field] != existing.get(field)
    )


def server_managed_fields_message(fields: Collection[str]) -> str:
    """Build a stable boundary-validation message."""
    return "Server-managed fields cannot be supplied or changed: " + ", ".join(
        sorted(fields)
    )
