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

:func:`resolve_prediction_source` picks *which* GeoPackage a reader
should open: the newest analyst-edited version when there is one, the
raw model output otherwise.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import fiona

from .gdal_security import harden_gdal
from .model_readiness import ModelLike, model_field

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

#: ``version=0`` explicitly selects the raw model output, so a caller can
#: ask for "what the model actually predicted" even after edits exist.
RAW_PREDICTION_VERSION = 0


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


class PredictionVersionNotFoundError(ValueError):
    """Raised when a requested edited prediction version does not exist.

    The HTTP layer maps this to a 404: the caller asked for a specific
    revision of a model's predictions and there is no such revision.
    """


@dataclass
class PredictionSource:
    """The prediction GeoPackage a reader should open, plus provenance.

    Attributes:
        url: Blob URL of the GeoPackage. Empty when the model has no
            predictions at all.
        version: Edited-version number, or ``None`` for the raw model
            output in ``Model.gpkgUrl``.
        created_at: When the edited version was saved (``None`` for raw).
        created_by: Who saved the edited version (``None`` for raw).
        edited_count: Buildings the analyst overrode in this version.
    """

    url: str = ""
    version: Optional[int] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    edited_count: int = 0

    @property
    def is_edited(self) -> bool:
        """``True`` when this is an analyst-edited version, not the raw."""
        return self.version is not None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for an HTTP payload."""
        return {
            "url": self.url,
            "version": self.version,
            "createdAt": self.created_at,
            "createdBy": self.created_by,
            "editedCount": self.edited_count,
            "isEdited": self.is_edited,
        }


def _entry_to_dict(entry: Any) -> Dict[str, Any]:
    """Normalise one ``editedPredictions`` entry to a plain dict.

    Model documents come off the metadata store as dicts, but a
    :class:`~hastegeo.core.models.projects.Model` instance carries
    ``EditedPredictionVersion`` objects. Callers (and ``json.dumps``)
    want the same shape either way.
    """
    if isinstance(entry, Mapping):
        return dict(entry)
    dump = getattr(entry, "model_dump", None)
    if callable(dump):
        return dump()
    return dict(getattr(entry, "__dict__", {}) or {})


def _entry_version(entry: Mapping[str, Any]) -> int:
    """Version number of an entry, treating a missing one as 0."""
    try:
        return int(entry.get("version") or 0)
    except (TypeError, ValueError):
        return 0


def edited_prediction_versions(model: ModelLike) -> List[Dict[str, Any]]:
    """Return ``Model.editedPredictions`` as dicts, newest version first.

    Ordering is by the numeric ``version`` field rather than list order:
    the list is append-only today, but readers must not depend on that.
    """
    entries = model_field(model, "editedPredictions") or []
    return sorted(
        (_entry_to_dict(entry) for entry in entries),
        key=_entry_version,
        reverse=True,
    )


def describe_prediction_source(
    model: ModelLike, version: Optional[int] = None
) -> PredictionSource:
    """Resolve which prediction GeoPackage to read, with its provenance.

    Newest-wins by default: analyst edits are what a reader should see,
    and ADR-0005 deliberately did not add a mutable "active version"
    pointer to the model, so "newest edit, else raw" *is* the selection
    rule. Pass ``version`` to pin a specific revision (``0`` selects the
    raw model output explicitly).

    Args:
        model: A Model instance or its raw metadata dict.
        version: Edited version number to pin, ``0`` for the raw model
            output, or ``None`` for "newest edit, else raw".

    Returns:
        A :class:`PredictionSource`. Its ``url`` is empty only when the
        model has no predictions at all — callers surface that as a 404.

    Raises:
        PredictionVersionNotFoundError: when ``version`` is given but no
            such edited version exists.
    """
    raw_url = model_field(model, "gpkgUrl") or ""
    entries = [
        entry
        for entry in edited_prediction_versions(model)
        if entry.get("gpkgUrl")
    ]

    if version is None:
        if not entries:
            return PredictionSource(url=raw_url)
        entry = entries[0]
    else:
        requested = int(version)
        if requested == RAW_PREDICTION_VERSION:
            return PredictionSource(url=raw_url)
        entry = next(
            (e for e in entries if _entry_version(e) == requested), None
        )
        if entry is None:
            available = [_entry_version(e) for e in entries]
            raise PredictionVersionNotFoundError(
                f"Edited prediction version {requested} does not exist "
                f"for model {model_field(model, 'modelId')}. Available "
                f"versions: {available} (0 selects the raw model output)."
            )

    return PredictionSource(
        url=str(entry.get("gpkgUrl") or ""),
        version=_entry_version(entry),
        created_at=entry.get("createdAt"),
        created_by=entry.get("createdBy"),
        edited_count=int(entry.get("editedCount") or 0),
    )


def resolve_prediction_source(
    model: ModelLike, version: Optional[int] = None
) -> str:
    """Return the URL of the prediction GeoPackage a reader should open.

    Thin wrapper over :func:`describe_prediction_source` for the common
    case where the caller only needs the URL. Reports, publishing and
    the results viewer all go through this so analyst edits reach every
    reader instead of stopping at the editor.
    """
    return describe_prediction_source(model, version=version).url
