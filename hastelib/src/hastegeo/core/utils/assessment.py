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
from typing import Iterable, Optional

DAMAGED = "Damaged"
NOT_DAMAGED = "NotDamaged"
UNKNOWN = "Unknown"


@dataclass
class AssessmentInputs:
    """Inputs to :func:`compute_assessment_report`.

    Attributes:
        damage_fractions: mapping from building id (e.g. Overture string id)
            to the model's predicted damage fraction in [0, 1].
        unknown_fractions: mapping from building id to the cloud/unknown
            cover fraction in [0, 1]; defaults to 0 for any id missing.
        areas_m2: mapping from building id to footprint area in square
            metres; defaults to ``None`` for any id missing. Used only by
            the population estimate (filtered by ``min_area_m2``).
        labels: mapping from building id to one of {Damaged, NotDamaged,
            Unknown}. Ids absent from the map are unlabeled.
    """

    damage_fractions: dict[str, float]
    unknown_fractions: dict[str, float] = field(default_factory=dict)
    areas_m2: dict[str, Optional[float]] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)


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

    Returns three parallel lists ``(precision, recall, thresholds)`` of
    length ``n_thresholds + 1`` for precision/recall and ``n_thresholds``
    for thresholds. Curves end with ``(precision=1.0, recall=0.0)``.
    """
    n_pos = sum(y_true)
    if n_pos == 0 or len(y_true) == 0:
        return [1.0], [0.0], []
    pairs = sorted(zip(y_score, y_true), key=lambda x: x[0], reverse=True)
    precisions: list[float] = []
    recalls: list[float] = []
    thresholds: list[float] = []
    tp = 0
    fp = 0
    # Snapshot of (tp, fp) at the previous score block — used when we
    # flush a curve point at a new score. Initialized so the first
    # iteration has no point to flush (last_score is None then anyway).
    tp_prev = 0
    fp_prev = 0
    last_score: Optional[float] = None
    for score, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        # Only record a curve point when the score changes — matches
        # sklearn's behavior of producing one point per distinct threshold.
        if last_score is None or score != last_score:
            if last_score is not None:
                precisions.append(tp_prev / (tp_prev + fp_prev))
                recalls.append(tp_prev / n_pos)
                thresholds.append(last_score)
            last_score = score
        tp_prev, fp_prev = tp, fp
    # Flush the final threshold.
    precisions.append(tp_prev / (tp_prev + fp_prev))
    recalls.append(tp_prev / n_pos)
    thresholds.append(last_score)
    # sklearn appends a sentinel (1, 0) point that closes the curve.
    precisions.append(1.0)
    recalls.append(0.0)
    return precisions, recalls, thresholds


def compute_assessment_report(
    inputs: AssessmentInputs,
    *,
    threshold: float = 0.1,
    min_area_m2: float = 50.0,
    pr_curve_max_points: int = 200,
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

    The return shape is documented on the
    ``GetAssessmentReport`` HTTP endpoint.
    """
    damage_fractions = inputs.damage_fractions
    unknown_fractions = inputs.unknown_fractions or {}
    areas_m2 = inputs.areas_m2 or {}
    labels = inputs.labels or {}

    total = len(damage_fractions)

    # Buildings the model considers "known" (i.e., not entirely cloud-covered).
    known_ids: list[str] = [
        bid for bid in damage_fractions if unknown_fractions.get(bid, 0.0) <= 0
    ]
    total_known = len(known_ids)
    total_unknown = total - total_known

    damaged_pred = sum(
        1 for bid in known_ids if damage_fractions[bid] > threshold
    )

    # Population N for the extrapolation: buildings whose area is large
    # enough that a human labeler could realistically have called them.
    pop_ids: list[str] = []
    for bid in damage_fractions:
        area = areas_m2.get(bid)
        if area is not None and area > min_area_m2:
            pop_ids.append(bid)
    N = len(pop_ids)

    # Label histogram (Damaged / NotDamaged / Unknown / other).
    label_counts: dict[str, int] = {DAMAGED: 0, NOT_DAMAGED: 0, UNKNOWN: 0}
    for lbl in labels.values():
        label_counts[lbl] = label_counts.get(lbl, 0) + 1
    sure_labels = label_counts[DAMAGED] + label_counts[NOT_DAMAGED]
    unsure_labels = label_counts[UNKNOWN]

    # Build y_true / y_score from sure-labeled buildings that are also
    # in the prediction set. Drops Unknown labels and labels for buildings
    # the model never assessed.
    y_true: list[int] = []
    y_score: list[float] = []
    missing = 0
    for bid, lbl in labels.items():
        if lbl == UNKNOWN:
            continue
        if bid not in damage_fractions:
            missing += 1
            continue
        y_true.append(1 if lbl == DAMAGED else 0)
        y_score.append(float(damage_fractions[bid]))

    n = len(y_true)
    x = sum(y_true)
    y_pred = [1 if s > threshold else 0 for s in y_score]

    if n == 0:
        return {
            "matched": 0,
            "totalLabels": len(labels),
            "labelCounts": label_counts,
            "sureLabels": sure_labels,
            "unsureLabels": unsure_labels,
            "labeledMissingFromPredictions": missing,
            "predictions": {
                "total": total,
                "knownNonCloudy": total_known,
                "cloudy": total_unknown,
                "predictedDamaged": damaged_pred,
                "predictedDamagedPctOfKnown": _round(
                    _safe_div(damaged_pred, total_known) * 100, 2
                ),
            },
            "populationEstimate": {
                "N": N,
                "minAreaM2": min_area_m2,
                "n": 0,
                "x": 0,
                "pHat": None,
                "samplingFraction": None,
                "sePHat": None,
                "z": _Z_95,
                "estimatedDamaged": None,
                "ciLower": None,
                "ciUpper": None,
            },
            "threshold": threshold,
            "error": "No sure-labeled buildings matched the predictions.",
        }

    # Pointwise confusion matrix and per-class metrics at the threshold.
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)

    accuracy = (tp + tn) / n
    recall = _safe_div(tp, tp + fn)
    precision = _safe_div(tp, tp + fp)

    has_both_classes = 0 < x < n
    ap = _average_precision(y_true, y_score) if x > 0 else None

    pr_p, pr_r, pr_t = _precision_recall_curve(y_true, y_score)
    # Downsample for transport.
    if len(pr_p) > pr_curve_max_points:
        step = max(1, len(pr_p) // pr_curve_max_points)
        pr_p = pr_p[::step] + [pr_p[-1]]
        pr_r = pr_r[::step] + [pr_r[-1]]
    # Thresholds are one shorter than the precision/recall arrays.
    if len(pr_t) > pr_curve_max_points:
        step = max(1, len(pr_t) // pr_curve_max_points)
        pr_t = pr_t[::step]

    # Finite-population CI on the damage rate, scaled up to a count of
    # buildings. Matches the CLI script exactly.
    p_hat = x / n
    f = n / N if N > 0 else 0.0
    if n > 1:
        var_p = (1 - f) * p_hat * (1 - p_hat) / (n - 1)
    else:
        var_p = 0.0
    se_p = math.sqrt(max(var_p, 0.0))
    Y_hat = N * p_hat
    ci_lower = N * (p_hat - _Z_95 * se_p)
    ci_upper = N * (p_hat + _Z_95 * se_p)

    return {
        "matched": n,
        "totalLabels": len(labels),
        "labelCounts": label_counts,
        "sureLabels": sure_labels,
        "unsureLabels": unsure_labels,
        "labeledMissingFromPredictions": missing,
        "predictions": {
            "total": total,
            "knownNonCloudy": total_known,
            "cloudy": total_unknown,
            "predictedDamaged": damaged_pred,
            "predictedDamagedPctOfKnown": _round(
                _safe_div(damaged_pred, total_known) * 100, 2
            ),
        },
        "evaluationSample": {
            "n": n,
            "trueDamaged": x,
            "trueNotDamaged": n - x,
            "predictedPositive": int(sum(y_pred)),
            "hasBothClasses": has_both_classes,
        },
        "metrics": {
            "accuracy": _round(accuracy),
            "recall": _round(recall),
            "precision": _round(precision),
            "averagePrecision": _round(ap) if ap is not None else None,
        },
        "confusionMatrix": {
            "labels": [DAMAGED, NOT_DAMAGED],
            # rows = actual, cols = predicted
            "matrix": [[tp, fn], [fp, tn]],
        },
        "precisionRecallCurve": {
            "precision": [_round(v, 6) for v in pr_p],
            "recall": [_round(v, 6) for v in pr_r],
            "thresholds": [_round(v, 6) for v in pr_t],
        },
        "populationEstimate": {
            "N": N,
            "minAreaM2": min_area_m2,
            "n": n,
            "x": x,
            "pHat": _round(p_hat),
            "samplingFraction": _round(f, 6),
            "sePHat": _round(se_p, 6),
            "z": _Z_95,
            "estimatedDamaged": _round(Y_hat, 1),
            "ciLower": _round(ci_lower, 1),
            "ciUpper": _round(ci_upper, 1),
        },
        "threshold": threshold,
    }


def _building_areas_m2(footprints_path: str) -> dict[str, float]:
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
    if gdf.crs.is_projected:
        proj = gdf
    else:
        proj = gdf.to_crs(gdf.estimate_utm_crs())
    areas = proj.geometry.area.tolist()
    ids = gdf["id"].astype(str).tolist()
    return dict(zip(ids, areas))


def build_assessment_inputs_from_gpkgs(
    footprints_path: str,
    merged_predictions_path: str,
    *,
    labels: Iterable[tuple[str, str]] | None = None,
    damage_field: str = "damage_pct_0m",
    unknown_field: str = "unknown_pct",
) -> AssessmentInputs:
    """Build :class:`AssessmentInputs` from on-disk GeoPackages.

    The merged predictions file uses sequential integer ``id``s in the
    same row order as the footprints file (this is what
    ``merge_with_building_footprints.py`` writes). We use that ordering
    to map back to Overture string ids.

    ``labels`` is the validation app's ``{overture_id: {label, ...}}``
    map flattened to ``(id, label)`` pairs (or ``None`` if computing
    aggregate-only stats without any labels).
    """
    import fiona

    with fiona.open(footprints_path) as src:
        overture_ids = [str(feat["properties"]["id"]) for feat in src]

    damage_fractions: dict[str, float] = {}
    unknown_fractions: dict[str, float] = {}
    with fiona.open(merged_predictions_path) as src:
        for feat in src:
            props = feat["properties"]
            int_id = props["id"]
            if int_id < 0 or int_id >= len(overture_ids):
                continue
            oid = overture_ids[int_id]
            dmg = props.get(damage_field)
            if dmg is None:
                continue
            damage_fractions[oid] = float(dmg)
            unknown_fractions[oid] = float(props.get(unknown_field) or 0.0)

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
    )
