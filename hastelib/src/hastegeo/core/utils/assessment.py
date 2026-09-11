# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Damage-assessment metrics: precision/recall/AP + finite-population CI.

Mirrors the "Analyze results" computation from
``notebooks/Evaluate-Gezanine_1.ipynb`` and from
``validation/evaluate.py``. Cleanly separates two pieces:

* :func:`compute_assessment_report` — a pure function that takes already-
  loaded per-building damage fractions, human labels, and (optional)
  footprint areas, and returns the same metric dictionary the
  ``Assessment Report`` modal renders.
* :func:`build_assessment_inputs_from_gpkgs` — a thin wrapper that reads
  the merged building+predictions GeoPackage (per-building
  ``damage_pct_0m``/``unknown_pct``/area) and a building footprints
  GeoPackage and produces the inputs ``compute_assessment_report`` wants.

Keeping the math in one place lets the HTTP endpoint, the CLI tool, and
unit tests all share the same code path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Iterable, Optional

from .gdal_security import harden_gdal

# Harden GDAL/OGR drivers before any geopandas/fiona read of the
# predictions/footprints GeoPackages (GDAL CVE compensating control —
# docs/known-vulnerabilities.md Root Cause C).
harden_gdal()

DAMAGED = "Damaged"
NOT_DAMAGED = "NotDamaged"
UNKNOWN = "Unknown"


@dataclass
class AssessmentInputs:
    """Inputs to :func:`compute_assessment_report`.

    Attributes:
        damage_fractions: mapping from building id (e.g. Overture string id)
            to the model's predicted damage fraction in [0, 1], or None
            when unscored. These are not replaced by analyst decisions.
        unknown_fractions: mapping from building id to the cloud/unknown
            cover fraction in [0, 1]; defaults to 0 for any id missing.
        areas_m2: mapping from building id to footprint area in square
            metres; defaults to ``None`` for any id missing. Used only by
            the population estimate (filtered by ``min_area_m2``).
        labels: mapping from building id to one of {Damaged, NotDamaged,
            Unknown}. Ids absent from the map are unlabeled.
        effective_classes: Complete categorical snapshot for an edited
            source; None keeps raw score-based reporting and its defaults.
        is_edited: Explicit selected-source marker. Edited sources must
            provide effective_classes, even when the snapshot has zero rows.
    """

    damage_fractions: dict[str, float | None]
    unknown_fractions: dict[str, float | None] = field(default_factory=dict)
    areas_m2: dict[str, Optional[float]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    # None means raw continuous scores, including binary-valued inference.
    # A saved snapshot supplies a complete categorical map instead.
    effective_classes: dict[str, str] | None = None
    is_edited: bool = False


# Critical z value for a two-sided 95% CI (norm.ppf(1 - 0.05/2)). Hard-coded
# so this module has no scipy/numpy dependency — both are heavy and would
# inflate the function-app cold start for a single constant. If we ever want
# arbitrary confidence levels we can revisit.
_Z_95 = 1.959963984540054


def _round(value: float, digits: int = 4) -> Optional[float]:
    """Round, returning None for non-finite values so JSON stays valid."""
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _average_precision(y_true: list[int], y_score: list[float]) -> float:
    """Average precision (area under the precision-recall curve).

    Implements the same step-function integral as
    ``sklearn.metrics.average_precision_score`` (the trapezoidal-free
    one): sort by descending score, walk the ranked list, and accumulate
    ``(recall_i - recall_{i-1}) * precision_i`` over thresholds where a
    new positive is seen. Hand-rolled because we deliberately don't pull
    scikit-learn into the function-app image.
    """
    n_pos = sum(y_true)
    if n_pos == 0 or len(y_true) == 0:
        return 0.0
    pairs = sorted(zip(y_score, y_true), key=lambda x: x[0], reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    ap = 0.0
    for _score, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / n_pos
        if recall > prev_recall:
            ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def _precision_recall_curve(
    y_true: list[int], y_score: list[float]
) -> tuple[list[float], list[float], list[float]]:
    """Same output shape as ``sklearn.metrics.precision_recall_curve``.

    Walks the descending-score ranking in two passes: the first
    accumulates cumulative (tp, fp) at every distinct threshold; the
    second turns each (tp, fp) pair into a (precision, recall) point.
    Ends with the sklearn sentinel ``(precision=1.0, recall=0.0)``.
    """
    n_pos = sum(y_true)
    if n_pos == 0 or len(y_true) == 0:
        return [1.0], [0.0], []

    # Pass 1: accumulate (tp, fp) at each distinct threshold.
    pairs = sorted(zip(y_score, y_true), key=lambda x: x[0], reverse=True)
    tp = fp = 0
    counts: list[tuple[float, int, int]] = []
    for score, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        if counts and counts[-1][0] == score:
            # Same score as the previous row — overwrite, don't append.
            counts[-1] = (score, tp, fp)
        else:
            counts.append((score, tp, fp))

    # Pass 2: convert to precision/recall + sklearn's closing sentinel.
    precisions = [t / (t + f) for _, t, f in counts]
    recalls = [t / n_pos for _, t, _f in counts]
    thresholds = [s for s, _t, _f in counts]
    precisions.append(1.0)
    recalls.append(0.0)
    return precisions, recalls, thresholds


def compute_assessment_report(
    inputs: AssessmentInputs,
    *,
    threshold: float = 0.1,
    min_area_m2: float = 50.0,
    pr_curve_max_points: int = 200,
    unknown_threshold: float = 0.0,
) -> dict:
    """Compute the assessment report dictionary.

    ``threshold`` is the damage fraction above which a building is called
    damaged (same default as the CLI script).

    ``min_area_m2`` is the minimum footprint area used to define the
    population N for the damaged-building count extrapolation. Areas are
    optional in the inputs; if any id has no area or area==None, that
    id is excluded from N but otherwise still contributes to the
    precision/recall computation.

    ``pr_curve_max_points`` downsamples the precision-recall curve before
    it goes over the wire — the modal renders an SVG with at most a few
    hundred points, no point shipping thousands.

    Raw scores retain the existing 0.1 report threshold default. Saved
    effective classes are categorical: neither report threshold changes them.
    Unknown predictions abstain from binary metrics but do not remove known
    ground-truth labels from the population-estimation sample.

    The return shape is documented on the
    ``GetAssessmentReport`` HTTP endpoint.
    """
    damage_fractions = inputs.damage_fractions
    unknown_fractions = inputs.unknown_fractions or {}
    areas_m2 = inputs.areas_m2 or {}
    labels = inputs.labels or {}

    for name, value in (
        ("threshold", threshold),
        ("unknown_threshold", unknown_threshold),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError(f"{name} must be a finite fraction in [0, 1].")
    categorical = inputs.effective_classes is not None
    if inputs.is_edited and not categorical:
        raise ValueError("Edited assessment inputs require effective classes.")
    if categorical:
        effective = dict(inputs.effective_classes)
        if set(effective) != set(damage_fractions):
            raise ValueError("Effective classes must cover every prediction.")
        if any(
            value not in (DAMAGED, NOT_DAMAGED, UNKNOWN)
            for value in effective.values()
        ):
            raise ValueError("Invalid effective prediction class.")
    else:
        effective = {}
        for bid, damage in damage_fractions.items():
            unknown = unknown_fractions.get(bid, 0.0)
            if (
                damage is None
                or unknown is None
                or not math.isfinite(damage)
                or not math.isfinite(unknown)
                or unknown > unknown_threshold
            ):
                effective[bid] = UNKNOWN
            else:
                effective[bid] = DAMAGED if damage > threshold else NOT_DAMAGED

    total = len(effective)
    total_known = sum(value != UNKNOWN for value in effective.values())
    total_unknown = total - total_known
    damaged_pred = sum(value == DAMAGED for value in effective.values())

    # Population N for the extrapolation: buildings whose area is large
    # enough that a human labeler could realistically have called them.
    N = sum(
        1
        for area in areas_m2.values()
        if area is not None and area > min_area_m2
    )

    # Label histogram (Damaged / NotDamaged / Unknown / other).
    label_counts: dict[str, int] = {DAMAGED: 0, NOT_DAMAGED: 0, UNKNOWN: 0}
    for lbl in labels.values():
        label_counts[lbl] = label_counts.get(lbl, 0) + 1

    # Keep ground-truth sampling independent from prediction abstentions:
    # editing a prediction to Unknown must not alter the estimated prevalence.
    population_truth: list[int] = []
    y_true: list[int] = []
    y_score: list[float] = []
    y_pred: list[int] = []
    missing = 0
    labeled_unknown = 0
    for bid, lbl in labels.items():
        if lbl not in (DAMAGED, NOT_DAMAGED):
            continue
        if bid not in effective:
            missing += 1
            continue
        truth = int(lbl == DAMAGED)
        population_truth.append(truth)
        if effective[bid] == UNKNOWN:
            labeled_unknown += 1
            continue
        predicted = int(effective[bid] == DAMAGED)
        y_true.append(truth)
        y_pred.append(predicted)
        y_score.append(
            float(predicted) if categorical else float(damage_fractions[bid])
        )

    n = len(y_true)
    x = sum(y_true)
    population_n = len(population_truth)
    population_x = sum(population_truth)

    # Pre-compute every field the response carries. Fields that don't
    # apply (no labels matched, no labels at all) just stay None — the
    # single return statement at the bottom assembles them all.
    if n > 0:
        tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
        fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
        fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
        tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)

        accuracy = (tp + tn) / n
        recall = _safe_div(tp, tp + fn)
        precision = _safe_div(tp, tp + fp)
        if categorical:
            # A human decision has no ranking or continuous score to sweep.
            ap = None
            pr_p, pr_r, pr_t = [precision], [recall], []
        else:
            ap = _average_precision(y_true, y_score) if x > 0 else None
            pr_p, pr_r, pr_t = _precision_recall_curve(y_true, y_score)
            if len(pr_p) > pr_curve_max_points:
                step = max(1, len(pr_p) // pr_curve_max_points)
                pr_p = pr_p[::step] + [pr_p[-1]]
                pr_r = pr_r[::step] + [pr_r[-1]]
                pr_t = pr_t[::step]
        evaluation_sample: Optional[dict] = {
            "n": n,
            "trueDamaged": x,
            "trueNotDamaged": n - x,
            "predictedPositive": int(sum(y_pred)),
            "hasBothClasses": 0 < x < n,
        }
        metrics: Optional[dict] = {
            "accuracy": _round(accuracy),
            "recall": _round(recall),
            "precision": _round(precision),
            "averagePrecision": _round(ap) if ap is not None else None,
        }
        confusion_matrix: Optional[dict] = {
            "labels": [DAMAGED, NOT_DAMAGED],
            # rows = actual, cols = predicted
            "matrix": [[tp, fn], [fp, tn]],
        }
        pr_curve: Optional[dict] = {
            "precision": [_round(v, 6) for v in pr_p],
            "recall": [_round(v, 6) for v in pr_r],
            "thresholds": [_round(v, 6) for v in pr_t],
        }
        if categorical:
            pr_curve["mode"] = "operating_point"
        error: Optional[str] = None
    else:
        evaluation_sample = None
        metrics = None
        confusion_matrix = None
        pr_curve = None
        error = "No sure-labeled buildings matched known predictions."

    # Same finite-population formula as before, using the ground-truth
    # cohort even when all model/analyst predictions are Unknown.
    if population_n:
        p_hat = population_x / population_n
        f = population_n / N if N > 0 else 0.0
        var_p = (
            (1 - f) * p_hat * (1 - p_hat) / (population_n - 1)
            if population_n > 1
            else 0.0
        )
        se_p = math.sqrt(max(var_p, 0.0))
        population_extra = {
            "pHat": _round(p_hat),
            "samplingFraction": _round(f, 6),
            "sePHat": _round(se_p, 6),
            "estimatedDamaged": _round(N * p_hat, 1),
            "ciLower": _round(N * (p_hat - _Z_95 * se_p), 1),
            "ciUpper": _round(N * (p_hat + _Z_95 * se_p), 1),
        }
    else:
        population_extra = {
            "pHat": None,
            "samplingFraction": None,
            "sePHat": None,
            "estimatedDamaged": None,
            "ciLower": None,
            "ciUpper": None,
        }

    response = {
        "matched": n,
        "totalLabels": len(labels),
        "labelCounts": label_counts,
        "sureLabels": label_counts[DAMAGED] + label_counts[NOT_DAMAGED],
        "unsureLabels": label_counts[UNKNOWN],
        "labeledMissingFromPredictions": missing,
        "labeledUnknownPredictions": labeled_unknown,
        "predictions": {
            "total": total,
            "knownNonCloudy": total_known,
            "cloudy": total_unknown,
            "predictedDamaged": damaged_pred,
            "predictedDamagedPctOfKnown": _round(
                _safe_div(damaged_pred, total_known) * 100, 2
            ),
        },
        "evaluationSample": evaluation_sample,
        "metrics": metrics,
        "confusionMatrix": confusion_matrix,
        "precisionRecallCurve": pr_curve,
        "populationEstimate": {
            "N": N,
            "minAreaM2": min_area_m2,
            "n": population_n,
            "x": population_x,
            "z": _Z_95,
            **population_extra,
        },
        "threshold": threshold,
    }
    if error is not None:
        response["error"] = error
    return response


def _building_areas_m2(footprints_path: str) -> dict[str, float | None]:
    """Compute square-metre footprint areas keyed by Overture id.

    Reprojects to the GeoPackage's estimated UTM CRS before measuring if
    the source is geographic, so areas come out in metres for any layer.
    """
    import geopandas as gpd

    gdf = gpd.read_file(footprints_path)
    if gdf.crs is None:
        raise ValueError(
            f"Footprints GeoPackage has no CRS: {footprints_path}"
        )
    if gdf.empty:
        return {}
    if not any(gdf.geometry.notna() & ~gdf.geometry.is_empty):
        return {str(value): None for value in gdf["id"]}
    if gdf.crs.is_projected:
        proj = gdf
    else:
        proj = gdf.to_crs(gdf.estimate_utm_crs())
    areas = [
        float(value) if math.isfinite(value) else None
        for value in proj.geometry.area.tolist()
    ]
    ids = gdf["id"].astype(str).tolist()
    return dict(zip(ids, areas))


def build_assessment_inputs_from_gpkgs(
    footprints_path: str,
    merged_predictions_path: str,
    *,
    labels: Iterable[tuple[str, str]] | None = None,
    damage_field: str = "damage_pct_0m",
    unknown_field: str = "unknown_pct",
    edited_class_field: str = "edited_class",
    flavor: str | None = None,
    is_edited: bool | None = None,
) -> AssessmentInputs:
    """Build :class:`AssessmentInputs` from on-disk GeoPackages.

    Validate source row IDs and explicit Overture IDs when present. Older
    report-only GPKGs lacking the Overture column retain their positional
    reader, but missing/renumbered rows now fail rather than misreporting.
    Raw scores remain continuous, including binary-valued inference. An
    edited snapshot adds a complete effective-class map instead of replacing
    model scores with synthetic numbers that could be rethresholded.

    ``labels`` is the validation app's ``{overture_id: {label, ...}}``
    map flattened to ``(id, label)`` pairs (or ``None`` if computing
    aggregate-only stats without any labels).
    """
    import fiona

    from .predictions import (
        EMBEDDING_FLAVOR,
        INFERENCE_FLAVOR,
        FootprintPredictionMismatchError,
        normalize_fraction,
        prediction_layer,
        read_footprint_ids,
        source_id,
        validate_prediction_class,
    )

    overture_ids = read_footprint_ids(footprints_path)

    damage_fractions: dict[str, float | None] = {}
    unknown_fractions: dict[str, float | None] = {}
    edited_values: dict[str, str | None] = {}
    layer = prediction_layer(merged_predictions_path)
    with fiona.open(merged_predictions_path, layer=layer) as src:
        if not src.crs:
            raise ValueError("Prediction GeoPackage must declare a CRS.")
        fields = src.schema["properties"]
        if "id" not in fields or damage_field not in fields:
            raise ValueError(
                "Prediction GeoPackage is missing report columns."
            )
        schema_flavor = (
            EMBEDDING_FLAVOR
            if layer == "predictions" and "area" in fields
            else INFERENCE_FLAVOR
        )
        if flavor is not None and flavor != schema_flavor:
            raise ValueError("Prediction flavor disagrees with its schema.")
        has_edit_column = edited_class_field in fields
        for index, feat in enumerate(src):
            props = feat["properties"]
            int_id = props["id"]
            if (
                isinstance(int_id, bool)
                or not isinstance(int_id, Integral)
                or int_id != index
                or index >= len(overture_ids)
            ):
                raise FootprintPredictionMismatchError(
                    "Invalid report source row ID."
                )
            oid = overture_ids[int_id]
            if (
                "overture_id" in fields
                and source_id(props["overture_id"]) != oid
            ):
                raise FootprintPredictionMismatchError(
                    "Report source ID mismatch."
                )
            damage_fractions[oid] = normalize_fraction(props[damage_field])
            unknown_fractions[oid] = normalize_fraction(
                props.get(unknown_field, 0.0)
            )
            edited_values[oid] = props.get(edited_class_field)
    if len(damage_fractions) != len(overture_ids):
        raise FootprintPredictionMismatchError(
            "Report source row count mismatch."
        )
    # Legacy raw report fixtures sometimes have an entirely blank edit
    # column. It is not a saved snapshot; partial/invalid edits are rejected.
    detected_edited = has_edit_column and (
        not edited_values
        or any(value not in (None, "") for value in edited_values.values())
    )
    if is_edited is not None and (
        not isinstance(is_edited, bool) or is_edited != detected_edited
    ):
        raise ValueError(
            "Selected report source disagrees with its edit schema."
        )
    effective_classes = (
        {
            oid: validate_prediction_class(value)
            for oid, value in edited_values.items()
        }
        if detected_edited
        else None
    )

    areas_m2 = _building_areas_m2(footprints_path)

    labels_dict: dict[str, str] = {}
    if labels is not None:
        for bid, lbl in labels:
            labels_dict[str(bid)] = lbl

    return AssessmentInputs(
        damage_fractions=damage_fractions,
        unknown_fractions=unknown_fractions,
        areas_m2=areas_m2,
        labels=labels_dict,
        effective_classes=effective_classes,
        is_edited=detected_edited,
    )
