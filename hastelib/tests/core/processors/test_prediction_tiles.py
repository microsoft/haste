# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the prediction-tiles processor.

The processor is pure orchestration: it decides whether the footprint
tiles and/or the attribute sidecar still have to be built, submits the
job to the *training* container through the unified runner (tippecanoe
ships only there), and writes the resulting URLs back onto the model and
its image layer. Storage, runner and queue are mocked — no Azure, no
Batch and no tippecanoe are touched.
"""

import json
import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer, Model, TrainingJob

STATUSES = Config.get_status_types()


def _model(**overrides) -> Model:
    data = {
        "modelId": "model-1",
        "projectId": "proj-1",
        "imageLayerId": "layer-1",
        "name": "test model",
        "gpkgUrl": "https://acct.blob/c/hash/predicted_damage_m.gpkg?sas",
    }
    data.update(overrides)
    return Model(**data)


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": "layer-1",
        "projectId": "proj-1",
        "buildingFootprintsUrl": (
            "https://acct.blob/c/hash/building_footprints_p_l.gpkg?sas"
        ),
    }
    data.update(overrides)
    return ImageLayer(**data)


def _build_preprocessor(model: Model, layer: ImageLayer):
    with patch(
        "hastegeo.core.processors.prediction_tiles.AzureQueueHandler",
        autospec=True,
    ):
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesPreprocessor,
        )

        return PredictionTilesPreprocessor(model, layer)


def _build_postprocessor(model: Model, layer: ImageLayer):
    with patch(
        "hastegeo.core.processors.prediction_tiles.UnifiedDataLayer",
        autospec=True,
    ), patch(
        "hastegeo.core.processors.prediction_tiles.UnifiedRunner",
        autospec=True,
    ), patch(
        "hastegeo.core.processors.prediction_tiles.AzureQueueHandler",
        autospec=True,
    ):
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesPostprocessor,
        )

        return PredictionTilesPostprocessor(model, layer)


class TestNeedsPreparation(unittest.TestCase):
    def test_everything_needed_when_nothing_exists(self):
        from hastegeo.core.processors.prediction_tiles import needs_preparation

        needs_pmtiles, needs_attrs = needs_preparation(_model(), _layer())
        self.assertTrue(needs_pmtiles)
        self.assertTrue(needs_attrs)

    def test_tiles_are_reused_across_models_on_a_layer(self):
        from hastegeo.core.processors.prediction_tiles import needs_preparation

        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        needs_pmtiles, needs_attrs = needs_preparation(_model(), layer)
        self.assertFalse(needs_pmtiles)
        self.assertTrue(needs_attrs)

    def test_embedding_model_pmtiles_are_reused(self):
        """The embedding workflow already tiles the same footprints.

        Rebuilding them would spawn a multi-gigabyte container job to
        produce a byte-for-byte equivalent archive.
        """
        from hastegeo.core.processors.prediction_tiles import needs_preparation

        model = _model(pmtilesUrl="https://acct/buildings_5553.pmtiles")
        needs_pmtiles, needs_attrs = needs_preparation(model, _layer())
        self.assertFalse(needs_pmtiles)
        self.assertTrue(needs_attrs)

    def test_resolve_tiles_url_prefers_the_model_archive(self):
        from hastegeo.core.processors.prediction_tiles import resolve_tiles_url

        model = _model(pmtilesUrl="https://acct/model.pmtiles")
        layer = _layer(footprintPmtilesUrl="https://acct/layer.pmtiles")
        self.assertEqual(
            resolve_tiles_url(model, layer), "https://acct/model.pmtiles"
        )
        self.assertEqual(
            resolve_tiles_url(_model(), layer), "https://acct/layer.pmtiles"
        )
        self.assertIsNone(resolve_tiles_url(_model(), _layer()))


class TestPreprocessor(unittest.TestCase):
    def test_enqueues_when_work_is_outstanding(self):
        model = _model()
        preprocessor = _build_preprocessor(model, _layer())

        output = preprocessor.queue_for_processing()

        self.assertEqual(output.predictionTilesStatus, STATUSES.PENDING.value)
        preprocessor.queue_client.put_message.assert_called_once()
        payload = json.loads(
            preprocessor.queue_client.put_message.call_args.args[0]
        )
        self.assertEqual(payload["modelId"], "model-1")
        # Documented prediction-edit-prep-queue message schema.
        self.assertEqual(
            set(payload),
            {
                "projectId",
                "imageLayerId",
                "modelId",
                "sourceGpkgUrl",
                "sourceFootprintsUrl",
                "force",
                "backfillVersions",
            },
        )
        self.assertEqual(payload["imageLayerId"], "layer-1")
        self.assertEqual(payload["sourceGpkgUrl"], _model().gpkgUrl)
        self.assertEqual(
            payload["sourceFootprintsUrl"],
            _layer().buildingFootprintsUrl,
        )
        self.assertFalse(payload["force"])

    def test_enqueue_helper_uses_the_prep_queue(self):
        from hastegeo.core.processors import prediction_tiles

        with patch.object(
            prediction_tiles, "AzureQueueHandler", autospec=True
        ) as handler:
            message = prediction_tiles.enqueue_prediction_tiles(
                project_id="proj-1",
                image_layer_id="layer-1",
                model_id="model-1",
                force=True,
            )

        queue_name = Config().queue_config["prediction_edit_prep_queue_name"]
        self.assertEqual(handler.call_args.args[1], queue_name)
        self.assertTrue(message["force"])
        handler.return_value.put_message.assert_called_once()

    def test_skips_when_both_artifacts_exist(self):
        model = _model(predictionAttrsUrl="https://acct/attrs.json")
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        preprocessor = _build_preprocessor(model, layer)

        output = preprocessor.queue_for_processing()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )
        preprocessor.queue_client.put_message.assert_not_called()

    def test_force_rebuilds_existing_artifacts(self):
        model = _model(predictionAttrsUrl="https://acct/attrs.json")
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        preprocessor = _build_preprocessor(model, layer)

        output = preprocessor.queue_for_processing(force=True)

        self.assertEqual(output.predictionTilesStatus, STATUSES.PENDING.value)
        preprocessor.queue_client.put_message.assert_called_once()

    def test_requires_predictions(self):
        preprocessor = _build_preprocessor(_model(gpkgUrl=None), _layer())
        with self.assertRaises(ValueError):
            preprocessor.queue_for_processing()

    def test_requires_building_footprints(self):
        preprocessor = _build_preprocessor(
            _model(), _layer(buildingFootprintsUrl=None)
        )
        with self.assertRaises(ValueError):
            preprocessor.queue_for_processing()


class TestPostprocessorSubmission(unittest.TestCase):
    def test_submits_to_the_training_image(self):
        model = _model(
            predictionTilesStatus=STATUSES.PENDING.value,
        )
        processor = _build_postprocessor(model, _layer())
        processor.runner.add_task.return_value = ("job-1", "ptl-abc")
        processor.storage.get_file_remote_path.return_value = (
            "https://acct.blob/c/hash/prediction_tiles_config_m.json?sas"
        )

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.IN_PROGRESS.value
        )
        self.assertEqual(output.predictionTilesJob.taskId, "ptl-abc")
        kwargs = processor.runner.add_task.call_args.kwargs
        self.assertIn(
            "python -m hastegeo.workflows.prepare_prediction_tiles",
            kwargs["command"],
        )
        # The training image is the only one carrying tippecanoe.
        self.assertEqual(
            kwargs["image_name"],
            Config().get_azure_batch_config()["docker_image"],
        )
        self.assertIn("footprints", kwargs["resource_files_for_upload"])
        self.assertIn("predictions", kwargs["resource_files_for_upload"])
        # Re-enqueued so the next poll advances the state machine.
        processor.queue_client.put_message.assert_called_once()

    def test_submission_failure_marks_the_model_failed(self):
        model = _model(predictionTilesStatus=STATUSES.PENDING.value)
        processor = _build_postprocessor(model, _layer())
        processor.storage.save.side_effect = RuntimeError("storage down")

        output = processor.process()

        self.assertEqual(output.predictionTilesStatus, STATUSES.FAILED.value)
        self.assertIn("failed", output.predictionTilesStatusMessage.lower())

    def test_config_skips_tiles_when_the_layer_has_them(self):
        model = _model(predictionTilesStatus=STATUSES.PENDING.value)
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        processor = _build_postprocessor(model, layer)
        processor.runner.add_task.return_value = ("job-1", "ptl-abc")
        processor.storage.get_file_remote_path.return_value = (
            "https://acct.blob/c/hash/prediction_tiles_config_m.json?sas"
        )

        processor.process()

        workflow_config = processor.storage.save.call_args.kwargs["data"]
        self.assertFalse(workflow_config["tiles"]["build_pmtiles"])
        self.assertEqual(
            workflow_config["files"]["attrs"],
            "prediction_attrs_model-1.json",
        )
        self.assertEqual(
            workflow_config["files"]["pmtiles"],
            "footprints_layer-1.pmtiles",
        )


class TestPostprocessorCompletion(unittest.TestCase):
    def _completed_processor(self, manifest: dict):
        model = _model(
            predictionTilesStatus=STATUSES.IN_PROGRESS.value,
            predictionTilesJob=TrainingJob(
                jobId="job-1",
                taskId="ptl-abc",
                modelId="model-1",
                projectId="proj-1",
                status=STATUSES.IN_PROGRESS.value,
            ),
        )
        processor = _build_postprocessor(model, _layer())
        processor.runner.get_task_status.return_value = (
            STATUSES.COMPLETED.value
        )

        def _file_content(job_id, task_id, filename):
            if filename.endswith(".json"):
                return json.dumps(manifest)
            return "2026-08-21T00:00:00+00:00|Building prediction attributes"

        processor.runner.get_filecontent_from_task.side_effect = _file_content
        return processor

    def test_persists_urls_counts_and_timestamp(self):
        processor = self._completed_processor(
            {
                "pmtiles_built": True,
                "pmtiles_filename": "footprints_layer-1.pmtiles",
                "pmtiles_url": "https://acct/footprints_layer-1.pmtiles",
                "attrs_filename": "prediction_attrs_model-1.json",
                "attrs_url": "https://acct/prediction_attrs_model-1.json",
                "building_count": 1234,
            }
        )

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )
        self.assertEqual(
            output.predictionAttrsUrl,
            "https://acct/prediction_attrs_model-1.json",
        )
        self.assertEqual(output.predictedBuildingCount, 1234)
        self.assertTrue(output.predictedAt)
        # Tiles belong to the layer, not the model.
        self.assertEqual(
            processor.image_layer.footprintPmtilesUrl,
            "https://acct/footprints_layer-1.pmtiles",
        )
        processor.runner.cleanup_task.assert_called_once()

    def test_resolves_urls_from_task_outputs_when_manifest_has_none(self):
        processor = self._completed_processor(
            {
                "pmtiles_built": False,
                "pmtiles_filename": "",
                "pmtiles_url": None,
                "attrs_filename": "prediction_attrs_model-1.json",
                "attrs_url": None,
                "building_count": 7,
            }
        )
        processor.storage.get_file_remote_path.return_value = (
            "https://acct/hash/ptl-abc/prediction_attrs_model-1.json?sas"
        )

        output = processor.process()

        self.assertEqual(
            output.predictionAttrsUrl,
            "https://acct/hash/ptl-abc/prediction_attrs_model-1.json?sas",
        )
        # No tiles were built, so the layer keeps its (empty) value.
        self.assertIsNone(processor.image_layer.footprintPmtilesUrl)

    def test_missing_manifest_fails_the_job(self):
        processor = self._completed_processor({})
        processor.runner.get_filecontent_from_task.side_effect = None
        processor.runner.get_filecontent_from_task.return_value = None

        output = processor.process()

        self.assertEqual(output.predictionTilesStatus, STATUSES.FAILED.value)

    def test_running_task_is_requeued(self):
        processor = self._completed_processor({})
        processor.runner.get_task_status.return_value = (
            STATUSES.IN_PROGRESS.value
        )

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.IN_PROGRESS.value
        )
        processor.queue_client.put_message.assert_called_once()
        processor.runner.cleanup_task.assert_not_called()

    def test_failed_task_is_reported(self):
        processor = self._completed_processor({})
        processor.runner.get_task_status.return_value = STATUSES.FAILED.value

        output = processor.process()

        self.assertEqual(output.predictionTilesStatus, STATUSES.FAILED.value)
        processor.runner.cleanup_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
