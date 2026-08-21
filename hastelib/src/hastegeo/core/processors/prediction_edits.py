# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Apply analyst edits to model predictions and version the result.

An analyst reviews a model's building-damage predictions, retunes the
damage/unknown thresholds and hand-corrects individual buildings. Saving
that review must never mutate the raw model output: :func:`apply_edits`
derives a NEW GeoPackage from the raw one and
:func:`store_edited_version` stores it under its own version, leaving
``Model.gpkgUrl`` pointing at the raw predictions forever.

The derived file is a strict superset of the source — every original
column is kept, ``damaged`` is rewritten to agree with the analyst's
call, and ``edited_class`` / ``edit_threshold`` / ``overture_id`` are
appended. **Row order is preserved exactly**, because the prediction →
footprint join downstream is positional (see
``hastegeo.core.utils.assessment.build_assessment_inputs_from_gpkgs``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import fiona
from fiona.model import Feature

from ..config import ArtifactTypes, Config
from ..models.projects import Model
from ..utils.assessment import DAMAGED, NOT_DAMAGED, UNKNOWN
from ..utils.gdal_security import harden_gdal
from ..utils.logs import Logger
from ..utils.predictions import DAMAGED_FIELD, PredictionRow, read_predictions

if TYPE_CHECKING:
    from .artifacts import ArtifactProcessor

# Harden GDAL/OGR drivers before any fiona read/write of a user-supplied
# vector file (GDAL CVE compensating control —
# docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

logger = Logger.get_logger(__name__)

EDITED_CLASS_FIELD = "edited_class"
EDIT_THRESHOLD_FIELD = "edit_threshold"
OVERTURE_ID_FIELD = "overture_id"

VALID_EDIT_CLASSES = (DAMAGED, NOT_DAMAGED, UNKNOWN)

GPKG_DRIVER = "GPKG"


@dataclass
class EditSummary:
    """Outcome of one :func:`apply_edits` run.

    Attributes:
        total_rows: Number of rows written, always equal to the number of
            rows in the source GeoPackage.
        counts: Row count per final class, keyed by ``"Damaged"``,
            ``"NotDamaged"`` and ``"Unknown"``.
        overrides_applied: Number of analyst overrides that matched a row
            and were applied.
    """

    total_rows: int = 0
    counts: Dict[str, int] = field(
        default_factory=lambda: {DAMAGED: 0, NOT_DAMAGED: 0, UNKNOWN: 0}
    )
    overrides_applied: int = 0

    @property
    def damaged(self) -> int:
        return self.counts.get(DAMAGED, 0)

    @property
    def not_damaged(self) -> int:
        return self.counts.get(NOT_DAMAGED, 0)

    @property
    def unknown(self) -> int:
        return self.counts.get(UNKNOWN, 0)

    def to_dict(self) -> Dict[str, Any]:
        """Render as a JSON-serialisable dict for API responses."""
        return {
            "totalRows": self.total_rows,
            "counts": dict(self.counts),
            "overridesApplied": self.overrides_applied,
        }


def _validate_threshold(name: str, value: float) -> float:
    """Validate a damage/unknown threshold as a fraction in [0, 1].

    ``damage_pct_0m`` and ``unknown_pct`` are fractions despite their
    names, so a caller passing a 0-100 percentage would silently
    misclassify every building. Fail loudly instead.
    """
    try:
        threshold = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            f"{name} must be a fraction between 0.0 and 1.0 "
            f"(damage values are fractions, not percentages), "
            f"got {threshold}"
        )
    return threshold


def _normalize_overrides(
    overrides: Optional[Dict[int, str]]
) -> Dict[int, str]:
    """Validate analyst overrides and coerce their keys to row indices.

    Raises:
        ValueError: on a non-integer row index or an unrecognised class.
    """
    if not overrides:
        return {}

    normalized: Dict[int, str] = {}
    for raw_index, raw_class in overrides.items():
        try:
            row_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Override row index must be an integer, got {raw_index!r}"
            ) from exc
        if raw_class not in VALID_EDIT_CLASSES:
            raise ValueError(
                f"Invalid override class {raw_class!r} for row {row_index}. "
                f"Valid classes are: {', '.join(VALID_EDIT_CLASSES)}"
            )
        normalized[row_index] = raw_class
    return normalized


def derive_class(
    row: PredictionRow,
    *,
    threshold: float,
    unknown_threshold: float,
    overrides: Dict[int, str],
) -> str:
    """Return the final class for one row, honouring edit precedence.

    An explicit analyst override always wins; otherwise unknown coverage
    takes precedence over damage, and both comparisons are strictly
    greater-than so a threshold of 0.0 keeps pristine buildings out of
    the damaged bucket.
    """
    override = overrides.get(row.row_index)
    if override is not None:
        return override
    if row.unknown_fraction > unknown_threshold:
        return UNKNOWN
    if row.damage_fraction > threshold:
        return DAMAGED
    return NOT_DAMAGED


def _output_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Extend a source schema with the edit columns, preserving order."""
    properties = dict(schema["properties"])
    properties.setdefault(DAMAGED_FIELD, "int")
    properties[EDITED_CLASS_FIELD] = "str"
    properties[EDIT_THRESHOLD_FIELD] = "float"
    properties[OVERTURE_ID_FIELD] = "str"
    return {"geometry": schema["geometry"], "properties": properties}


def apply_edits(
    src_gpkg: str,
    dst_gpkg: str,
    *,
    threshold: float,
    unknown_threshold: float = 0.0,
    overrides: Dict[int, str],
    footprints_path: Optional[str] = None,
) -> EditSummary:
    """Write an edited copy of a prediction GeoPackage.

    Args:
        src_gpkg: Path to the raw (or previously edited) prediction
            GeoPackage. Never modified.
        dst_gpkg: Path the edited GeoPackage is written to; replaced if
            it already exists.
        threshold: Damage fraction in [0, 1]; a building is damaged when
            its damage fraction is strictly greater.
        unknown_threshold: Unknown/cloud fraction in [0, 1]; a building
            is unknown when its unknown fraction is strictly greater.
        overrides: Analyst class overrides keyed by row index. Values
            must be one of ``Damaged``, ``NotDamaged``, ``Unknown``.
        footprints_path: Optional footprints GeoPackage used to resolve
            Overture ids positionally.

    Returns:
        An :class:`EditSummary` describing what was written.

    Raises:
        ValueError: on an invalid threshold, an invalid override, or a
            footprints/predictions row-count mismatch.
    """
    threshold = _validate_threshold("threshold", threshold)
    unknown_threshold = _validate_threshold(
        "unknown_threshold", unknown_threshold
    )
    normalized_overrides = _normalize_overrides(overrides)

    predictions = read_predictions(src_gpkg, footprints_path=footprints_path)
    if not predictions.supports_threshold:
        logger.warning(
            "Prediction file %s is the '%s' flavor: its damage values are "
            "binary, so the %s threshold only separates 0.0 from 1.0.",
            src_gpkg,
            predictions.flavor,
            threshold,
        )

    rows: List[PredictionRow] = predictions.rows
    summary = EditSummary()

    dst_dir = os.path.dirname(dst_gpkg)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(dst_gpkg):
        os.remove(dst_gpkg)

    try:
        with fiona.open(src_gpkg, layer=predictions.layer_name) as src:
            schema = _output_schema(src.schema)
            with fiona.open(
                dst_gpkg,
                "w",
                driver=GPKG_DRIVER,
                crs=src.crs,
                schema=schema,
                layer=predictions.layer_name,
            ) as dst:
                for row_index, feature in enumerate(src):
                    if row_index >= len(rows):
                        raise ValueError(
                            f"Prediction GeoPackage {src_gpkg} yielded more "
                            "rows on the second pass than on the first; "
                            "refusing to write a misaligned output."
                        )
                    row = rows[row_index]
                    final_class = derive_class(
                        row,
                        threshold=threshold,
                        unknown_threshold=unknown_threshold,
                        overrides=normalized_overrides,
                    )
                    if row_index in normalized_overrides:
                        summary.overrides_applied += 1
                    summary.counts[final_class] = (
                        summary.counts.get(final_class, 0) + 1
                    )

                    properties = dict(feature["properties"])
                    properties[DAMAGED_FIELD] = (
                        1 if final_class == DAMAGED else 0
                    )
                    properties[EDITED_CLASS_FIELD] = final_class
                    properties[EDIT_THRESHOLD_FIELD] = threshold
                    properties[OVERTURE_ID_FIELD] = row.overture_id or ""
                    dst.write(
                        Feature(
                            geometry=feature.geometry,
                            properties=properties,
                        )
                    )
                    summary.total_rows += 1
    except Exception:
        # Never leave a half-written GeoPackage behind: a truncated file
        # would still look like a valid edited version to the caller.
        if os.path.exists(dst_gpkg):
            os.remove(dst_gpkg)
        raise

    if summary.total_rows != len(rows):
        raise ValueError(
            f"Wrote {summary.total_rows} rows but read {len(rows)} from "
            f"{src_gpkg}; refusing to return a misaligned output."
        )

    unmatched = len(normalized_overrides) - summary.overrides_applied
    if unmatched:
        logger.warning(
            "%d override(s) referenced row indices outside %s (%d rows) "
            "and were ignored.",
            unmatched,
            src_gpkg,
            summary.total_rows,
        )
    logger.info(
        "Wrote %d edited predictions to %s (%s)",
        summary.total_rows,
        dst_gpkg,
        summary.counts,
    )
    return summary


def _version_of(entry: Union[Model, Dict[str, Any]]) -> Optional[int]:
    """Extract the version number from a dict or Pydantic entry."""
    value = (
        entry.get("version")
        if isinstance(entry, dict)
        else getattr(entry, "version", None)
    )
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring non-integer edited-prediction version %r", value
        )
        return None


def next_version(model_doc: Union[Model, Dict[str, Any]]) -> int:
    """Return the next edited-prediction version for a model.

    Args:
        model_doc: A ``Model`` instance or its dict representation.

    Returns:
        ``1`` when the model has no edited predictions yet, otherwise one
        past the highest existing version (versions are append-only, so
        deleting a revision must not let a new one reuse its number).
    """
    if isinstance(model_doc, dict):
        entries = model_doc.get("editedPredictions") or []
    else:
        entries = getattr(model_doc, "editedPredictions", None) or []

    versions = [
        version
        for version in (_version_of(entry) for entry in entries)
        if version is not None
    ]
    if not versions:
        return 1
    return max(versions) + 1


def edited_version_artifact_name(model_id: str, version: int) -> str:
    """Return the artifact name for one edited-prediction version."""
    return (
        ArtifactTypes.EDITED_PREDICTIONS_GPKG.value.substitute(
            modelId=model_id,
            version=version,
        )
        + ".gpkg"
    )


def store_edited_version(
    project_id: str,
    model_id: str,
    version: int,
    local_gpkg_path: str,
    *,
    processor: Optional["ArtifactProcessor"] = None,
    config: Optional[Config] = None,
) -> str:
    """Store an edited GeoPackage as a new version and return its URL.

    The artifact name embeds the version, so each save lands on its own
    blob and never overwrites a previous revision — or the raw model
    prediction referenced by ``Model.gpkgUrl``.

    Args:
        project_id: Project the model belongs to; used as the storage
            partition key.
        model_id: Model whose predictions were edited.
        version: Version number from :func:`next_version`.
        local_gpkg_path: Path to the GeoPackage written by
            :func:`apply_edits`.
        processor: Optional pre-built ``ArtifactProcessor`` (used by
            tests and by callers that already hold one).
        config: Optional ``Config`` used when building the processor.

    Returns:
        The download URL of the stored artifact.

    Raises:
        FileNotFoundError: if ``local_gpkg_path`` does not exist.
    """
    if not os.path.exists(local_gpkg_path):
        raise FileNotFoundError(
            f"Edited GeoPackage not found: {local_gpkg_path}"
        )

    if processor is None:
        # Imported lazily so the pure-geospatial half of this module stays
        # importable without the queue/runner stack ArtifactProcessor pulls
        # in (Batch tasks import apply_edits alone).
        from .artifacts import ArtifactProcessor as _ArtifactProcessor

        processor = _ArtifactProcessor(project_id, config=config)

    artifact_name = edited_version_artifact_name(model_id, version)
    processor.store_artifact(
        artifact_name=artifact_name, src_path=local_gpkg_path
    )
    url = processor.get_download_url(identifier=artifact_name)
    logger.info(
        "Stored edited predictions v%s for model %s at %s",
        version,
        model_id,
        artifact_name,
    )
    return url
