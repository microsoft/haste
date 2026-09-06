# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
import unittest
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

import fiona
from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.prediction_results import (
    BuildingPredictionsRequest,
    ModelArtifactRequest,
    ResultsRequest,
)
from hastegeo.core.models.projects import (
    ImageLayer,
    LabelProject,
    Model,
    Project,
)
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.prediction_generations import (
    PredictionSupersededError,
)
from hastegeo.core.processors.prediction_results import (
    PredictionResultsProcessor,
)
from hastegeo.core.processors.visualizer import (
    VisualizerProcessor,
    build_visualizer,
)
from hastegeo.core.publishing.source import (
    PublishingSourceNotEligibleError,
    PublishingSourceResolver,
)
from hastegeo.core.utils.prediction_readiness import raw_predictions_readiness

PROJECT_ID = "123e4567-e89b-12d3-a456-426614174000"
LAYER_ID = "550e8400-e29b-41d4-a716-446655440000"
OTHER_LAYER = "550e8400-e29b-41d4-a716-446655440001"
MODEL_ID = "0042"


class ResultsTestCase(unittest.TestCase):
    """Real isolated filesystem metadata/artifacts; no Azure or Docker."""

    def setUp(self) -> None:
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = Config()
        self.config.storage_type = "local"
        self.config.storage_config = {
            "directory": os.path.join(self.directory, "metadata")
        }
        self.config.artifact_storage_type = "local"
        self.config.artifact_storage_config = {
            "directory": os.path.join(self.directory, "artifacts")
        }
        self.config.TEMP_DIR = self.directory
        self.storage = UnifiedArtifactStorage(
            storage_type="local",
            partition_key=PROJECT_ID,
            **self.config.artifact_storage_config,
        )
        footprints = self.storage.get_file_path("cached.gpkg")
        with fiona.open(
            footprints,
            "w",
            driver="GPKG",
            crs="EPSG:4326",
            schema={"geometry": "Polygon", "properties": {"id": "str"}},
        ) as output:
            for index in range(2):
                output.write(
                    {
                        "type": "Feature",
                        "properties": {"id": f"building-{index}"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    (index, 0),
                                    (index + 0.001, 0),
                                    (index + 0.001, 0.001),
                                    (index, 0.001),
                                    (index, 0),
                                ]
                            ],
                        },
                    }
                )
        self.layer = ImageLayer(
            imageLayerId=LAYER_ID,
            projectId=PROJECT_ID,
            buildingFootprintsUrl=self.storage.get_download_url(
                identifier="cached.gpkg"
            ),
            footprintPmtilesUrl="https://storage/footprints.pmtiles?sig=secret",
            preEventProcessedImageryUrl="https://storage/pre.tif?sig=secret",
            postEventProcessedImageryUrl="https://storage/post.tif?sig=secret",
            postEventMosaicCogImageryUrl="https://storage/raw.tif?sig=secret",
        )
        self.model = Model(
            modelId=MODEL_ID,
            projectId=PROJECT_ID,
            imageLayerId=LAYER_ID,
            name="Flood / São #1",
            modelType="embedding",
            status="Processed",
        )
        self.save_record("model", MODEL_ID, self.model.model_dump())
        self.save_record("imagelayer", LAYER_ID, self.layer.model_dump())
        self.save_record(
            "project",
            PROJECT_ID,
            Project(projectId=PROJECT_ID, name="Test project").model_dump(),
        )
        self.processor = PredictionResultsProcessor(self.config)
        self.repository = self.processor.repository

    def save_record(
        self, kind: str, key: str, value: dict, data_format: str = "json"
    ) -> None:
        MetadataProcessor(kind, PROJECT_ID, self.config).save(
            key, value, data_format
        )

    def request(self, **overrides: Any) -> BuildingPredictionsRequest:
        data = {
            "projectId": PROJECT_ID,
            "imageLayerId": LAYER_ID,
            "modelId": MODEL_ID,
            "predictions": [{"id": 0, "damaged": 1}, {"id": 1, "damaged": 0}],
        }
        data.update(overrides)
        return BuildingPredictionsRequest.model_validate(data)

    def current(self) -> Model:
        return self.repository.load(PROJECT_ID, MODEL_ID)

    def save_predictions(self, **overrides: Any) -> dict:
        return self.processor.save_building_predictions(
            self.request(**overrides)
        )


class TestInteractiveGenerations(ResultsTestCase):
    def test_save_publishes_verified_immutable_pair_and_readiness(
        self,
    ) -> None:
        response = self.save_predictions()
        model = self.current()
        self.assertTrue(response["predictionsReady"])
        self.assertEqual(response["count"], 2)
        self.assertEqual(
            model.predictionRevision, model.predictionReadyRevision
        )
        self.assertEqual(model.predictionState, "ready")
        self.assertIsNotNone(model.predictedAt)
        for key in ("gpkgUrl", "predictionAttrsUrl"):
            self.assertTrue(response[key].startswith("/api/GetModelArtifact?"))
            self.assertIn(model.predictionRevision, response[key])
        attrs = json.loads(
            self.storage.read_artifact_bytes(
                self.storage.resolve_artifact_path(model.predictionAttrsUrl),
                100_000,
            )
        )
        self.assertEqual(attrs["predictionRevision"], model.predictionRevision)
        self.assertEqual(attrs["flavor"], "embedding")
        self.assertEqual(attrs["overtureIds"], ["building-0", "building-1"])

    def test_repeat_save_creates_fresh_generation_and_rejects_old_url(
        self,
    ) -> None:
        self.save_predictions()
        old = self.current()
        self.save_predictions()
        new = self.current()
        self.assertNotEqual(old.predictionRevision, new.predictionRevision)
        self.assertNotEqual(old.gpkgUrl, new.gpkgUrl)
        self.assertNotEqual(old.predictionAttrsUrl, new.predictionAttrsUrl)
        self.assertTrue(self.storage.artifact_exists(old.gpkgUrl))
        with self.assertRaises(FileNotFoundError):
            self.processor.resolve_artifact(
                ModelArtifactRequest(
                    projectId=PROJECT_ID,
                    modelId=MODEL_ID,
                    kind="prediction_attrs",
                    predictionRevision=old.predictionRevision,
                )
            )

    def test_clear_needs_no_footprints_and_cannot_be_restored_by_stale_model(
        self,
    ) -> None:
        self.save_predictions()
        stale = self.current()
        self.save_record(
            "imagelayer", LAYER_ID, {"buildingFootprintsUrl": None}
        )
        with patch(
            "hastegeo.core.processors.prediction_results.write_building_predictions"
        ) as writer, patch.object(
            UnifiedArtifactStorage, "fetch_artifact"
        ) as fetch:
            response = self.save_predictions(predictions=[])
        writer.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(response["buildingCount"], 0)
        self.assertFalse(response["predictionsReady"])
        self.save_record("model", MODEL_ID, stale.model_dump())
        current = self.current()
        self.assertEqual(current.predictedBuildingCount, 0)
        self.assertIsNone(current.gpkgUrl)
        self.assertIsNone(current.predictionAttrsUrl)
        self.assertFalse(raw_predictions_readiness(current)["ready"])

    def test_invalid_nonempty_predictions_preserve_good_generation(
        self,
    ) -> None:
        self.save_predictions()
        original = self.current().model_dump()
        for predictions in (
            [{"id": 99, "damaged": 1}],
            [{"id": 0, "damaged": 1}],
            [
                {"id": 0, "damaged": 1, "overtureId": "wrong"},
                {"id": 1, "damaged": 0},
            ],
        ):
            with self.assertRaises(ValueError):
                self.save_predictions(predictions=predictions)
            self.assertEqual(self.current().model_dump(), original)

    def test_second_upload_failure_does_not_reuse_old_ready_sidecar(
        self,
    ) -> None:
        self.save_predictions()
        old = self.current()
        original = UnifiedArtifactStorage.store_artifact

        def fail_attrs(storage: UnifiedArtifactStorage, **kwargs: Any) -> str:
            if kwargs["artifact_name"].endswith(".json"):
                raise RuntimeError("upload failed")
            return original(storage, **kwargs)

        with patch.object(
            UnifiedArtifactStorage, "store_artifact", fail_attrs
        ):
            with self.assertRaises(RuntimeError):
                self.save_predictions()
        failed = self.current()
        self.assertEqual(failed.predictionState, "failed")
        self.assertNotEqual(failed.predictionRevision, old.predictionRevision)
        self.assertIsNone(failed.predictionAttrsUrl)
        self.assertIsNone(failed.gpkgUrl)
        self.assertFalse(raw_predictions_readiness(failed)["ready"])

    def test_superseded_upload_cannot_replace_newer_results(self) -> None:
        original = UnifiedArtifactStorage.store_artifact
        newer = {}

        def supersede(storage: UnifiedArtifactStorage, **kwargs: Any) -> str:
            if not newer:
                newer["started"] = True
                newer["response"] = self.save_predictions()
            return original(storage, **kwargs)

        with patch.object(UnifiedArtifactStorage, "store_artifact", supersede):
            with self.assertRaises(PredictionSupersededError):
                self.save_predictions()
        self.assertEqual(
            self.current().predictionRevision,
            newer["response"]["predictionRevision"],
        )
        self.assertTrue(raw_predictions_readiness(self.current())["ready"])

    def test_every_model_bound_artifact_rejects_another_layer(self) -> None:
        for kind in (
            "gpkg",
            "prediction_attrs",
            "sidecar",
            "geojson",
            "footprint_pmtiles",
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.processor.resolve_artifact(
                        ModelArtifactRequest(
                            projectId=PROJECT_ID,
                            modelId=MODEL_ID,
                            imageLayerId=OTHER_LAYER,
                            kind=kind,
                        )
                    )

    def test_clear_during_validation_supersedes_the_unpublished_request(
        self,
    ) -> None:
        from hastegeo.core.processors.building_predictions import (
            write_building_predictions,
        )

        self.save_predictions()

        def validate_then_clear(*args: Any, **kwargs: Any) -> Any:
            artifacts = write_building_predictions(*args, **kwargs)
            self.save_predictions(predictions=[])
            return artifacts

        with patch(
            "hastegeo.core.processors.prediction_results.write_building_predictions",
            side_effect=validate_then_clear,
        ):
            with self.assertRaises(PredictionSupersededError):
                self.save_predictions()
        self.assertEqual(self.current().predictedBuildingCount, 0)
        self.assertIsNone(self.current().gpkgUrl)

    def test_clear_is_not_publishable_even_with_an_old_valid_gpkg(
        self,
    ) -> None:
        self.save_predictions()
        self.save_predictions(predictions=[])
        with self.assertRaises(PublishingSourceNotEligibleError):
            PublishingSourceResolver(config=self.config)._load_source(
                PROJECT_ID, LAYER_ID, MODEL_ID
            )


class TestCommonVisualizer(ResultsTestCase):
    def test_missing_tiles_blocks_rendering_but_not_raw_readiness(
        self,
    ) -> None:
        self.save_predictions()
        self.save_record("imagelayer", LAYER_ID, {"footprintPmtilesUrl": None})
        row = self.processor.list_models(PROJECT_ID, LAYER_ID)[0]
        self.assertTrue(row["rawPredictionsReady"])
        self.assertFalse(row["predictionsReady"])
        self.assertEqual(
            row["predictionsReadiness"]["reason"], "missing_footprint_tiles"
        )
        url, _ = self.processor.resolve_artifact(
            ModelArtifactRequest(
                projectId=PROJECT_ID, modelId=MODEL_ID, kind="gpkg"
            )
        )
        self.assertEqual(url, self.current().gpkgUrl)

    def test_embedding_payload_is_read_only_and_has_no_fake_rasters(
        self,
    ) -> None:
        self.save_predictions()
        request = ResultsRequest(
            projectId=PROJECT_ID, imageLayerId=LAYER_ID, modelId=MODEL_ID
        )
        with patch(
            "hastegeo.core.utils.queues.AzureQueueHandler.put_message"
        ) as queue:
            result = VisualizerProcessor(self.config).load(request)
            rows = self.processor.list_models(PROJECT_ID, LAYER_ID)
        queue.assert_not_called()
        self.assertEqual(result.flavor, "embedding")
        self.assertFalse(result.supportsThreshold)
        self.assertIsNone(result.predictedDamageLayer)
        self.assertIsNone(result.predictionsLayer)
        self.assertEqual(result.defaultThreshold, 0)
        self.assertEqual(result.defaultUnknownThreshold, 0)
        self.assertEqual(result.buildingCount, 2)
        self.assertTrue(result.predictionsReady)
        self.assertTrue(rows[0]["predictionsReady"])
        self.assertTrue(result.footprintTilesUrl.startswith("/api/"))

    def test_standard_flavor_is_not_inferred_from_binary_scores(self) -> None:
        self.model.modelType = "trained"
        self.model.inferenceStatus = "Processed"
        self.model.gpkgUrl = "https://storage/raw.gpkg"
        self.model.predictedDamageLayerUrl = (
            "https://storage/result_visualizer.tif"
        )
        result = build_visualizer(
            self.model,
            self.layer,
            Project(projectId=PROJECT_ID),
            LabelProject(),
            "https://titiler/",
        )
        self.assertEqual(result.flavor, "inference")
        self.assertTrue(result.supportsThreshold)
        self.assertIsNotNone(result.predictionsLayer)
        self.assertIsNotNone(result.predictedDamageLayer)
        self.assertTrue(result.rawPredictionsReady)
        self.assertFalse(result.predictionsReady)
        self.assertEqual(
            result.predictionsReadiness["reason"], "missing_attributes"
        )
        self.assertTrue(result.gpkgUrl.startswith("/api/"))

    def test_zero_count_is_preserved(self) -> None:
        self.save_predictions(predictions=[])
        result = self.processor.list_models(PROJECT_ID, LAYER_ID)[0]
        self.assertEqual(result["buildingCount"], 0)
        self.assertFalse(result["predictionsReady"])
