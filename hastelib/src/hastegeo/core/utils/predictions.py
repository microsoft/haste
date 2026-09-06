# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Read building predictions without losing their source row identity.

The cached footprint order is the layer's tile-ID contract. A prediction's
``id`` is that zero-based row index, not its GeoPackage FID. New producers
also carry ``overture_id`` so equal-sized, misordered inputs cannot silently
join. This module contains no storage, edit application or queue logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Any

import fiona

from .gdal_security import harden_gdal
from .logs import Logger

harden_gdal()
logger = Logger.get_logger(__name__)

INFERENCE_FLAVOR = "inference"
EMBEDDING_FLAVOR = "embedding"
DEFAULT_DAMAGE_THRESHOLD = 0.0
DEFAULT_UNKNOWN_THRESHOLD = 0.0
DAMAGED = "Damaged"
NOT_DAMAGED = "NotDamaged"
UNKNOWN = "Unknown"
PREDICTION_CLASSES = (DAMAGED, NOT_DAMAGED, UNKNOWN)

DAMAGE_FIELD = "damage_pct_0m"
UNKNOWN_FIELD = "unknown_pct"
DAMAGED_FIELD = "damaged"
FOOTPRINT_ID_FIELD = "id"
OVERTURE_ID_FIELD = "overture_id"
EMBEDDING_LAYER_NAME = "predictions"
EDITED_CLASS_FIELD = "edited_class"


class FootprintPredictionMismatchError(ValueError):
    """Predictions do not match the immutable layer's source row IDs."""


@dataclass
class PredictionRow:
    row_index: int
    overture_id: str | None
    damage_fraction: float | None
    damaged: int
    unknown_fraction: float | None
    edited_class: str | None = None


@dataclass
class PredictionSet:
    rows: list[PredictionRow] = field(default_factory=list)
    flavor: str = INFERENCE_FLAVOR
    supports_threshold: bool = True
    layer_name: str | None = None
    crs: Any = None
    is_edited: bool = False

    def __len__(self) -> int:
        return len(self.rows)


def source_id(value: Any) -> str:
    """Normalize a source identifier, rejecting missing or ambiguous IDs."""
    if isinstance(value, bool) or not isinstance(value, (str, Integral)):
        raise FootprintPredictionMismatchError(
            "Footprints and predictions must carry non-null source IDs."
        )
    result = str(value)
    if not result or result != result.strip():
        raise FootprintPredictionMismatchError(
            "Source IDs must be nonempty and have no surrounding whitespace."
        )
    return result


def normalize_fraction(value: Any) -> float | None:
    """Keep unavailable scores unknown; reject finite out-of-range scores."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            "Prediction scores must be numeric fractions or null."
        )
    result = float(value)
    if not math.isfinite(result):
        return None
    if not 0.0 <= result <= 1.0:
        raise ValueError("Prediction scores must be between zero and one.")
    return result


def binary_damage(value: Any) -> int:
    """Validate the producer's binary call without truncation/coercion."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Integral)
        or value not in (0, 1)
    ):
        raise ValueError("damaged must be the integer zero or one.")
    return int(value)


def validate_prediction_class(value: Any) -> str:
    """Validate a categorical decision without guessing a missing class."""
    if not isinstance(value, str) or value not in PREDICTION_CLASSES:
        raise ValueError(
            "Prediction class must be Damaged, NotDamaged or Unknown."
        )
    return value


def validate_threshold(value: Any, name: str = "threshold") -> float:
    """Thresholds, unlike model scores, may never be null or non-finite."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite fraction between 0 and 1.")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be a finite fraction between 0 and 1.")
    return result


def validate_edit_thresholds(
    flavor: str, threshold: float, unknown_threshold: float
) -> tuple[float, float]:
    """Validate editor controls against producer identity, not score values."""
    if flavor not in (INFERENCE_FLAVOR, EMBEDDING_FLAVOR):
        raise ValueError("Unknown prediction flavor.")
    threshold = validate_threshold(threshold)
    unknown_threshold = validate_threshold(
        unknown_threshold, "unknown_threshold"
    )
    if flavor == EMBEDDING_FLAVOR and (threshold or unknown_threshold):
        raise ValueError(
            "Embedding predictions do not support threshold edits."
        )
    return threshold, unknown_threshold


def threshold_prediction_class(
    row: PredictionRow,
    *,
    flavor: str,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
) -> str:
    """Classify a raw row at validated editor thresholds (strictly >)."""
    threshold, unknown_threshold = validate_edit_thresholds(
        flavor, threshold, unknown_threshold
    )
    if row.damage_fraction is None or row.unknown_fraction is None:
        return UNKNOWN
    if row.unknown_fraction > unknown_threshold:
        return UNKNOWN
    if flavor == EMBEDDING_FLAVOR:
        return DAMAGED if row.damaged else NOT_DAMAGED
    return DAMAGED if row.damage_fraction > threshold else NOT_DAMAGED


def prediction_layer(predictions_path: str) -> str:
    layers = fiona.listlayers(predictions_path)
    if not layers:
        raise ValueError("Prediction GeoPackage has no layers.")
    return (
        EMBEDDING_LAYER_NAME if EMBEDDING_LAYER_NAME in layers else layers[0]
    )


def read_footprint_ids(footprints_path: str) -> list[str]:
    """Read unique source IDs in the exact order used by layer tiles."""
    with fiona.open(footprints_path) as src:
        if not src.crs:
            raise ValueError("Footprint GeoPackage must declare a CRS.")
        if FOOTPRINT_ID_FIELD not in src.schema["properties"]:
            raise FootprintPredictionMismatchError(
                "Footprint GeoPackage is missing its source id column."
            )
        ids = [
            source_id(feature["properties"][FOOTPRINT_ID_FIELD])
            for feature in src
        ]
    if len(set(ids)) != len(ids):
        raise FootprintPredictionMismatchError(
            "Footprint GeoPackage contains duplicate source IDs."
        )
    return ids


def raw_prediction_class(row: PredictionRow) -> str:
    """Classify raw results at the zero defaults, before any rounding."""
    if (
        row.damage_fraction is None
        or row.unknown_fraction is None
        or row.unknown_fraction > DEFAULT_UNKNOWN_THRESHOLD
    ):
        return UNKNOWN
    return DAMAGED if row.damaged else NOT_DAMAGED


def read_predictions(
    gpkg_path: str,
    footprints_path: str | None = None,
    *,
    flavor: str | None = None,
) -> PredictionSet:
    """Read prediction scores and, when supplied, verify their source join.

    Flavor is explicit or schema-based: ``predictions`` plus ``area`` marks
    an embedding output. Binary-valued inference fractions remain inference.
    NULL/non-finite scores remain unavailable, never artificially undamaged.
    """
    if flavor not in (None, INFERENCE_FLAVOR, EMBEDDING_FLAVOR):
        raise ValueError("Unknown prediction flavor.")
    layer_name = prediction_layer(gpkg_path)
    footprint_ids = (
        read_footprint_ids(footprints_path)
        if footprints_path is not None
        else None
    )
    rows: list[PredictionRow] = []
    required = {
        "id",
        OVERTURE_ID_FIELD,
        DAMAGE_FIELD,
        UNKNOWN_FIELD,
        DAMAGED_FIELD,
    }
    with fiona.open(gpkg_path, layer=layer_name) as src:
        if not src.crs:
            raise ValueError("Prediction GeoPackage must declare a CRS.")
        crs = src.crs
        fields = set(src.schema["properties"])
        missing = required - fields
        if missing:
            raise ValueError(
                f"Prediction GeoPackage is missing columns: {sorted(missing)}"
            )
        is_edited = EDITED_CLASS_FIELD in fields
        schema_flavor = (
            EMBEDDING_FLAVOR
            if layer_name == EMBEDDING_LAYER_NAME and "area" in fields
            else INFERENCE_FLAVOR
        )
        if flavor is not None and flavor != schema_flavor:
            raise ValueError("Prediction flavor does not match its schema.")
        flavor = flavor or schema_flavor
        for position, feature in enumerate(src):
            props = feature["properties"]
            row_id = props["id"]
            if (
                isinstance(row_id, bool)
                or not isinstance(row_id, Integral)
                or row_id != position
            ):
                raise FootprintPredictionMismatchError(
                    "Prediction IDs must be contiguous source row IDs in "
                    f"order; expected {position}, got {row_id!r}."
                )
            rows.append(
                PredictionRow(
                    row_index=int(row_id),
                    overture_id=source_id(props[OVERTURE_ID_FIELD]),
                    damage_fraction=normalize_fraction(props[DAMAGE_FIELD]),
                    damaged=binary_damage(props[DAMAGED_FIELD]),
                    unknown_fraction=normalize_fraction(props[UNKNOWN_FIELD]),
                    edited_class=(
                        validate_prediction_class(props[EDITED_CLASS_FIELD])
                        if is_edited
                        else None
                    ),
                )
            )

    prediction_ids = [row.overture_id for row in rows]
    if len(set(prediction_ids)) != len(prediction_ids):
        raise FootprintPredictionMismatchError(
            "Prediction GeoPackage contains duplicate Overture IDs."
        )
    if footprint_ids is not None and prediction_ids != footprint_ids:
        raise FootprintPredictionMismatchError(
            "Prediction/footprint count or source ID mismatch: "
            f"{len(rows)} predictions versus {len(footprint_ids)} footprints. "
            "Both files must match row for row."
        )
    logger.info("Read %d predictions (flavor=%s)", len(rows), flavor)
    return PredictionSet(
        rows=rows,
        flavor=flavor,
        supports_threshold=flavor == INFERENCE_FLAVOR and not is_edited,
        layer_name=layer_name,
        crs=crs,
        is_edited=is_edited,
    )


def _read_legacy_raw_report_predictions(
    gpkg_path: str,
    footprints_path: str,
    layer_name: str,
    *,
    flavor: str | None,
) -> PredictionSet:
    """Resolve legacy positional identity in memory for reports only.

    This is deliberately separate from ``read_predictions``: producers,
    sidecar builders and edit application must still require overture_id.
    Never use positional compatibility for a saved/edited source.
    """
    footprint_ids = read_footprint_ids(footprints_path)
    rows: list[PredictionRow] = []
    with fiona.open(gpkg_path, layer=layer_name) as src:
        if not src.crs:
            raise ValueError("Prediction GeoPackage must declare a CRS.")
        crs = src.crs
        fields = set(src.schema["properties"])
        if EDITED_CLASS_FIELD in fields:
            raise ValueError("Positional report compatibility is raw-only.")
        required = {"id", DAMAGE_FIELD, UNKNOWN_FIELD, DAMAGED_FIELD}
        if not required.issubset(fields):
            raise ValueError(
                "Prediction GeoPackage is missing report columns."
            )
        schema_flavor = (
            EMBEDDING_FLAVOR
            if layer_name == EMBEDDING_LAYER_NAME and "area" in fields
            else INFERENCE_FLAVOR
        )
        if flavor is not None and flavor != schema_flavor:
            raise ValueError("Prediction flavor does not match its schema.")
        for position, feature in enumerate(src):
            props = feature["properties"]
            row_id = props["id"]
            if (
                isinstance(row_id, bool)
                or not isinstance(row_id, Integral)
                or row_id != position
                or position >= len(footprint_ids)
            ):
                raise FootprintPredictionMismatchError(
                    "Legacy prediction IDs must match source row order."
                )
            oid = footprint_ids[position]
            if (
                OVERTURE_ID_FIELD in fields
                and source_id(props[OVERTURE_ID_FIELD]) != oid
            ):
                raise FootprintPredictionMismatchError(
                    "Legacy prediction Overture ID does not match its source."
                )
            rows.append(
                PredictionRow(
                    row_index=int(row_id),
                    overture_id=oid,
                    damage_fraction=normalize_fraction(props[DAMAGE_FIELD]),
                    damaged=binary_damage(props[DAMAGED_FIELD]),
                    unknown_fraction=normalize_fraction(props[UNKNOWN_FIELD]),
                )
            )
    if len(rows) != len(footprint_ids):
        raise FootprintPredictionMismatchError(
            "Legacy prediction/footprint row counts must match."
        )
    return PredictionSet(
        rows=rows,
        flavor=schema_flavor,
        supports_threshold=schema_flavor == INFERENCE_FLAVOR,
        layer_name=layer_name,
        crs=crs,
    )


def read_effective_prediction_classes(
    gpkg_path: str,
    footprints_path: str,
    *,
    flavor: str | None = None,
    threshold: float = 0.0,
    unknown_threshold: float = 0.0,
    is_edited: bool | None = None,
) -> dict[str, str]:
    """Return Overture ID -> effective class for a selected report source.

    Saved categorical classes bypass report/editor thresholds, including
    when the preserved model score is null. Source selection is the caller's
    responsibility. Auto-detection uses the dedicated GPKG edit column, never
    the ``classes`` array (which raw sidecars also carry).

    Legacy raw report files may omit overture_id. Resolve that missing
    column positionally only here, after enforcing stored IDs/count/order;
    never write the inferred column back or weaken producer/edit validation.
    """
    if is_edited is not None and not isinstance(is_edited, bool):
        raise ValueError("is_edited must be a boolean or None.")
    layer = prediction_layer(gpkg_path)
    with fiona.open(gpkg_path, layer=layer) as src:
        fields = src.schema["properties"]
        legacy_raw = (
            is_edited is not True
            and OVERTURE_ID_FIELD not in fields
            and EDITED_CLASS_FIELD not in fields
        )
    if legacy_raw:
        predictions = _read_legacy_raw_report_predictions(
            gpkg_path, footprints_path, layer, flavor=flavor
        )
    else:
        predictions = read_predictions(
            gpkg_path, footprints_path, flavor=flavor
        )
    if is_edited is not None and (
        not isinstance(is_edited, bool) or is_edited != predictions.is_edited
    ):
        raise ValueError(
            "Selected prediction source disagrees with its schema."
        )
    if predictions.is_edited:
        return {row.overture_id: row.edited_class for row in predictions.rows}
    validate_edit_thresholds(predictions.flavor, threshold, unknown_threshold)
    return {
        row.overture_id: threshold_prediction_class(
            row,
            flavor=predictions.flavor,
            threshold=threshold,
            unknown_threshold=unknown_threshold,
        )
        for row in predictions.rows
    }
