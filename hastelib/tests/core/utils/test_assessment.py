# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for hastegeo.core.utils.assessment.

Focuses on compute_assessment_report — the GeoPackage-reading wrappers
are exercised against tiny synthetic data in a follow-up integration
test and would otherwise need real Overture/inference files.
"""

import math
import os
import tempfile
import unittest

from hastegeo.core.utils.assessment import (
    DAMAGED,
    NOT_DAMAGED,
    UNKNOWN,
    AssessmentInputs,
    _average_precision,
    _precision_recall_curve,
    build_assessment_inputs_from_gpkgs,
    compute_assessment_report,
)


class TestAveragePrecision(unittest.TestCase):
    def test_perfectly_ranked(self):
        # All positives come before all negatives -> AP = 1.0
        y_true = [1, 1, 1, 0, 0, 0]
        y_score = [0.9, 0.8, 0.7, 0.4, 0.3, 0.1]
        self.assertAlmostEqual(_average_precision(y_true, y_score), 1.0)

    def test_no_positives(self):
        self.assertEqual(_average_precision([0, 0, 0], [0.1, 0.2, 0.3]), 0.0)

    def test_empty(self):
        self.assertEqual(_average_precision([], []), 0.0)

    def test_matches_sklearn_known_value(self):
        # Two positives, three negatives, sklearn AP = 0.5833...
        # Worked out by hand: ranked scores [0.9(0) 0.8(1) 0.7(0) 0.6(1) 0.5(0)]
        # On hit#1 at rank 2: P=1/2=0.5  R=1/2=0.5  -> contrib 0.5 * 0.5 = 0.25
        # On hit#2 at rank 4: P=2/4=0.5  R=2/2=1.0  -> contrib 0.5 * 0.5 = 0.25
        # AP = 0.5
        y_true = [0, 1, 0, 1, 0]
        y_score = [0.9, 0.8, 0.7, 0.6, 0.5]
        self.assertAlmostEqual(_average_precision(y_true, y_score), 0.5)


class TestPrecisionRecallCurve(unittest.TestCase):
    def test_perfect_ranking(self):
        precisions, recalls, thresholds = _precision_recall_curve(
            [1, 1, 0, 0], [0.9, 0.8, 0.3, 0.1]
        )
        # Curve always ends at (P=1, R=0)
        self.assertEqual(precisions[-1], 1.0)
        self.assertEqual(recalls[-1], 0.0)
        # First threshold: top-1 is a TP -> P=1, R=0.5
        self.assertAlmostEqual(precisions[0], 1.0)
        self.assertAlmostEqual(recalls[0], 0.5)

    def test_no_positives(self):
        precisions, recalls, thresholds = _precision_recall_curve(
            [0, 0, 0], [0.5, 0.4, 0.3]
        )
        self.assertEqual(precisions, [1.0])
        self.assertEqual(recalls, [0.0])
        self.assertEqual(thresholds, [])


class TestComputeAssessmentReport(unittest.TestCase):
    """Cover the headline computation paths."""

    def _build_inputs(self, n_pos=4, n_neg=6, with_unknown=2):
        damage_fractions = {}
        unknown_fractions = {}
        areas_m2 = {}
        labels = {}
        # Damaged buildings: damage frac well over threshold.
        for i in range(n_pos):
            bid = f"pos-{i}"
            damage_fractions[bid] = 0.6
            unknown_fractions[bid] = 0.0
            areas_m2[bid] = 200.0
            labels[bid] = DAMAGED
        # Not-damaged buildings: damage frac well under threshold.
        for i in range(n_neg):
            bid = f"neg-{i}"
            damage_fractions[bid] = 0.0
            unknown_fractions[bid] = 0.0
            areas_m2[bid] = 200.0
            labels[bid] = NOT_DAMAGED
        # Cloud-covered buildings — counted in totals but not in metrics.
        for i in range(with_unknown):
            bid = f"unk-{i}"
            damage_fractions[bid] = 0.0
            unknown_fractions[bid] = 0.5
            areas_m2[bid] = 200.0
            labels[bid] = UNKNOWN
        return AssessmentInputs(
            damage_fractions=damage_fractions,
            unknown_fractions=unknown_fractions,
            areas_m2=areas_m2,
            labels=labels,
        )

    def test_perfect_classifier(self):
        rpt = compute_assessment_report(self._build_inputs())
        self.assertEqual(rpt["matched"], 10)  # 4 positives + 6 negatives
        self.assertEqual(rpt["metrics"]["accuracy"], 1.0)
        self.assertEqual(rpt["metrics"]["precision"], 1.0)
        self.assertEqual(rpt["metrics"]["recall"], 1.0)
        self.assertEqual(rpt["metrics"]["averagePrecision"], 1.0)
        self.assertEqual(rpt["confusionMatrix"]["matrix"], [[4, 0], [0, 6]])
        # Unknown labels are excluded from matching.
        self.assertEqual(rpt["labelCounts"][UNKNOWN], 2)
        # Predictions: 4 damaged out of 10 known (12 total - 2 cloudy).
        self.assertEqual(rpt["predictions"]["total"], 12)
        self.assertEqual(rpt["predictions"]["knownNonCloudy"], 10)
        self.assertEqual(rpt["predictions"]["cloudy"], 2)
        self.assertEqual(rpt["predictions"]["predictedDamaged"], 4)

    def test_population_estimate_ci_contains_truth(self):
        rpt = compute_assessment_report(self._build_inputs())
        pop = rpt["populationEstimate"]
        # N = 12 buildings with area>50m^2 (all of them).
        self.assertEqual(pop["N"], 12)
        # 4 damaged out of n=10 in the sample -> p_hat=0.4
        self.assertEqual(pop["n"], 10)
        self.assertEqual(pop["x"], 4)
        self.assertAlmostEqual(pop["pHat"], 0.4)
        # Y_hat = 12 * 0.4 = 4.8
        self.assertAlmostEqual(pop["estimatedDamaged"], 4.8)
        # CI must enclose the point estimate.
        self.assertLessEqual(pop["ciLower"], pop["estimatedDamaged"])
        self.assertGreaterEqual(pop["ciUpper"], pop["estimatedDamaged"])

    def test_min_area_filters_population(self):
        # Halve every footprint so only smaller-than-min-area is left.
        inputs = self._build_inputs()
        for bid in inputs.areas_m2:
            inputs.areas_m2[bid] = 10.0
        rpt = compute_assessment_report(inputs, min_area_m2=50.0)
        self.assertEqual(rpt["populationEstimate"]["N"], 0)
        # With N=0, sampling fraction is 0 and the Y_hat is also 0.
        self.assertEqual(rpt["populationEstimate"]["estimatedDamaged"], 0.0)

    def test_missing_areas_drop_from_population_only(self):
        inputs = self._build_inputs(n_pos=2, n_neg=2, with_unknown=0)
        # No areas at all -> N == 0 but metrics still compute.
        inputs.areas_m2 = {}
        rpt = compute_assessment_report(inputs)
        self.assertEqual(rpt["populationEstimate"]["N"], 0)
        self.assertEqual(rpt["matched"], 4)
        self.assertEqual(rpt["metrics"]["accuracy"], 1.0)

    def test_unknown_labels_excluded_from_matching(self):
        inputs = self._build_inputs(n_pos=2, n_neg=2, with_unknown=3)
        rpt = compute_assessment_report(inputs)
        self.assertEqual(rpt["matched"], 4)
        self.assertEqual(rpt["labelCounts"][UNKNOWN], 3)
        self.assertEqual(rpt["sureLabels"], 4)
        self.assertEqual(rpt["unsureLabels"], 3)

    def test_labeled_building_without_prediction_is_counted_missing(self):
        inputs = self._build_inputs(n_pos=1, n_neg=1, with_unknown=0)
        inputs.labels["ghost-1"] = DAMAGED
        rpt = compute_assessment_report(inputs)
        # 2 matched, 1 missing
        self.assertEqual(rpt["matched"], 2)
        self.assertEqual(rpt["labeledMissingFromPredictions"], 1)

    def test_no_matched_labels_returns_error_field(self):
        # Predictions exist but the labels reference different ids.
        inputs = AssessmentInputs(
            damage_fractions={"pred-1": 0.7, "pred-2": 0.1},
            unknown_fractions={"pred-1": 0.0, "pred-2": 0.0},
            areas_m2={"pred-1": 100.0, "pred-2": 100.0},
            labels={"label-1": DAMAGED, "label-2": NOT_DAMAGED},
        )
        rpt = compute_assessment_report(inputs)
        self.assertEqual(rpt["matched"], 0)
        self.assertIn("error", rpt)

    def test_threshold_changes_predicted_positive(self):
        inputs = AssessmentInputs(
            damage_fractions={"a": 0.05, "b": 0.15, "c": 0.45, "d": 0.85},
            unknown_fractions={"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0},
            areas_m2={"a": 100.0, "b": 100.0, "c": 100.0, "d": 100.0},
            labels={
                "a": NOT_DAMAGED,
                "b": NOT_DAMAGED,
                "c": DAMAGED,
                "d": DAMAGED,
            },
        )
        rpt_low = compute_assessment_report(inputs, threshold=0.1)
        # threshold=0.1 -> {b,c,d} predicted positive (b is a false positive)
        self.assertEqual(rpt_low["evaluationSample"]["predictedPositive"], 3)
        rpt_high = compute_assessment_report(inputs, threshold=0.5)
        # threshold=0.5 -> only d (one false negative on c)
        self.assertEqual(rpt_high["evaluationSample"]["predictedPositive"], 1)

    def test_finite_population_correction_shrinks_se(self):
        # n == N -> sampling fraction = 1 -> SE = 0 -> CI collapses to point.
        inputs = AssessmentInputs(
            damage_fractions={f"b{i}": 0.5 for i in range(10)},
            unknown_fractions={f"b{i}": 0.0 for i in range(10)},
            areas_m2={f"b{i}": 100.0 for i in range(10)},
            labels={
                f"b{i}": (DAMAGED if i < 4 else NOT_DAMAGED) for i in range(10)
            },
        )
        rpt = compute_assessment_report(inputs)
        pop = rpt["populationEstimate"]
        self.assertEqual(pop["N"], 10)
        self.assertEqual(pop["n"], 10)
        # f = 1 -> var = 0 -> se = 0 -> CI = point estimate (within FP rounding).
        self.assertAlmostEqual(pop["sePHat"], 0.0)
        self.assertAlmostEqual(pop["ciLower"], pop["estimatedDamaged"])
        self.assertAlmostEqual(pop["ciUpper"], pop["estimatedDamaged"])

    def test_json_finite_values_only(self):
        # Round-trip through json to make sure no NaN / inf snuck through.
        import json

        rpt = compute_assessment_report(self._build_inputs())
        s = json.dumps(rpt, allow_nan=False)
        self.assertIn('"matched":', s)
        # No floats should round-trip into infinity.
        round_tripped = json.loads(s)
        for section in ("metrics", "populationEstimate"):
            for v in round_tripped[section].values():
                if isinstance(v, float):
                    self.assertTrue(math.isfinite(v), f"{section} -> {v}")


class TestEditedPredictionsAreHonoured(unittest.TestCase):
    """An analyst's saved call must outrank the model's own score.

    ``apply_edits`` rewrites ``damaged``/``edited_class`` but leaves
    ``damage_pct_0m`` at whatever the model predicted. Reading the score
    here reported the raw model's counts under an edited version's name.
    """

    def _write(self, directory, rows):
        import fiona
        from fiona.crs import CRS
        from fiona.model import Feature, Geometry

        footprints = os.path.join(directory, "footprints.gpkg")
        predictions = os.path.join(directory, "predictions.gpkg")

        def square(i):
            return Geometry(
                type="Polygon",
                coordinates=[
                    [
                        (i, 0.0),
                        (i + 0.0005, 0.0),
                        (i + 0.0005, 0.0005),
                        (i, 0.0005),
                        (i, 0.0),
                    ]
                ],
            )

        with fiona.open(
            footprints,
            "w",
            driver="GPKG",
            crs=CRS.from_epsg(4326),
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
        ) as dst:
            for i, _ in enumerate(rows):
                dst.write(
                    Feature(
                        geometry=square(float(i)),
                        properties={"id": f"overture-{i}"},
                    )
                )

        schema = {
            "geometry": "Polygon",
            "properties": {
                "id": "int",
                "damage_pct_0m": "float",
                "unknown_pct": "float",
                "edited_class": "str",
            },
        }
        with fiona.open(
            predictions,
            "w",
            driver="GPKG",
            crs=CRS.from_epsg(4326),
            schema=schema,
        ) as dst:
            for i, (damage, edited) in enumerate(rows):
                dst.write(
                    Feature(
                        geometry=square(float(i)),
                        properties={
                            "id": i,
                            "damage_pct_0m": damage,
                            "unknown_pct": 0.0,
                            "edited_class": edited,
                        },
                    )
                )
        return footprints, predictions

    def test_edited_class_overrides_the_model_score(self):
        # Row 0: model says undamaged, analyst says Damaged.
        # Row 1: model says damaged, analyst says NotDamaged.
        # Row 2: model says damaged, analyst says Unknown.
        with tempfile.TemporaryDirectory() as tmp:
            footprints, predictions = self._write(
                tmp,
                [
                    (0.0, "Damaged"),
                    (0.9, "NotDamaged"),
                    (0.9, "Unknown"),
                ],
            )
            inputs = build_assessment_inputs_from_gpkgs(
                footprints, predictions
            )

        self.assertEqual(inputs.damage_fractions["overture-0"], 1.0)
        self.assertEqual(inputs.damage_fractions["overture-1"], 0.0)
        self.assertEqual(inputs.unknown_fractions["overture-2"], 1.0)

        report = compute_assessment_report(inputs)
        # Only row 0 counts as damaged, and row 2 leaves the known set.
        self.assertEqual(report["predictions"]["predictedDamaged"], 1)
        self.assertEqual(report["predictions"]["knownNonCloudy"], 2)
        self.assertEqual(report["predictions"]["cloudy"], 1)

    def test_raw_predictions_still_use_the_score(self):
        # No edited_class column values: unchanged behaviour.
        with tempfile.TemporaryDirectory() as tmp:
            footprints, predictions = self._write(
                tmp, [(0.0, ""), (0.9, ""), (0.9, "")]
            )
            inputs = build_assessment_inputs_from_gpkgs(
                footprints, predictions
            )

        self.assertEqual(inputs.damage_fractions["overture-1"], 0.9)
        report = compute_assessment_report(inputs)
        self.assertEqual(report["predictions"]["predictedDamaged"], 2)


if __name__ == "__main__":
    unittest.main()
