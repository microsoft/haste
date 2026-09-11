# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Validation report orchestration over a request-local prediction source."""

import asyncio
import os
from typing import Any

from ..models.prediction_edits import PredictionSelectionRequest
from ..utils.predictions import read_effective_prediction_classes
from .assessment import AssessmentReportProcessor
from .prediction_results import PredictionResultsProcessor
from .prediction_sources import resolve_prediction_source


def validation_metrics(
    labels: dict[str, Any], predictions: dict[str, str]
) -> dict[str, Any]:
    """Retain the existing binary report, excluding Unknown on either side."""
    classes = ("Damaged", "NotDamaged")
    label_counts = {"Damaged": 0, "NotDamaged": 0, "Unknown": 0}
    pairs = []
    excluded_unknown = 0
    for building_id, value in labels.items():
        actual = value.get("label", "Unknown")
        label_counts[actual] = label_counts.get(actual, 0) + 1
        predicted = predictions.get(building_id)
        if actual in classes and predicted == "Unknown":
            excluded_unknown += 1
        if actual in classes and predicted in classes:
            pairs.append((actual, predicted))
    report: dict[str, Any] = {
        "matched": len(pairs),
        "totalValidationLabels": len(labels),
        "labelCounts": label_counts,
        "unknownPredictions": sum(
            value == "Unknown" for value in predictions.values()
        ),
        "excludedUnknownPredictions": excluded_unknown,
    }
    if not pairs:
        return {
            **report,
            "error": "No validation labels could be matched to known prediction classes.",
        }
    matrix = [
        [
            sum(actual == a and predicted == p for actual, predicted in pairs)
            for p in classes
        ]
        for a in classes
    ]

    def divide(numerator: int | float, denominator: int | float) -> float:
        return numerator / denominator if denominator else 0.0

    per_class = {}
    for index, label in enumerate(classes):
        tp = matrix[index][index]
        precision = divide(tp, sum(row[index] for row in matrix))
        recall = divide(tp, sum(matrix[index]))
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(divide(2 * precision * recall, precision + recall), 4),
        }
    return {
        **report,
        "accuracy": round(
            sum(matrix[index][index] for index in range(2)) / len(pairs), 4
        ),
        "confusionMatrix": {"labels": list(classes), "matrix": matrix},
        "perClass": per_class,
        "macroF1": round(
            sum(value["f1"] for value in per_class.values()) / 2, 4
        ),
    }


class ValidationReportProcessor(AssessmentReportProcessor):
    async def generate_validation(
        self, request: PredictionSelectionRequest
    ) -> dict[str, Any]:
        model, layer = await asyncio.to_thread(
            PredictionResultsProcessor(
                self.config, self.processor_factory
            ).context,
            request,
        )
        source = resolve_prediction_source(
            model,
            request.version,
            default="latest_current",
            prediction_revision=request.predictionRevision,
        )
        if not source.gpkgUrl or not layer.buildingFootprintsUrl:
            raise FileNotFoundError("Prediction report source is unavailable")
        raw_labels = await asyncio.to_thread(
            self.processor_factory(
                data_type=self.config.get_metadata_types().VALIDATION.value,
                partition_key=request.projectId,
                config=self.config,
            ).load,
            request.imageLayerId,
        )
        labels = (raw_labels or {}).get("labels") or {}
        if not labels:
            raise FileNotFoundError("No validation labels found")
        paths = []
        try:
            footprints = await self._download(
                layer.buildingFootprintsUrl, ".gpkg"
            )
            paths.append(footprints)
            gpkg = await self._download(source.gpkgUrl, ".gpkg")
            paths.append(gpkg)
            # Raw validation retains producer-class/zero-threshold behavior.
            # Saved classes are authoritative and are never rethresholded.
            predictions = await asyncio.to_thread(
                read_effective_prediction_classes,
                gpkg,
                footprints,
                flavor=source.flavor,
                threshold=source.threshold,
                unknown_threshold=source.unknownThreshold,
                is_edited=source.is_edited,
            )
            report = validation_metrics(labels, predictions)
            return {
                **report,
                **source.descriptor(),
                "predictionSource": source.descriptor(),
            }
        finally:
            for path in paths:
                try:
                    os.unlink(path)
                except OSError:
                    pass
