# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Normalising reader for HASTE building-damage prediction GeoPackages.

Two producers write prediction GeoPackages and they do not agree on
layout, so every consumer that hand-rolled its own reader ended up
encoding one producer's quirks:

* **inference** — ``docker/training/code/merge_with_building_footprints.py``
  writes the default layer with ``id`` (sequential row index),
  ``damage_pct_0m`` / ``damage_pct_10m`` / ``damage_pct_20m`` (damage
  *fractions* in [0, 1], despite the ``pct`` name), ``damaged``
  (``damage_pct_0m > 0``) and ``unknown_pct``. Thresholding this flavor
  is meaningful because the damage fraction is continuous.
* **embedding** — the interactive building labeler writes a
  ``predictions`` layer with ``id``, ``damaged``, ``damage_pct_0m``
  (a degenerate 0.0/1.0 copy of ``damaged``), ``unknown_pct`` and
  ``area``. Thresholding this flavor is meaningless.

:func:`read_predictions` hides that difference behind
:class:`PredictionSet`, so callers only branch on
:attr:`PredictionSet.supports_threshold` when the distinction genuinely
matters.

Neither producer stores the Overture building id: predictions join to the
image layer's footprints GeoPackage **by row order**, matching
``hastegeo.core.utils.assessment.build_assessment_inputs_from_gpkgs``.
Pass ``footprints_path`` to resolve those ids.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

import fiona

from .gdal_security import harden_gdal

# Harden GDAL/OGR drivers before any fiona read of a user-supplied vector
# file (GDAL CVE compensating control — docs/known-vulnerabilities.md
# Root Cause C).
harden_gdal()

logger = logging.getLogger(__name__)

INFERENCE_FLAVOR = "inference"
EMBEDDING_FLAVOR = "embedding"

DAMAGE_FIELD = "damage_pct_0m"
UNKNOWN_FIELD = "unknown_pct"
DAMAGED_FIELD = "damaged"
AREA_FIELD = "area"
EMBEDDING_LAYER_NAME = "predictions"

# Overture ids live only in the footprints GeoPackage
# (hastegeo.core.utils.footprints writes them to this column).
FOOTPRINT_ID_FIELD = "id"


@dataclass
class PredictionRow:
    """One building's prediction, normalised across both producers.

    Attributes:
        row_index: Zero-based position of the row in the GeoPackage. This
            is the join key for the positional footprint join and for
            analyst edits — it is the row's *position*, not the value of
            its ``id`` column (the two coincide for both producers).
        overture_id: Overture building id, resolved from the footprints
            GeoPackage; ``None`` when no footprints file was supplied.
        damage_fraction: Predicted damage fraction in [0, 1].
        damaged: Producer's own binary damage call (0 or 1).
        unknown_fraction: Cloud/unknown cover fraction in [0, 1].
    """

    row_index: int
    overture_id: Optional[str]
    damage_fraction: float
    damaged: int
    unknown_fraction: float


@dataclass
class PredictionSet:
    """All predictions from one GeoPackage plus its provenance.

    Attributes:
        rows: Prediction rows in file order. Downstream consumers join
            positionally, so this order must never be rearranged.
        flavor: ``"inference"`` or ``"embedding"``.
        supports_threshold: ``True`` only when the damage fraction is
            continuous and thresholding it is meaningful.
        layer_name: Layer the predictions were read from.
        crs: CRS of the source layer, as returned by fiona.
    """

    rows: List[PredictionRow] = field(default_factory=list)
    flavor: str = INFERENCE_FLAVOR
    supports_threshold: bool = True
    layer_name: Optional[str] = None
    crs: Any = None

    def __len__(self) -> int:
        return len(self.rows)


def _as_float(value: Any) -> float:
    """Coerce a GeoPackage property to a float, treating NULL as 0.0."""
    if value is None:
        return 0.0
    return float(value)


def _as_int(value: Any) -> int:
    """Coerce a GeoPackage property to an int, treating NULL as 0."""
    if value is None:
        return 0
    return int(value)


def _detect_flavor(
    layer_name: Optional[str],
    field_names: List[str],
    damage_values: List[float],
) -> str:
    """Classify which producer wrote a prediction layer.

    A ``predictions`` layer carrying an ``area`` column is the
    interactive labeler's output. Failing that, a ``damage_pct_0m``
    column that only ever holds 0.0 or 1.0 is the labeler's degenerate
    copy of ``damaged`` rather than a real damage fraction.
    """
    if layer_name == EMBEDDING_LAYER_NAME and AREA_FIELD in field_names:
        return EMBEDDING_FLAVOR
    if damage_values and all(v in (0.0, 1.0) for v in damage_values):
        return EMBEDDING_FLAVOR
    return INFERENCE_FLAVOR


def read_footprint_ids(footprints_path: str) -> List[str]:
    """Read Overture building ids from a footprints GeoPackage, in order.

    Raises:
        ValueError: if the layer has no ``id`` column.
    """
    with fiona.open(footprints_path) as src:
        if FOOTPRINT_ID_FIELD not in src.schema["properties"]:
            raise ValueError(
                "Footprints GeoPackage is missing the "
                f"'{FOOTPRINT_ID_FIELD}' column: {footprints_path}"
            )
        return [
            str(feature["properties"][FOOTPRINT_ID_FIELD]) for feature in src
        ]


def read_predictions(
    gpkg_path: str,
    footprints_path: Optional[str] = None,
) -> PredictionSet:
    """Read a prediction GeoPackage written by either producer.

    Args:
        gpkg_path: Path to the prediction GeoPackage.
        footprints_path: Optional path to the image layer's footprints
            GeoPackage. When given, Overture ids are attached to each row
            by position, mirroring the positional join in
            ``hastegeo.core.utils.assessment``.

    Returns:
        A :class:`PredictionSet` whose rows are in file order.

    Raises:
        ValueError: if the GeoPackage has no layers, or if the footprints
            file has a different row count than the predictions (which
            would silently corrupt the positional join).
    """
    layers = fiona.listlayers(gpkg_path)
    if not layers:
        raise ValueError(f"Prediction GeoPackage has no layers: {gpkg_path}")
    layer_name = (
        EMBEDDING_LAYER_NAME if EMBEDDING_LAYER_NAME in layers else layers[0]
    )

    overture_ids: Optional[List[str]] = None
    if footprints_path:
        overture_ids = read_footprint_ids(footprints_path)

    rows: List[PredictionRow] = []
    damage_values: List[float] = []
    with fiona.open(gpkg_path, layer=layer_name) as src:
        crs = src.crs
        field_names = list(src.schema["properties"].keys())
        for row_index, feature in enumerate(src):
            props = feature["properties"]
            damage = _as_float(props.get(DAMAGE_FIELD))
            damage_values.append(damage)
            rows.append(
                PredictionRow(
                    row_index=row_index,
                    overture_id=None,
                    damage_fraction=damage,
                    damaged=_as_int(props.get(DAMAGED_FIELD)),
                    unknown_fraction=_as_float(props.get(UNKNOWN_FIELD)),
                )
            )

    if overture_ids is not None:
        if len(overture_ids) != len(rows):
            raise ValueError(
                "Footprints/predictions row count mismatch: "
                f"{len(overture_ids)} footprints in {footprints_path} vs "
                f"{len(rows)} predictions in {gpkg_path}. The prediction "
                "join is positional, so these files must line up row for "
                "row."
            )
        for row in rows:
            row.overture_id = overture_ids[row.row_index]

    flavor = _detect_flavor(layer_name, field_names, damage_values)
    logger.info(
        "Read %d predictions from %s (layer=%s, flavor=%s)",
        len(rows),
        gpkg_path,
        layer_name,
        flavor,
    )
    return PredictionSet(
        rows=rows,
        flavor=flavor,
        supports_threshold=flavor == INFERENCE_FLAVOR,
        layer_name=layer_name,
        crs=crs,
    )
