# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Read raw building predictions without losing their source row identity.

The cached footprint order is the layer's tile-ID contract. A prediction's
``id`` is that zero-based row index, not its GeoPackage FID. New producers
also carry ``overture_id`` so equal-sized, misordered inputs cannot silently
join. This module deliberately contains no storage, editing or queue logic.
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

DAMAGE_FIELD = "damage_pct_0m"
UNKNOWN_FIELD = "unknown_pct"
DAMAGED_FIELD = "damaged"
FOOTPRINT_ID_FIELD = "id"
OVERTURE_ID_FIELD = "overture_id"
EMBEDDING_LAYER_NAME = "predictions"


class FootprintPredictionMismatchError(ValueError):
    """Predictions do not match the immutable layer's source row IDs."""


@dataclass
class PredictionRow:
    row_index: int
    overture_id: str | None
    damage_fraction: float | None
    damaged: int
    unknown_fraction: float | None


@dataclass
class PredictionSet:
    rows: list[PredictionRow] = field(default_factory=list)
    flavor: str = INFERENCE_FLAVOR
    supports_threshold: bool = True
    layer_name: str | None = None
    crs: Any = None

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
    """Read raw predictions and, when supplied, verify their source join.

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
        supports_threshold=flavor == INFERENCE_FLAVOR,
        layer_name=layer_name,
        crs=crs,
    )
