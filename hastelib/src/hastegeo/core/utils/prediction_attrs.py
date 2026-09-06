# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Eager, storage-independent columnar attributes for raw predictions."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .logs import Logger
from .predictions import (
    FootprintPredictionMismatchError,
    prediction_layer,
    raw_prediction_class,
    read_predictions,
)

# Public re-exports retain the reference builder's utility/error interfaces.
__all__ = [
    "FootprintPredictionMismatchError",
    "attrs_artifact_name",
    "build_prediction_attrs",
    "prediction_layer",
    "write_prediction_attrs",
]

SCHEMA_VERSION = 1
logger = Logger.get_logger(__name__)


def build_prediction_attrs(
    predictions_path: str,
    footprints_path: str,
    *,
    prediction_revision: str,
    flavor: str | None = None,
    footprint_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build all columns from a strictly validated source-row join.

    Scores retain their precision: rounding a small positive fraction to
    zero would change the default (strictly greater than zero) class.
    ``classes`` describes raw results too; it does not imply analyst edits.
    """
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
    predictions = read_predictions(
        predictions_path, footprints_path, flavor=flavor
    )
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
