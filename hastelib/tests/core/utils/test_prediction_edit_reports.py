# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Saved-class reports retain raw scores but never rethreshold human calls."""

import json
import math
import os
import tempfile
import unittest

import fiona
from hastegeo.core.utils.assessment import (
    AssessmentInputs,
    build_assessment_inputs_from_gpkgs,
    compute_assessment_report,
)
from hastegeo.core.utils.prediction_edits import (
    PredictionOverride,
    apply_prediction_edits,
)
from hastegeo.core.utils.predictions import (
    FootprintPredictionMismatchError,
    read_effective_prediction_classes,
)

from .prediction_edit_fixtures import rewrite_properties, write_prediction_pair


class EditedReportTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 0.9, 0.9, None], [0.0, 0.0, 0.0, None]
        )
        self.labels = [
            ("building-0", "Damaged"),
            ("building-1", "NotDamaged"),
            ("building-2", "Damaged"),
            ("building-3", "NotDamaged"),
        ]

    def edited(self, assignments):
        return apply_prediction_edits(
            self.raw,
            self.footprints,
            os.path.join(self.directory, "saved.gpkg"),
            os.path.join(self.directory, "saved.json"),
            prediction_revision="historical-generation",
            version=7,
            overrides=assignments,
        )

    def test_saved_classes_control_both_reports_without_rethresholding(
        self,
    ) -> None:
        saved = self.edited(
            [
                PredictionOverride(0, "Damaged"),
                PredictionOverride(1, "NotDamaged"),
                PredictionOverride(2, "Unknown"),
                PredictionOverride(3, "NotDamaged"),
            ]
        )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints,
            saved.gpkg_path,
            labels=self.labels,
            is_edited=True,
        )
        # The read path does not replace scores with invented binary scores.
        self.assertEqual(inputs.damage_fractions["building-0"], 0.0)
        self.assertEqual(inputs.damage_fractions["building-1"], 0.9)
        self.assertIsNone(inputs.damage_fractions["building-3"])
        self.assertEqual(
            inputs.effective_classes,
            {
                "building-0": "Damaged",
                "building-1": "NotDamaged",
                "building-2": "Unknown",
                "building-3": "NotDamaged",
            },
        )
        self.assertTrue(inputs.is_edited)
        validation = read_effective_prediction_classes(
            saved.gpkg_path, self.footprints, threshold=1.0, is_edited=True
        )
        self.assertEqual(validation, inputs.effective_classes)
        reports = [
            compute_assessment_report(inputs, threshold=threshold)
            for threshold in (0.0, 0.1, 0.5, 1.0)
        ]
        for report in reports:
            self.assertEqual(report["matched"], 3)
            self.assertEqual(report["labeledUnknownPredictions"], 1)
            self.assertEqual(report["predictions"]["predictedDamaged"], 1)
            self.assertEqual(report["predictions"]["knownNonCloudy"], 3)
            self.assertEqual(report["predictions"]["cloudy"], 1)
            self.assertEqual(
                report["confusionMatrix"]["matrix"], [[1, 0], [0, 2]]
            )
            self.assertEqual(report["metrics"]["precision"], 1.0)
            self.assertEqual(report["metrics"]["recall"], 1.0)
            self.assertIsNone(report["metrics"]["averagePrecision"])
            self.assertEqual(
                report["precisionRecallCurve"],
                {
                    "mode": "operating_point",
                    "precision": [1.0],
                    "recall": [1.0],
                    "thresholds": [],
                },
            )
            json.dumps(report, allow_nan=False)

    def test_unknown_changes_do_not_bias_ground_truth_population_cohort(
        self,
    ) -> None:
        raw_inputs = build_assessment_inputs_from_gpkgs(
            self.footprints, self.raw, labels=self.labels, is_edited=False
        )
        before = compute_assessment_report(raw_inputs)
        saved = self.edited(
            [PredictionOverride(i, "Unknown") for i in range(4)]
        )
        after = compute_assessment_report(
            build_assessment_inputs_from_gpkgs(
                self.footprints,
                saved.gpkg_path,
                labels=self.labels,
                is_edited=True,
            )
        )
        self.assertEqual(
            before["populationEstimate"], after["populationEstimate"]
        )
        self.assertEqual(after["populationEstimate"]["n"], 4)
        self.assertEqual(after["populationEstimate"]["x"], 2)
        self.assertEqual(after["populationEstimate"]["estimatedDamaged"], 2.0)
        self.assertEqual(after["matched"], 0)
        self.assertEqual(after["labeledUnknownPredictions"], 4)
        self.assertIsNone(after["metrics"])
        self.assertIsNone(after["precisionRecallCurve"])

    def test_raw_default_stays_point_one_and_explicit_zero_is_distinct(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 0.05, 0.1, math.nextafter(0.1, 1.0)]
        )
        inputs = build_assessment_inputs_from_gpkgs(self.footprints, self.raw)
        self.assertIsNone(inputs.effective_classes)
        self.assertFalse(inputs.is_edited)
        default = compute_assessment_report(inputs)
        zero = compute_assessment_report(inputs, threshold=0.0)
        self.assertEqual(default["threshold"], 0.1)
        self.assertEqual(default["predictions"]["predictedDamaged"], 1)
        self.assertEqual(zero["predictions"]["predictedDamaged"], 3)
        self.assertEqual(
            read_effective_prediction_classes(
                self.raw, self.footprints, threshold=0.1, is_edited=False
            )["building-2"],
            "NotDamaged",
        )

    def test_binary_raw_inference_retains_continuous_curve_and_ap(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [0.0, 1.0]
        )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints,
            self.raw,
            flavor="inference",
            labels=[("building-0", "NotDamaged"), ("building-1", "Damaged")],
        )
        report = compute_assessment_report(inputs)
        self.assertIsNone(inputs.effective_classes)
        self.assertEqual(report["metrics"]["averagePrecision"], 1.0)
        self.assertNotEqual(
            report["precisionRecallCurve"].get("mode"), "operating_point"
        )
        self.assertTrue(report["precisionRecallCurve"]["thresholds"])
        self.assertEqual(
            compute_assessment_report(inputs, threshold=1.0)["predictions"][
                "predictedDamaged"
            ],
            0,
        )

    def test_raw_null_and_nonfinite_scores_abstain_without_disappearing(
        self,
    ) -> None:
        inputs = AssessmentInputs(
            damage_fractions={
                "a": None,
                "b": float("nan"),
                "c": 0.8,
                "d": 0.2,
            },
            unknown_fractions={
                "a": None,
                "b": 0.0,
                "c": float("inf"),
                "d": 0.0,
            },
            labels={
                "a": "Damaged",
                "b": "Damaged",
                "c": "NotDamaged",
                "d": "Damaged",
            },
            areas_m2={name: 100.0 for name in "abcd"},
        )
        report = compute_assessment_report(inputs)
        self.assertEqual(report["predictions"]["total"], 4)
        self.assertEqual(report["predictions"]["knownNonCloudy"], 1)
        self.assertEqual(report["labeledUnknownPredictions"], 3)
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["populationEstimate"]["n"], 4)
        self.assertEqual(report["populationEstimate"]["x"], 3)
        json.dumps(report, allow_nan=False)

    def test_report_source_marker_and_identity_must_match(self) -> None:
        with self.assertRaises(ValueError):
            build_assessment_inputs_from_gpkgs(
                self.footprints, self.raw, is_edited=True
            )
        saved = self.edited([])
        with self.assertRaises(ValueError):
            build_assessment_inputs_from_gpkgs(
                self.footprints, saved.gpkg_path, is_edited=False
            )
        rewrite_properties(
            saved.gpkg_path, lambda i, p: p.update(id=3) if i == 0 else None
        )
        with self.assertRaises(FootprintPredictionMismatchError):
            build_assessment_inputs_from_gpkgs(
                self.footprints, saved.gpkg_path
            )

    def test_missing_effective_classes_cannot_be_reinterpreted_as_raw(
        self,
    ) -> None:
        inputs = AssessmentInputs(damage_fractions={"a": 0.9}, is_edited=True)
        with self.assertRaises(ValueError):
            compute_assessment_report(inputs)
        inputs.effective_classes = {}
        with self.assertRaises(ValueError):
            compute_assessment_report(inputs)
        inputs.effective_classes = {"a": "invalid"}
        with self.assertRaises(ValueError):
            compute_assessment_report(inputs)

    def test_empty_sources_keep_report_inputs(self) -> None:
        self.raw, self.footprints = write_prediction_pair(self.directory, [])
        saved = self.edited([])
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints, saved.gpkg_path, is_edited=True
        )
        report = compute_assessment_report(inputs)
        self.assertEqual(report["predictions"]["total"], 0)
        self.assertEqual(report["populationEstimate"]["N"], 0)
        self.assertEqual(inputs.effective_classes, {})

    def test_null_footprint_geometry_has_no_area_but_keeps_analyst_outcome(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory, [None], [None], crs="EPSG:4326", null_geometry=True
        )
        saved = self.edited([PredictionOverride(0, "Damaged")])
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints,
            saved.gpkg_path,
            labels=[("building-0", "Damaged")],
            is_edited=True,
        )
        self.assertIsNone(inputs.areas_m2["building-0"])
        report = compute_assessment_report(inputs)
        self.assertEqual(report["predictions"]["total"], 1)
        self.assertEqual(report["populationEstimate"]["N"], 0)
        self.assertEqual(report["metrics"]["accuracy"], 1.0)

    def test_legacy_raw_report_schema_is_read_only_and_keeps_custom_fields(
        self,
    ) -> None:
        # Existing report-only GPKGs may have no overture_id/damaged columns.
        # Preserve that read compatibility without generating/backfilling files.
        old = os.path.join(self.directory, "legacy.gpkg")
        with fiona.open(
            old,
            "w",
            driver="GPKG",
            crs="EPSG:6933",
            schema={
                "geometry": "Polygon",
                "properties": {
                    "id": "int",
                    "score": "float",
                    "cloud": "float",
                    "edited_class": "str",
                },
            },
        ) as dst:
            for index in range(4):
                dst.write(
                    {
                        "geometry": None,
                        "properties": {
                            "id": index,
                            "score": 0.05,
                            "cloud": 0.0,
                            "edited_class": "",
                        },
                    }
                )
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints,
            old,
            damage_field="score",
            unknown_field="cloud",
        )
        self.assertFalse(inputs.is_edited)
        self.assertIsNone(inputs.effective_classes)
        self.assertEqual(
            compute_assessment_report(inputs)["predictions"][
                "predictedDamaged"
            ],
            0,
        )
        with fiona.open(old) as src:
            self.assertNotIn("overture_id", src.schema["properties"])

    def test_saved_embedding_is_categorical_without_threshold_reclassification(
        self,
    ) -> None:
        self.raw, self.footprints = write_prediction_pair(
            self.directory,
            [0.0, 1.0],
            flavor="embedding",
        )
        saved = self.edited([PredictionOverride(0, "Damaged")])
        inputs = build_assessment_inputs_from_gpkgs(
            self.footprints,
            saved.gpkg_path,
            flavor="embedding",
            is_edited=True,
            labels=[("building-0", "Damaged"), ("building-1", "NotDamaged")],
        )
        report = compute_assessment_report(
            inputs, threshold=1.0, unknown_threshold=1.0
        )
        self.assertEqual(report["predictions"]["predictedDamaged"], 2)
        self.assertEqual(
            report["precisionRecallCurve"]["mode"], "operating_point"
        )
        self.assertIsNone(report["metrics"]["averagePrecision"])
