# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest

from hastegeo.core.models.prediction_edits import (
    PredictionSelectionRequest,
    SavedPredictionResponse,
)
from hastegeo.core.processors.assessment import AssessmentReportProcessor
from hastegeo.core.processors.validation_reports import (
    ValidationReportProcessor,
)
from hastegeo.core.processors.visualizer import VisualizerProcessor
from hastegeo.core.utils.metadata import MetadataUtils
from hastegeo.core.utils.prediction_attrs import write_prediction_attrs
from pydantic import ValidationError

from ..utils.prediction_edit_fixtures import write_prediction_pair
from .test_prediction_edits import EditTestCase
from .test_prediction_results import LAYER_ID, MODEL_ID, PROJECT_ID


class StandardEditTestCase(EditTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.install_raw([0.2, 0.05, None], [0.0, 0.0, None])

    def install_raw(
        self, scores: list[float | None], unknowns: list[float | None]
    ) -> None:
        raw, footprints = write_prediction_pair(
            self.directory, scores, unknowns
        )
        revision = MetadataUtils.generate_id()
        attrs = os.path.join(self.directory, "raw-attrs.json")
        write_prediction_attrs(
            raw,
            footprints,
            attrs,
            prediction_revision=revision,
            flavor="inference",
        )
        namespace = ["standard-fixture", revision]
        for name, path in (
            ("raw.gpkg", raw),
            ("footprints.gpkg", footprints),
            ("attrs.json", attrs),
        ):
            self.storage.store_artifact(
                name, src_path=path, namespace=namespace
            )

        def url(name: str) -> str:
            return self.storage.get_download_url(
                identifier=name, extra_partition_keys=namespace
            )

        model = self.current().model_copy(
            update={
                "modelType": "trained",
                "inferenceStatus": "Processed",
                "predictionRevision": revision,
                "gpkgUrl": url("raw.gpkg"),
                "predictionAttrsUrl": url("attrs.json"),
                "predictedBuildingCount": len(scores),
            }
        )
        self.save_record("model", MODEL_ID, model.model_dump(mode="json"))
        self.save_record(
            "imagelayer",
            LAYER_ID,
            {"buildingFootprintsUrl": url("footprints.gpkg")},
        )
        self.save_record(
            "validation",
            LAYER_ID,
            {
                "labels": {
                    "building-0": {"label": "Damaged"},
                    "building-1": {"label": "NotDamaged"},
                    "building-2": {"label": "Damaged"},
                }
            },
        )


class TestVersionedPredictionReports(
    StandardEditTestCase, unittest.IsolatedAsyncioTestCase
):
    def edited(self) -> SavedPredictionResponse:
        return self.edit(
            threshold=0.1,
            overrides=[
                {"id": 0, "class": "Unknown"},
                {"id": 2, "class": "Damaged"},
            ],
        )

    async def test_human_class_for_null_unknown_is_valid_and_used_by_reports(
        self,
    ) -> None:
        saved = self.edited()
        attrs = self.attrs(saved.version)
        self.assertIsNone(attrs["damage"][2])
        self.assertIsNone(attrs["unknown"][2])
        self.assertEqual(attrs["modelClasses"][2], "Unknown")
        self.assertEqual(attrs["classes"][2], "Damaged")
        report = await AssessmentReportProcessor(self.config).generate(
            PROJECT_ID,
            LAYER_ID,
            MODEL_ID,
            version=saved.version,
            threshold=0.99,
        )
        self.assertEqual(report["predictionVersion"], saved.version)
        self.assertEqual(
            report["predictionRevision"], saved.predictionRevision
        )
        self.assertEqual(report["matched"], 2)
        self.assertEqual(report["populationEstimate"]["n"], 3)
        self.assertEqual(report["labeledUnknownPredictions"], 1)
        self.assertEqual(report["threshold"], 0.1)
        self.assertIsNone(report["metrics"]["averagePrecision"])
        self.assertEqual(
            report["precisionRecallCurve"]["mode"], "operating_point"
        )
        self.assertEqual(len(report["precisionRecallCurve"]["precision"]), 1)
        self.assertEqual(len(report["precisionRecallCurve"]["recall"]), 1)
        self.assertEqual(report["precisionRecallCurve"]["thresholds"], [])
        validation = await ValidationReportProcessor(
            self.config
        ).generate_validation(
            PredictionSelectionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=saved.version,
            )
        )
        self.assertEqual(validation["matched"], 2)
        self.assertEqual(validation["totalValidationLabels"], 3)
        self.assertEqual(validation["excludedUnknownPredictions"], 1)
        self.assertEqual(
            validation["confusionMatrix"]["matrix"], [[1, 0], [0, 1]]
        )

    async def test_report_selection_is_independent_and_raw_default_stays_point_one(
        self,
    ) -> None:
        saved = self.edited()
        processor = AssessmentReportProcessor(self.config)
        raw = await processor.generate(
            PROJECT_ID, LAYER_ID, MODEL_ID, version=0
        )
        default = await processor.generate(PROJECT_ID, LAYER_ID, MODEL_ID)
        self.assertEqual(raw["predictionVersion"], 0)
        self.assertEqual(raw["threshold"], 0.1)
        self.assertNotIn("mode", raw["precisionRecallCurve"])
        self.assertEqual(default["predictionVersion"], saved.version)
        self.assertEqual(
            raw["populationEstimate"], default["populationEstimate"]
        )

    async def test_historical_version_reports_do_not_need_current_raw_or_viewer(
        self,
    ) -> None:
        saved = self.edited()
        self.save_record(
            "model",
            MODEL_ID,
            {
                "gpkgUrl": None,
                "predictionAttrsUrl": None,
                "predictionRevision": MetadataUtils.generate_id(),
                "predictedBuildingCount": 0,
            },
        )
        self.save_record("imagelayer", LAYER_ID, {"footprintPmtilesUrl": None})
        with self.assertRaises(FileNotFoundError):
            await AssessmentReportProcessor(self.config).generate(
                PROJECT_ID, LAYER_ID, MODEL_ID
            )
        report = await AssessmentReportProcessor(self.config).generate(
            PROJECT_ID, LAYER_ID, MODEL_ID, version=saved.version
        )
        self.assertEqual(
            report["predictionRevision"], saved.predictionRevision
        )
        self.assertEqual(report["predictionVersion"], saved.version)

    async def test_saved_damage_threshold_creates_new_version_preserving_manual_assignments(
        self,
    ) -> None:
        self.install_raw([0.8, 0.4, None], [0.0, 0.0, None])
        pins = [
            {"id": 0, "class": "NotDamaged"},
            {"id": 2, "class": "Damaged"},
        ]
        saved = self.edit(threshold=0.5, overrides=pins)
        before = self.attrs(saved.version)
        changed = self.edit(
            baseVersion=saved.version,
            threshold=0.2,
            overrides=pins,
        )
        after = self.attrs(changed.version)
        self.assertEqual(
            after["classes"], ["NotDamaged", "Damaged", "Damaged"]
        )
        self.assertEqual(after["overrideClasses"], before["overrideClasses"])
        self.assertEqual(after["modelClasses"], before["modelClasses"])
        self.assertEqual(after["unknownThreshold"], before["unknownThreshold"])
        self.assertEqual(self.attrs(saved.version), before)
        self.assertEqual(len(self.current().editedPredictions), 2)
        result = VisualizerProcessor(self.config).load(
            PredictionSelectionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=changed.version,
            )
        )
        self.assertTrue(result.supportsThreshold)
        self.assertTrue(result.editReadiness["ready"])
        self.assertEqual(result.threshold, 0.2)

    async def test_saved_unknown_threshold_stays_fixed(self) -> None:
        saved = self.edited()
        from hastegeo.core.processors.prediction_results import (
            PredictionRequestError,
        )

        with self.assertRaises(PredictionRequestError):
            self.edit(baseVersion=saved.version, unknownThreshold=0.2)
        self.assertEqual(len(self.current().editedPredictions), 1)
        result = VisualizerProcessor(self.config).load(
            PredictionSelectionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
            )
        )
        self.assertEqual(result.predictionVersion, saved.version)
        self.assertTrue(result.supportsThreshold)
        self.assertEqual(result.threshold, 0.1)

    async def test_raw_binary_inference_keeps_threshold_support(self) -> None:
        self.install_raw([0.0, 1.0], [0.0, 0.0])
        result = VisualizerProcessor(self.config).load(
            PredictionSelectionRequest(
                projectId=PROJECT_ID,
                imageLayerId=LAYER_ID,
                modelId=MODEL_ID,
                version=0,
            )
        )
        self.assertEqual(result.flavor, "inference")
        self.assertTrue(result.supportsThreshold)
        saved = self.edit(threshold=1.0, overrides=[])
        self.assertEqual(
            self.attrs(saved.version)["classes"], ["NotDamaged", "NotDamaged"]
        )
        self.assertEqual(saved.editedCount, 1)


class TestEditingWireValidation(EditTestCase):
    def test_invalid_override_threshold_or_identity_is_rejected(self) -> None:
        for changes in (
            {"baseVersion": True},
            {"baseVersion": -1},
            {"clientRequestId": "bad"},
            {"predictionRevision": ""},
            {"threshold": float("nan")},
            {"unknownThreshold": 2},
            {"overrides": [{"id": True, "class": "Damaged"}]},
            {"overrides": [{"id": 0, "class": "Intact"}]},
            {
                "overrides": [
                    {"id": 0, "class": "Damaged"},
                    {"id": 0, "class": "Unknown"},
                ]
            },
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError):
                    self.edit_request(**changes)

    def test_embedding_thresholds_cannot_be_changed(self) -> None:
        from hastegeo.core.processors.prediction_results import (
            PredictionRequestError,
        )

        with self.assertRaises(PredictionRequestError):
            self.edit(threshold=0.1)
        self.assertEqual(self.current().editedPredictions, [])
