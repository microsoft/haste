# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Model-only publication tests; GIS validation has its own native suite."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.prediction_results import (
    BuildingPredictionsRequest,
    ModelArtifactRequest,
)
from hastegeo.core.models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    Project,
)
from hastegeo.core.processors import prediction_results
from hastegeo.core.processors.visualizer import build_visualizer
from hastegeo.core.utils.prediction_readiness import (
    raw_predictions_readiness,
    results_readiness,
)

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
LAYER_ID = "550e8400-e29b-41d4-a716-446655440000"
OTHER_LAYER = "550e8400-e29b-41d4-a716-446655440001"
MODEL_ID = "0042"


def attrs(revision: str, flavor: str = "embedding") -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "predictionRevision": revision,
        "flavor": flavor,
        "n": 2,
        "ids": [0, 1],
        "overtureIds": ["a", "b"],
        "damage": [1.0, 0.0],
        "unknown": [0.0, 0.0],
        "damaged": [1, 0],
        "classes": ["Damaged", "NotDamaged"],
    }


class ResultsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = Config()
        self.config.storage_type = self.config.artifact_storage_type = "local"
        self.config.storage_config = {"directory": self.directory}
        self.config.artifact_storage_config = {"directory": self.directory}
        self.config.TEMP_DIR = self.directory
        self.storage = UnifiedArtifactStorage(
            "local", directory=self.directory
        )
        Path(self.directory, "footprints.gpkg").write_bytes(
            b"transport fixture"
        )
        self.layer = ImageLayer(
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            buildingFootprintsUrl=self.storage.get_download_url(
                identifier="footprints.gpkg"
            ),
            footprintPmtilesUrl="https://storage/tiles",
        )
        self.record = Model(
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            modelId=MODEL_ID,
            modelType="embedding",
            status="Processed",
            name="Flood / São #1",
            gpkgUrl="https://storage/old.gpkg",
            predictionAttrsUrl="https://storage/old.json",
            predictionRevision="old",
            predictedBuildingCount=2,
            predictedAt="yesterday",
        ).model_dump()
        self.metadata = MagicMock()
        self.metadata.load.side_effect = self.load
        self.metadata.load_all_from_partition.side_effect = lambda: [
            deepcopy(self.record)
        ]
        self.metadata.save.side_effect = lambda key, data: self.record.update(
            deepcopy(data)
        )
        self.enterContext(
            patch.object(
                prediction_results,
                "MetadataProcessor",
                return_value=self.metadata,
            )
        )
        self.writer = self.enterContext(
            patch.object(
                prediction_results,
                "write_building_predictions",
                side_effect=self.write,
            )
        )
        self.processor = prediction_results.PredictionResultsProcessor(
            self.config
        )

    def load(self, key: str, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("data_format") == "yaml":
            return {}
        return (
            deepcopy(self.record)
            if key == MODEL_ID
            else self.layer.model_dump()
        )

    def write(
        self,
        source: str,
        rows: list,
        gpkg: str,
        sidecar: str,
        *,
        prediction_revision: str
    ) -> Any:
        Path(gpkg).write_bytes(b"new GPKG transport fixture")
        Path(sidecar).write_text(json.dumps(attrs(prediction_revision)))
        return SimpleNamespace(gpkg_path=gpkg, attrs_path=sidecar, count=2)

    def request(self, **changes: Any) -> BuildingPredictionsRequest:
        return BuildingPredictionsRequest.model_validate(
            {
                "projectId": PROJECT_ID,
                "imageLayerId": LAYER_ID,
                "modelId": MODEL_ID,
                "predictions": [
                    {"id": 0, "damaged": 1},
                    {"id": 1, "damaged": 0},
                ],
                **changes,
            }
        )


class TestPredictionResults(ResultsTestCase):
    def test_pair_is_published_once_after_both_uploads(self) -> None:
        original = UnifiedArtifactStorage.store_artifact

        def store(
            storage: UnifiedArtifactStorage, *args: Any, **kwargs: Any
        ) -> str:
            self.assertEqual(self.record["predictionRevision"], "old")
            self.metadata.save.assert_not_called()
            return original(storage, *args, **kwargs)

        with patch.object(UnifiedArtifactStorage, "store_artifact", store):
            result = self.processor.save_building_predictions(self.request())
        self.metadata.save.assert_called_once()
        self.assertEqual(result["buildingCount"], 2)
        self.assertTrue(result["predictionsReady"])
        self.assertIn("/predictions/0042/", self.record["gpkgUrl"])
        self.assertIn(
            result["predictionRevision"], result["predictionAttrsUrl"]
        )

    def test_upload_or_gis_failure_preserves_the_good_pair(self) -> None:
        before = deepcopy(self.record)
        with patch.object(
            UnifiedArtifactStorage,
            "store_artifact",
            side_effect=["orphan", RuntimeError("upload failed")],
        ):
            with self.assertRaises(RuntimeError):
                self.processor.save_building_predictions(self.request())
        self.writer.side_effect = ValueError("invalid coverage")
        with self.assertRaises(prediction_results.PredictionRequestError):
            self.processor.save_building_predictions(self.request())
        self.assertEqual(self.record, before)
        self.metadata.save.assert_not_called()

    def test_clear_needs_no_footprint_download(self) -> None:
        self.layer.buildingFootprintsUrl = None
        with patch.object(
            prediction_results, "fetch_prediction_file"
        ) as fetch:
            result = self.processor.save_building_predictions(
                self.request(predictions=[])
            )
        fetch.assert_not_called()
        self.writer.assert_not_called()
        self.assertEqual(result["buildingCount"], 0)
        self.assertIsNone(self.record["gpkgUrl"])
        self.assertIsNone(self.record["predictionAttrsUrl"])
        self.assertNotEqual(self.record["predictionRevision"], "old")
        self.assertNotEqual(self.record["predictedAt"], "yesterday")

    def test_known_superseded_write_does_not_replace_model_fields(
        self,
    ) -> None:
        original = self.write

        def supersede(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            self.record["predictionRevision"] = "another-output"
            return result

        self.writer.side_effect = supersede
        with self.assertRaises(prediction_results.PredictionSupersededError):
            self.processor.save_building_predictions(self.request())
        self.assertEqual(self.record["predictionRevision"], "another-output")
        self.metadata.save.assert_not_called()

    def test_raw_readiness_is_independent_of_viewer_and_current_job(
        self,
    ) -> None:
        model = Model(
            **{
                **self.record,
                "predictionAttrsUrl": None,
                "inferenceStatus": "Failed",
            }
        )
        self.assertTrue(raw_predictions_readiness(model)["ready"])
        self.assertFalse(results_readiness(model, self.layer)["ready"])
        model.predictedBuildingCount = 0
        self.assertFalse(raw_predictions_readiness(model)["ready"])

    def test_artifacts_reject_wrong_layer_and_stale_revision(self) -> None:
        for kind in (
            "gpkg",
            "prediction_attrs",
            "footprint_pmtiles",
            "sidecar",
            "geojson",
        ):
            with self.assertRaises(prediction_results.PredictionRequestError):
                self.processor.resolve_artifact(
                    ModelArtifactRequest(
                        projectId=PROJECT_ID,
                        imageLayerId=OTHER_LAYER,
                        modelId=MODEL_ID,
                        kind=kind,
                    )
                )
        with self.assertRaises(FileNotFoundError):
            self.processor.resolve_artifact(
                ModelArtifactRequest(
                    projectId=PROJECT_ID,
                    modelId=MODEL_ID,
                    kind="prediction_attrs",
                    predictionRevision="retired",
                )
            )

    def test_repeat_predictions_use_a_new_output_pair(self) -> None:
        self.processor.save_building_predictions(self.request())
        before = deepcopy(self.record)
        self.processor.save_building_predictions(self.request())
        self.assertNotEqual(self.record["gpkgUrl"], before["gpkgUrl"])
        self.assertNotEqual(
            self.record["predictionAttrsUrl"], before["predictionAttrsUrl"]
        )
        self.assertNotEqual(
            self.record["predictionRevision"], before["predictionRevision"]
        )
        self.assertTrue(self.storage.artifact_exists(before["gpkgUrl"]))

    def test_bad_uploaded_sidecar_never_replaces_model(self) -> None:
        before = deepcopy(self.record)

        def wrong_revision(*args: Any, **kwargs: Any) -> Any:
            output = self.write(*args, **kwargs)
            Path(output.attrs_path).write_text(json.dumps(attrs("incorrect")))
            return output

        self.writer.side_effect = wrong_revision
        with self.assertRaises(ValueError):
            self.processor.save_building_predictions(self.request())
        self.assertEqual(self.record, before)
        self.metadata.save.assert_not_called()

    def test_both_workflow_payloads_keep_the_existing_viewer_contract(
        self,
    ) -> None:
        for kind in ("embedding", "trained"):
            model = Model(**{**self.record, "modelType": kind})
            payload = build_visualizer(
                model,
                self.layer,
                Project(projectId=PROJECT_ID),
                LabelProject(),
                "/tiles/",
            )
            self.assertEqual(
                payload.flavor,
                "embedding" if kind == "embedding" else "inference",
            )
            self.assertEqual(payload.supportsThreshold, kind == "trained")
            self.assertEqual(payload.defaultThreshold, 0)
            self.assertEqual(payload.defaultUnknownThreshold, 0)
            self.assertEqual(payload.buildingCount, 2)
            self.assertTrue(payload.predictionsReady)
            self.assertTrue(
                payload.predictionAttrsUrl.startswith("/api/GetModelArtifact?")
            )
            if kind == "embedding":
                self.assertIsNone(payload.predictionsLayer)
