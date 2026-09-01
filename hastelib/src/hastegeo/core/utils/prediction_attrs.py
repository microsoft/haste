# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Builder for the columnar prediction attribute sidecar.

The map clients (prediction editor and results viewer) render EVERY
predicted building of an image layer from two artifacts: geometry-only
footprint PMTiles, shared by every model on the layer, and this
*sidecar* — a compact columnar JSON payload of the per-building damage
values, indexed by the same integer row id that is baked into the tiles.

The builder used to live in
``hastegeo.workflows.prepare_prediction_tiles``, next to the tippecanoe
helpers. That made it unreachable from the Azure Functions app, which
has no tippecanoe and must not import a training-image workflow module
— yet the app is exactly where a sidecar has to be written when an
analyst saves an edited version of a model's predictions. It therefore
lives here, and the workflow imports it.

Two shapes come out of this module:

* :func:`build_prediction_attrs` — the sidecar of a *raw* prediction
  GeoPackage: ``{"n", "ids", "overtureIds", "damage", "unknown",
  "damaged"}``.
* :func:`build_edited_prediction_attrs` — the same payload plus a
  ``"classes"`` column, for a GeoPackage written by
  ``hastegeo.core.processors.prediction_edits.apply_edits``. That file
  carries the analyst's final call per row in ``edited_class``, which
  the numeric columns alone cannot express (a building overridden to
  ``Unknown`` still has whatever unknown fraction the model predicted).

CRITICAL — row-order invariant:
    Predictions join to the layer's footprints GeoPackage **by row
    index**, so every array here is ordered by that index and a
    footprint/prediction count mismatch is a hard error rather than a
    silent misalignment.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import fiona

from ..config import ArtifactTypes
from .gdal_security import harden_gdal
from .predictions import PredictionSet, read_predictions

# Harden GDAL/OGR drivers before any fiona read of a user-supplied vector
# file (GDAL CVE compensating control — docs/known-vulnerabilities.md
# Root Cause C).
harden_gdal()

logger = logging.getLogger(__name__)

# Damage/unknown values are fractions in [0, 1]; six decimals is well
# below any threshold a user can set and keeps the payload compact.
VALUE_PRECISION = 6

# Column ``apply_edits`` writes the analyst's final class to. Kept as a
# literal so this module does not import the processors package (which
# pulls in the artifact-storage stack).
EDITED_CLASS_FIELD = "edited_class"

#: Extra column carried by an edited version's sidecar.
CLASSES_KEY = "classes"


class FootprintPredictionMismatchError(ValueError):
    """Raised when predictions and footprints do not line up row for row."""


def count_features(path: str, layer: Optional[str] = None) -> int:
    """Count features in a vector file without loading its geometry."""
    if layer is None:
        layers = fiona.listlayers(path)
        if not layers:
            raise ValueError(f"Vector file has no layers: {path}")
        layer = layers[0]
    with fiona.open(path, layer=layer) as src:
        return len(src)


def prediction_layer(predictions_path: str) -> str:
    """Return the layer a prediction GeoPackage stores its rows in."""
    layers = fiona.listlayers(predictions_path)
    if not layers:
        raise ValueError(
            f"Prediction GeoPackage has no layers: {predictions_path}"
        )
    # The embedding flavor writes a named "predictions" layer; the
    # trained-inference flavor uses the default (first) layer.
    return "predictions" if "predictions" in layers else layers[0]


def _assert_row_counts_match(
    predictions_path: str, footprints_path: str
) -> int:
    """Fail loudly when predictions and footprints do not line up.

    The prediction -> footprint join is positional, so a count mismatch
    would silently attach every damage value to the wrong building.

    Returns:
        The (shared) row count.

    Raises:
        FootprintPredictionMismatchError: on any mismatch.
    """
    footprint_count = count_features(footprints_path)
    prediction_count = count_features(
        predictions_path, layer=prediction_layer(predictions_path)
    )
    if footprint_count != prediction_count:
        raise FootprintPredictionMismatchError(
            "Prediction/footprint row count mismatch: "
            f"{prediction_count} predictions in {predictions_path} vs "
            f"{footprint_count} footprints in {footprints_path}. The "
            "prediction-to-footprint join is positional, so both files "
            "must have the same number of rows in the same order."
        )
    return footprint_count


def build_prediction_attrs(
    predictions_path: str, footprints_path: str
) -> Dict[str, Any]:
    """Build the columnar attribute payload for one model.

    Args:
        predictions_path: Prediction GeoPackage (either flavor — the
            trained-inference merge output or the embedding labeler's
            ``predictions`` layer).
        footprints_path: The image layer's building-footprints
            GeoPackage, used to resolve Overture ids positionally.

    Returns:
        ``{"n", "ids", "overtureIds", "damage", "unknown", "damaged"}``
        with every array the same length and ordered by row index.

    Raises:
        FootprintPredictionMismatchError: when the two files disagree on
            row count.
        ValueError: when the prediction row indices are not the
            contiguous range ``0..n-1``.
    """
    expected_count = _assert_row_counts_match(
        predictions_path, footprints_path
    )
    predictions: PredictionSet = read_predictions(
        predictions_path, footprints_path=footprints_path
    )
    rows = sorted(predictions.rows, key=lambda row: row.row_index)

    ids: List[int] = [int(row.row_index) for row in rows]
    if ids != list(range(expected_count)):
        raise ValueError(
            f"Prediction GeoPackage {predictions_path} does not carry a "
            f"contiguous 0..{expected_count - 1} row index; the editor "
            "indexes the sidecar arrays by tile feature id, so gaps or "
            "duplicates would mislabel buildings."
        )

    payload: Dict[str, Any] = {
        "n": expected_count,
        "ids": ids,
        "overtureIds": [
            "" if row.overture_id is None else str(row.overture_id)
            for row in rows
        ],
        "damage": [
            round(float(row.damage_fraction), VALUE_PRECISION) for row in rows
        ],
        "unknown": [
            round(float(row.unknown_fraction), VALUE_PRECISION) for row in rows
        ],
        "damaged": [int(row.damaged) for row in rows],
    }

    lengths = {
        key: len(value)
        for key, value in payload.items()
        if isinstance(value, list)
    }
    if set(lengths.values()) != {expected_count}:
        raise ValueError(
            "Prediction attribute arrays have inconsistent lengths "
            f"{lengths}; expected {expected_count} for every column."
        )
    return payload


def write_prediction_attrs(
    predictions_path: str, footprints_path: str, attrs_path: str
) -> Dict[str, Any]:
    """Build and write the attribute sidecar; return the payload."""
    payload = build_prediction_attrs(predictions_path, footprints_path)
    with open(attrs_path, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    logger.info(
        "Wrote prediction attributes for %s buildings -> %s",
        payload["n"],
        os.path.basename(attrs_path),
    )
    return payload


def read_edited_classes(predictions_path: str) -> Optional[List[str]]:
    """Return the ``edited_class`` column in row order, if present.

    Returns ``None`` for a GeoPackage that has no such column, i.e. any
    raw model output — only ``apply_edits`` writes it.
    """
    layer = prediction_layer(predictions_path)
    with fiona.open(predictions_path, layer=layer) as src:
        if EDITED_CLASS_FIELD not in src.schema["properties"]:
            return None
        return [
            str(feature["properties"].get(EDITED_CLASS_FIELD) or "")
            for feature in src
        ]


def build_edited_prediction_attrs(
    predictions_path: str, footprints_path: str
) -> Dict[str, Any]:
    """Build the sidecar of one analyst-edited prediction version.

    Same payload as :func:`build_prediction_attrs` plus a ``"classes"``
    array holding the analyst's final class per row (``"Damaged"``,
    ``"NotDamaged"`` or ``"Unknown"``), read from the ``edited_class``
    column ``apply_edits`` writes.

    The numeric columns alone cannot express that call: ``damage`` and
    ``unknown`` are still the model's fractions, so a building the
    analyst forced to ``Unknown`` looks pristine there. ``damaged``
    *does* already agree with the edit (``apply_edits`` rewrites it), so
    a client that ignores ``classes`` still renders damaged-vs-not
    correctly for the version.

    Args:
        predictions_path: An edited-version GeoPackage.
        footprints_path: The image layer's footprints GeoPackage.

    Returns:
        The payload. ``classes`` is omitted when the GeoPackage carries
        no ``edited_class`` column, which makes the function safe to
        call on a raw prediction file too.

    Raises:
        FootprintPredictionMismatchError: on a row-count mismatch.
        ValueError: when ``classes`` would not line up with the other
            columns.
    """
    payload = build_prediction_attrs(predictions_path, footprints_path)
    classes = read_edited_classes(predictions_path)
    if classes is None:
        logger.warning(
            "Prediction GeoPackage %s has no '%s' column; its sidecar "
            "carries no per-row class column.",
            predictions_path,
            EDITED_CLASS_FIELD,
        )
        return payload
    if len(classes) != payload["n"]:
        raise ValueError(
            f"Edited class column of {predictions_path} has "
            f"{len(classes)} values but the sidecar has {payload['n']} "
            "rows; refusing to write a misaligned sidecar."
        )
    payload[CLASSES_KEY] = classes
    return payload


def write_edited_prediction_attrs(
    predictions_path: str, footprints_path: str, attrs_path: str
) -> Dict[str, Any]:
    """Build and write an edited version's sidecar; return the payload."""
    payload = build_edited_prediction_attrs(predictions_path, footprints_path)
    with open(attrs_path, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    logger.info(
        "Wrote edited prediction attributes for %s buildings -> %s",
        payload["n"],
        os.path.basename(attrs_path),
    )
    return payload


def attrs_artifact_name(model_id: str) -> str:
    """Artifact name for a model's RAW prediction attribute sidecar."""
    return (
        ArtifactTypes.PREDICTION_ATTRS.value.substitute(modelId=model_id)
        + ".json"
    )


def version_attrs_artifact_name(model_id: str, version: int) -> str:
    """Artifact name for ONE edited version's attribute sidecar.

    The version is part of the name, so each save lands on its own blob
    and never overwrites another revision's sidecar — mirroring
    ``prediction_edits.edited_version_artifact_name`` for the GeoPackage
    the sidecar describes.
    """
    return (
        ArtifactTypes.PREDICTION_ATTRS_VERSION.value.substitute(
            modelId=model_id, version=int(version)
        )
        + ".json"
    )
