# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Create interactive prediction artifacts locally, without publication.

The caller owns temporary directories, upload, generation concurrency and
metadata. Empty-list clear requests must be handled by that caller before
invoking this full-replacement writer.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
from typing import Any

import fiona
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from ..utils.prediction_attrs import write_prediction_attrs
from ..utils.predictions import (
    EMBEDDING_FLAVOR,
    FootprintPredictionMismatchError,
    binary_damage,
    normalize_fraction,
    read_footprint_ids,
    source_id,
)


@dataclass
class BuildingPredictionArtifacts:
    gpkg_path: str
    attrs_path: str
    count: int
    payload: dict[str, Any]


def write_building_predictions(
    footprints_path: str,
    predictions: Sequence[Mapping[str, Any]],
    gpkg_path: str,
    attrs_path: str,
    *,
    prediction_revision: str,
    footprint_fingerprint: str | None = None,
) -> BuildingPredictionArtifacts:
    """Validate a complete replacement and write matching GPKG and JSON.

    Requests may be out of order, but every source row must appear exactly
    once. ``overtureId`` is optional in the request; when provided it must
    agree with the immutable footprint source. It is always saved to GPKG.
    """
    paths = {
        os.path.realpath(footprints_path),
        os.path.realpath(gpkg_path),
        os.path.realpath(attrs_path),
    }
    if len(paths) != 3:
        raise ValueError("Input, GeoPackage and sidecar paths must differ.")
    ids = read_footprint_ids(footprints_path)
    count = len(ids)
    if not isinstance(predictions, Sequence) or isinstance(
        predictions, (str, bytes)
    ):
        raise ValueError("predictions must be a sequence of prediction rows.")
    ordered: dict[int, tuple[int, float]] = {}
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise ValueError("Each prediction must be an object.")
        row_id = prediction.get("id")
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, Integral)
            or not 0 <= row_id < count
        ):
            raise ValueError("Prediction id must be an in-range integer.")
        if row_id in ordered:
            raise ValueError(f"Duplicate prediction id: {row_id}.")
        if (
            "overtureId" in prediction
            and source_id(prediction["overtureId"]) != ids[row_id]
        ):
            raise FootprintPredictionMismatchError(
                f"Prediction {row_id} has the wrong Overture ID."
            )
        damaged = binary_damage(prediction.get("damaged"))
        unknown = normalize_fraction(prediction.get("unknown", 0.0))
        if unknown is None:
            raise ValueError("unknown must be a finite fraction.")
        ordered[int(row_id)] = (damaged, unknown)
    if len(ordered) != count:
        raise ValueError(
            "Predictions must cover every footprint exactly once; "
            "handle an empty-list clear before invoking this writer."
        )

    with fiona.open(footprints_path) as src:
        schema = {
            "geometry": src.schema["geometry"],
            "properties": {
                "id": "int",
                "overture_id": "str",
                "damaged": "int",
                "damage_pct_0m": "float",
                "unknown_pct": "float",
                "area": "float",
            },
        }
        to_equal_area = Transformer.from_crs(
            src.crs, "EPSG:6933", always_xy=True
        )
        with fiona.open(
            gpkg_path,
            "w",
            driver="GPKG",
            layer="predictions",
            crs_wkt=src.crs_wkt,
            schema=schema,
        ) as dst:
            for index, feature in enumerate(src):
                geometry = feature["geometry"]
                area = (
                    transform(to_equal_area.transform, shape(geometry)).area
                    if geometry is not None
                    else None
                )
                if area is not None and not math.isfinite(area):
                    area = None
                damaged, unknown = ordered[index]
                dst.write(
                    {
                        "geometry": geometry,
                        "properties": {
                            "id": index,
                            "overture_id": ids[index],
                            "damaged": damaged,
                            "damage_pct_0m": float(damaged),
                            "unknown_pct": unknown,
                            "area": area,
                        },
                    }
                )
    payload = write_prediction_attrs(
        gpkg_path,
        footprints_path,
        attrs_path,
        prediction_revision=prediction_revision,
        flavor=EMBEDDING_FLAVOR,
        footprint_fingerprint=footprint_fingerprint,
    )
    return BuildingPredictionArtifacts(
        gpkg_path=gpkg_path,
        attrs_path=attrs_path,
        count=count,
        payload=payload,
    )
