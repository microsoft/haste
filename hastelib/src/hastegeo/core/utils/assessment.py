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
    total_known = sum(
        1 for bid in damage_fractions if unknown_fractions.get(bid, 0.0) <= 0
    )
    total_unknown = total - total_known
    damaged_pred = sum(
        1
        for bid, dmg in damage_fractions.items()
        if dmg > threshold and unknown_fractions.get(bid, 0.0) <= 0
    )

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
        ap = _average_precision(y_true, y_score) if x > 0 else None

        pr_p, pr_r, pr_t = _precision_recall_curve(y_true, y_score)
        # Downsample for transport. Thresholds are one shorter than the
        # precision/recall arrays — use the same step for both.
        if len(pr_p) > pr_curve_max_points:
            step = max(1, len(pr_p) // pr_curve_max_points)
            pr_p = pr_p[::step] + [pr_p[-1]]
            pr_r = pr_r[::step] + [pr_r[-1]]
            pr_t = pr_t[::step]

        # Finite-population CI on the damage rate, scaled up to a count of
        # buildings. Matches the CLI script exactly.
        p_hat = x / n
        f = n / N if N > 0 else 0.0
        var_p = (1 - f) * p_hat * (1 - p_hat) / (n - 1) if n > 1 else 0.0
        se_p = math.sqrt(max(var_p, 0.0))
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
        population_extra: dict = {
            "pHat": _round(p_hat),
            "samplingFraction": _round(f, 6),
            "sePHat": _round(se_p, 6),
            "estimatedDamaged": _round(N * p_hat, 1),
            "ciLower": _round(N * (p_hat - _Z_95 * se_p), 1),
            "ciUpper": _round(N * (p_hat + _Z_95 * se_p), 1),
        }
        error: Optional[str] = None
    else:
        evaluation_sample = None
        metrics = None
        confusion_matrix = None
        pr_curve = None
        population_extra = {
            "pHat": None,
            "samplingFraction": None,
            "sePHat": None,
            "estimatedDamaged": None,
            "ciLower": None,
            "ciUpper": None,
        }
        error = "No sure-labeled buildings matched the predictions."

    response = {
        "matched": n,
        "totalLabels": len(labels),
        "labelCounts": label_counts,
        "sureLabels": label_counts[DAMAGED] + label_counts[NOT_DAMAGED],
        "unsureLabels": label_counts[UNKNOWN],
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
        "evaluationSample": evaluation_sample,
        "metrics": metrics,
        "confusionMatrix": confusion_matrix,
        "precisionRecallCurve": pr_curve,
        "populationEstimate": {
            "N": N,
            "minAreaM2": min_area_m2,
            "n": n,
            "x": x,
            "z": _Z_95,
            **population_extra,
        },
        "threshold": threshold,
    }
    if error is not None:
        response["error"] = error
    return response


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
