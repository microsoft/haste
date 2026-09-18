# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Apply a complete assignment snapshot to an immutable raw GPKG locally.

No storage, model documents, version allocation, queues or HTTP objects live
here. The caller verifies generation identity and publishes the resulting
pair with create-only storage writes. ``classes`` in a raw sidecar is not an
edit marker: only the dedicated GPKG edit columns identify an edited source.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from numbers import Integral
from typing import Any

import fiona

from .logs import Logger
from .prediction_attrs import (
    EDIT_THRESHOLD_FIELD,
    EDIT_UNKNOWN_THRESHOLD_FIELD,
    MODEL_CLASS_FIELD,
    MODEL_DAMAGED_FIELD,
    OVERRIDE_CLASS_FIELD,
    validate_prediction_provenance,
    validate_prediction_version,
    write_edited_prediction_attrs,
)
from .predictions import (
    DAMAGED,
    EDITED_CLASS_FIELD,
    PREDICTION_CLASSES,
    FootprintPredictionMismatchError,
    PredictionRow,
    normalize_fraction,
    raw_prediction_class,
    read_predictions,
    source_id,
    threshold_prediction_class,
    validate_edit_thresholds,
    validate_prediction_class,
)

logger = Logger.get_logger(__name__)


@dataclass(frozen=True)
class PredictionOverride:
    row_index: int
    edited_class: str


@dataclass
class EditSummary:
    total_rows: int = 0
    counts: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(PREDICTION_CLASSES, 0)
    )
    overrides_applied: int = 0
    changed_from_model: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "totalRows": self.total_rows,
            "counts": dict(self.counts),
            "overridesApplied": self.overrides_applied,
            "changedFromModel": self.changed_from_model,
        }


@dataclass
class EditedPredictionArtifacts:
    gpkg_path: str
    attrs_path: str
    count: int
    payload: dict[str, Any]
    summary: EditSummary


def derive_prediction_class(
    row: PredictionRow,
    *,
    flavor: str,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
    override: str | None = None,
) -> str:
    """Explicit calls beat Unknown/null scores; otherwise compare strictly >."""
    validate_edit_thresholds(flavor, threshold, unknown_threshold)
    if override is not None:
        return validate_prediction_class(override)
    return threshold_prediction_class(
        row,
        flavor=flavor,
        threshold=threshold,
        unknown_threshold=unknown_threshold,
    )


def _validate_paths(
    raw_path: str, footprints_path: str, gpkg_path: str, attrs_path: str
) -> None:
    paths = (raw_path, footprints_path, gpkg_path, attrs_path)
    if len({os.path.realpath(path) for path in paths}) != len(paths):
        raise ValueError(
            "Raw, footprints, GeoPackage and sidecar paths must differ."
        )
    for index, path in enumerate(paths):
        for other in paths[:index]:
            if (
                os.path.exists(path)
                and os.path.exists(other)
                and os.path.samefile(path, other)
            ):
                raise ValueError("Prediction artifact paths must not alias.")
    for path in (gpkg_path, attrs_path):
        if os.path.lexists(path):
            raise FileExistsError(path)
    for path in (raw_path, footprints_path):
        if not os.path.isfile(path):
            raise FileNotFoundError(path)


def _override_snapshot(
    overrides: Sequence[PredictionOverride], count: int
) -> dict[int, str]:
    if not isinstance(overrides, Sequence) or isinstance(
        overrides, (str, bytes)
    ):
        raise ValueError(
            "overrides must be a sequence of PredictionOverride objects."
        )
    result: dict[int, str] = {}
    for override in overrides:
        if not isinstance(override, PredictionOverride):
            raise ValueError("Each override must be a PredictionOverride.")
        index = override.row_index
        if (
            isinstance(index, bool)
            or not isinstance(index, Integral)
            or not 0 <= index < count
        ):
            raise ValueError("Override row_index must be an in-range integer.")
        if index in result:
            raise ValueError(f"Duplicate override row_index: {index}.")
        result[int(index)] = validate_prediction_class(override.edited_class)
    return result


def apply_prediction_edits(
    raw_gpkg_path: str,
    footprints_path: str,
    gpkg_path: str,
    attrs_path: str,
    *,
    prediction_revision: str,
    version: int,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
    overrides: Sequence[PredictionOverride] = (),
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> EditedPredictionArtifacts:
    """Create a saved GPKG/sidecar from raw scores and complete explicit pins.

    Missing assignments mean threshold-derived, not "retain some previous
    file's edit". Callers resaving a version must carry its entire assignment
    snapshot forward. Model-class pins are never minimized away.
    """
    _validate_paths(raw_gpkg_path, footprints_path, gpkg_path, attrs_path)
    validate_prediction_provenance(prediction_revision, footprint_fingerprint)
    version = validate_prediction_version(version)
    predictions = read_predictions(
        raw_gpkg_path, footprints_path, flavor=flavor
    )
    if predictions.is_edited:
        raise ValueError(
            "The edit baseline must be the raw prediction GeoPackage."
        )
    threshold, unknown_threshold = validate_edit_thresholds(
        predictions.flavor, threshold, unknown_threshold
    )
    assignments = _override_snapshot(overrides, len(predictions))
    model_classes = [raw_prediction_class(row) for row in predictions.rows]
    classes = [
        derive_prediction_class(
            row,
            flavor=predictions.flavor,
            threshold=threshold,
            unknown_threshold=unknown_threshold,
            override=assignments.get(row.row_index),
        )
        for row in predictions.rows
    ]
    summary = EditSummary(
        total_rows=len(predictions),
        overrides_applied=len(assignments),
        changed_from_model=sum(a != b for a, b in zip(classes, model_classes)),
        counts={name: classes.count(name) for name in PREDICTION_CLASSES},
    )
    created = False
    try:
        with fiona.open(raw_gpkg_path, layer=predictions.layer_name) as src:
            properties = dict(src.schema["properties"])
            edit_fields = {
                EDITED_CLASS_FIELD: "str",
                MODEL_CLASS_FIELD: "str",
                OVERRIDE_CLASS_FIELD: "str",
                MODEL_DAMAGED_FIELD: "int",
                EDIT_THRESHOLD_FIELD: "float",
                EDIT_UNKNOWN_THRESHOLD_FIELD: "float",
            }
            if set(edit_fields).intersection(properties):
                raise ValueError(
                    "The raw baseline contains reserved edit columns."
                )
            properties.update(edit_fields)
            written = 0
            with fiona.open(
                gpkg_path,
                "w",
                driver="GPKG",
                layer=predictions.layer_name,
                crs_wkt=src.crs_wkt,
                schema={
                    "geometry": src.schema["geometry"],
                    "properties": properties,
                },
            ) as dst:
                created = True
                for index, feature in enumerate(src):
                    if index >= len(predictions):
                        raise FootprintPredictionMismatchError(
                            "Raw row count changed."
                        )
                    row = predictions.rows[index]
                    props = dict(feature["properties"])
                    if (
                        props["id"] != row.row_index
                        or source_id(props["overture_id"]) != row.overture_id
                        or props["damaged"] != row.damaged
                        or normalize_fraction(props["damage_pct_0m"])
                        != row.damage_fraction
                        or normalize_fraction(props["unknown_pct"])
                        != row.unknown_fraction
                    ):
                        raise FootprintPredictionMismatchError(
                            "Raw prediction changed."
                        )
                    props.update(
                        damaged=int(classes[index] == DAMAGED),
                        edited_class=classes[index],
                        model_class=model_classes[index],
                        override_class=assignments.get(index),
                        model_damaged=row.damaged,
                        edit_threshold=threshold,
                        edit_unknown_threshold=unknown_threshold,
                    )
                    dst.write(
                        {"geometry": feature["geometry"], "properties": props}
                    )
                    written += 1
            if written != len(predictions):
                raise FootprintPredictionMismatchError(
                    "Raw row count changed."
                )
        payload = write_edited_prediction_attrs(
            gpkg_path,
            footprints_path,
            attrs_path,
            prediction_revision=prediction_revision,
            version=version,
            threshold=threshold,
            unknown_threshold=unknown_threshold,
            flavor=predictions.flavor,
            footprint_fingerprint=footprint_fingerprint,
        )
    except Exception:
        if created and os.path.exists(gpkg_path):
            fiona.remove(gpkg_path, driver="GPKG")
        raise
    logger.info(
        "Created edited predictions: %d rows, %d assignments, %d changed classes",
        summary.total_rows,
        summary.overrides_applied,
        summary.changed_from_model,
    )
    return EditedPredictionArtifacts(
        gpkg_path=gpkg_path,
        attrs_path=attrs_path,
        count=summary.total_rows,
        payload=payload,
        summary=summary,
    )
