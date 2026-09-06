# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Eager, storage-independent attributes for raw and saved predictions."""

from __future__ import annotations

import json
import os
import re
from numbers import Integral
from typing import Any

import fiona

from .logs import Logger
from .predictions import (
    FootprintPredictionMismatchError,
    PredictionRow,
    PredictionSet,
    binary_damage,
    prediction_layer,
    raw_prediction_class,
    read_predictions,
    source_id,
    threshold_prediction_class,
    validate_edit_thresholds,
    validate_prediction_class,
)

# Public re-exports retain the reference builder's utility/error interfaces.
__all__ = [
    "FootprintPredictionMismatchError",
    "attrs_artifact_name",
    "build_prediction_attrs",
    "build_edited_prediction_attrs",
    "prediction_layer",
    "write_prediction_attrs",
    "write_edited_prediction_attrs",
]

SCHEMA_VERSION = 1
logger = Logger.get_logger(__name__)
MODEL_CLASS_FIELD = "model_class"
OVERRIDE_CLASS_FIELD = "override_class"
MODEL_DAMAGED_FIELD = "model_damaged"
EDIT_THRESHOLD_FIELD = "edit_threshold"
EDIT_UNKNOWN_THRESHOLD_FIELD = "edit_unknown_threshold"


def validate_prediction_provenance(
    prediction_revision: str,
    footprint_fingerprint: str | None = None,
) -> None:
    """Validate payload identifiers before creating local artifacts."""
    if (
        not isinstance(prediction_revision, str)
        or not prediction_revision.strip()
    ):
        raise ValueError("prediction_revision must be a nonempty string.")
    if footprint_fingerprint is not None and (
        not isinstance(footprint_fingerprint, str)
        or not footprint_fingerprint.strip()
    ):
        raise ValueError("footprint_fingerprint must be a nonempty string.")


def validate_prediction_version(version: int) -> int:
    if (
        isinstance(version, bool)
        or not isinstance(version, Integral)
        or version < 1
    ):
        raise ValueError(
            "Edited prediction version must be a positive integer."
        )
    return int(version)


def _columnar_payload(
    predictions: PredictionSet,
    prediction_revision: str,
    footprint_fingerprint: str | None,
) -> dict[str, Any]:
    rows = predictions.rows
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "predictionRevision": prediction_revision,
        "flavor": predictions.flavor,
        "n": len(rows),
        "ids": [row.row_index for row in rows],
        "overtureIds": [row.overture_id for row in rows],
        "damage": [row.damage_fraction for row in rows],
        "unknown": [row.unknown_fraction for row in rows],
        "damaged": [row.damaged for row in rows],
        "classes": [raw_prediction_class(row) for row in rows],
    }
    if footprint_fingerprint is not None:
        payload["footprintFingerprint"] = footprint_fingerprint
    return payload


def build_prediction_attrs(
    predictions_path: str,
    footprints_path: str,
    *,
    prediction_revision: str,
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build raw columns with source identity and full score precision.

    Raw ``classes`` does not imply edited provenance. Do not pass a saved
    GPKG here: its rewritten binary calls are no longer the model baseline.
    """
    validate_prediction_provenance(prediction_revision, footprint_fingerprint)
    predictions = read_predictions(
        predictions_path, footprints_path, flavor=flavor
    )
    if predictions.is_edited:
        raise ValueError(
            "Use the edited builder for a saved prediction source."
        )
    return _columnar_payload(
        predictions, prediction_revision, footprint_fingerprint
    )


def write_prediction_attrs(
    predictions_path: str,
    footprints_path: str,
    attrs_path: str,
    *,
    prediction_revision: str,
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Write strict JSON after validation; propagate every write failure."""
    if os.path.realpath(attrs_path) in {
        os.path.realpath(predictions_path),
        os.path.realpath(footprints_path),
    }:
        raise ValueError("The sidecar must not overwrite an input GeoPackage.")
    payload = build_prediction_attrs(
        predictions_path,
        footprints_path,
        prediction_revision=prediction_revision,
        flavor=flavor,
        footprint_fingerprint=footprint_fingerprint,
    )
    with open(attrs_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
    logger.info("Wrote prediction attributes for %d buildings", payload["n"])
    return payload


def attrs_artifact_name(model_id: str) -> str:
    """The reference-compatible raw sidecar basename, including extension."""
    if not isinstance(model_id, str) or not re.fullmatch(
        r"[0-9]{1,8}", model_id
    ):
        raise ValueError("model_id must be a short integer ID string.")
    return f"prediction_attrs_{model_id}.json"


def build_edited_prediction_attrs(
    predictions_path: str,
    footprints_path: str,
    *,
    prediction_revision: str,
    version: int,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Read effective classes, original baseline and pins from a saved GPKG.

    The local edit writer verifies the raw source before writing these
    columns. Revalidate their consistency here; do not derive ``modelClasses``
    from the edited ``damaged`` column, or treat null model scores as zero.
    """
    validate_prediction_provenance(prediction_revision, footprint_fingerprint)
    version = validate_prediction_version(version)
    predictions = read_predictions(
        predictions_path, footprints_path, flavor=flavor
    )
    if not predictions.is_edited:
        raise ValueError("Edited attributes require an edited GeoPackage.")
    threshold, unknown_threshold = validate_edit_thresholds(
        predictions.flavor, threshold, unknown_threshold
    )
    model_classes: list[str] = []
    override_classes: list[str | None] = []
    with fiona.open(predictions_path, layer=predictions.layer_name) as src:
        required = {
            MODEL_CLASS_FIELD,
            OVERRIDE_CLASS_FIELD,
            MODEL_DAMAGED_FIELD,
            EDIT_THRESHOLD_FIELD,
            EDIT_UNKNOWN_THRESHOLD_FIELD,
        }
        if not required.issubset(src.schema["properties"]):
            raise ValueError(
                "Edited GeoPackage is missing baseline provenance."
            )
        for index, feature in enumerate(src):
            if index >= len(predictions.rows):
                raise FootprintPredictionMismatchError(
                    "Edited row count changed."
                )
            row = predictions.rows[index]
            props = feature["properties"]
            if (
                props["id"] != row.row_index
                or source_id(props["overture_id"]) != row.overture_id
            ):
                raise FootprintPredictionMismatchError(
                    "Edited row identity changed."
                )
            model_row = PredictionRow(
                row_index=row.row_index,
                overture_id=row.overture_id,
                damage_fraction=row.damage_fraction,
                damaged=binary_damage(props[MODEL_DAMAGED_FIELD]),
                unknown_fraction=row.unknown_fraction,
            )
            model_class = validate_prediction_class(props[MODEL_CLASS_FIELD])
            if model_class != raw_prediction_class(model_row):
                raise ValueError(
                    "Stored model class disagrees with its baseline."
                )
            override = props[OVERRIDE_CLASS_FIELD]
            if override is not None:
                override = validate_prediction_class(override)
            if (
                props[EDIT_THRESHOLD_FIELD] != threshold
                or props[EDIT_UNKNOWN_THRESHOLD_FIELD] != unknown_threshold
            ):
                raise ValueError(
                    "Stored edit thresholds disagree with the save."
                )
            expected_class = (
                override
                if override is not None
                else threshold_prediction_class(
                    model_row,
                    flavor=predictions.flavor,
                    threshold=threshold,
                    unknown_threshold=unknown_threshold,
                )
            )
            if row.edited_class != expected_class or row.damaged != int(
                expected_class == "Damaged"
            ):
                raise ValueError(
                    "Stored effective class disagrees with its edit."
                )
            model_classes.append(model_class)
            override_classes.append(override)
    if len(model_classes) != len(predictions.rows):
        raise FootprintPredictionMismatchError("Edited row count changed.")
    payload = _columnar_payload(
        predictions, prediction_revision, footprint_fingerprint
    )
    payload.update(
        predictionVersion=version,
        isEdited=True,
        threshold=threshold,
        unknownThreshold=unknown_threshold,
        classes=[row.edited_class for row in predictions.rows],
        modelClasses=model_classes,
        overrideClasses=override_classes,
    )
    return payload


def write_edited_prediction_attrs(
    predictions_path: str,
    footprints_path: str,
    attrs_path: str,
    *,
    prediction_revision: str,
    version: int,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create a new saved-version sidecar; never replace an existing file."""
    if os.path.realpath(attrs_path) in {
        os.path.realpath(predictions_path),
        os.path.realpath(footprints_path),
    }:
        raise ValueError("The sidecar must not overwrite an input GeoPackage.")
    if os.path.lexists(attrs_path):
        raise FileExistsError(attrs_path)
    payload = build_edited_prediction_attrs(
        predictions_path,
        footprints_path,
        prediction_revision=prediction_revision,
        version=version,
        threshold=threshold,
        unknown_threshold=unknown_threshold,
        flavor=flavor,
        footprint_fingerprint=footprint_fingerprint,
    )
    created = False
    try:
        with open(attrs_path, "x", encoding="utf-8") as handle:
            created = True
            json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
    except Exception:
        if created:
            os.unlink(attrs_path)
        raise
    return payload
