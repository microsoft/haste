# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Eager, storage-independent columnar attributes for raw predictions."""

from __future__ import annotations

import json
import math
import os
import re
from numbers import Integral, Real
from typing import Any

import fiona

from .gdal_security import harden_gdal
from .logs import Logger

harden_gdal()
SCHEMA_VERSION = 1
EMBEDDING_FLAVOR = "embedding"
INFERENCE_FLAVOR = "inference"
logger = Logger.get_logger(__name__)


class FootprintPredictionMismatchError(ValueError):
    """Prediction rows do not match the immutable cached footprints."""


def source_id(value: Any) -> str:
    """Normalize source identifiers without inventing missing IDs."""
    if isinstance(value, bool) or not isinstance(value, (str, Integral)):
        raise FootprintPredictionMismatchError("Source IDs must be non-null.")
    result = str(value)
    if not result or result != result.strip():
        raise FootprintPredictionMismatchError(
            "Source IDs must be nonempty without surrounding whitespace."
        )
    return result


def normalize_fraction(value: Any) -> float | None:
    """NULL/non-finite scores are unscored, not undamaged."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            "Prediction scores must be numeric fractions or null."
        )
    result = float(value)
    if not math.isfinite(result):
        return None
    if not 0 <= result <= 1:
        raise ValueError("Prediction scores must be between zero and one.")
    return result


def binary_damage(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or value not in (0, 1)
    ):
        raise ValueError("damaged must be the integer zero or one.")
    return int(value)


def read_footprint_ids(footprints_path: str) -> list[str]:
    """Read the unique source IDs in the order used by the layer's tiles."""
    with fiona.open(footprints_path) as src:
        if not src.crs:
            raise ValueError("Footprint GeoPackage must declare a CRS.")
        if "id" not in src.schema["properties"]:
            raise FootprintPredictionMismatchError(
                "Missing footprint id column."
            )
        ids = [source_id(row["properties"]["id"]) for row in src]
    if len(set(ids)) != len(ids):
        raise FootprintPredictionMismatchError(
            "Duplicate footprint source IDs."
        )
    return ids


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
    footprint_ids = read_footprint_ids(footprints_path)
    layers = fiona.listlayers(predictions_path)
    if not layers:
        raise ValueError("Prediction GeoPackage has no layers.")
    layer = "predictions" if "predictions" in layers else layers[0]
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "predictionRevision": prediction_revision,
        "n": len(footprint_ids),
        "ids": [],
        "overtureIds": footprint_ids,
        "damage": [],
        "unknown": [],
        "damaged": [],
        "classes": [],
    }
    with fiona.open(predictions_path, layer=layer) as src:
        if not src.crs:
            raise ValueError("Prediction GeoPackage must declare a CRS.")
        fields = set(src.schema["properties"])
        required = {
            "id",
            "overture_id",
            "damage_pct_0m",
            "unknown_pct",
            "damaged",
        }
        if not required.issubset(fields):
            raise ValueError("Prediction GeoPackage is missing columns.")
        schema_flavor = (
            EMBEDDING_FLAVOR
            if layer == "predictions" and "area" in fields
            else INFERENCE_FLAVOR
        )
        if flavor is not None and flavor != schema_flavor:
            raise ValueError("Prediction flavor does not match its schema.")
        payload["flavor"] = schema_flavor
        for index, feature in enumerate(src):
            props = feature["properties"]
            row_id = props["id"]
            if (
                isinstance(row_id, bool)
                or not isinstance(row_id, Integral)
                or row_id != index
                or index >= len(footprint_ids)
                or source_id(props["overture_id"]) != footprint_ids[index]
            ):
                raise FootprintPredictionMismatchError(
                    "Prediction IDs and Overture IDs must match source row order."
                )
            damage = normalize_fraction(props["damage_pct_0m"])
            unknown = normalize_fraction(props["unknown_pct"])
            damaged = binary_damage(props["damaged"])
            if damage is None or unknown is None or unknown > 0:
                classification = "Unknown"
            else:
                classification = "Damaged" if damaged else "NotDamaged"
            payload["ids"].append(int(row_id))
            payload["damage"].append(damage)
            payload["unknown"].append(unknown)
            payload["damaged"].append(damaged)
            payload["classes"].append(classification)
    if len(payload["ids"]) != len(footprint_ids):
        raise FootprintPredictionMismatchError(
            "Prediction and footprint row counts must match."
        )
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
