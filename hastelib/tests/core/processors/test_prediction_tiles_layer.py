# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for layer-only (model-less) prediction-tile preparation.

Footprint PMTiles are shared by every model on an image layer, so they
are built once — at layer-creation time, straight after imagery prep
caches the building footprints, when no model exists yet. In that mode
the job must build the tiles, skip the attribute sidecar entirely, and
keep all of its state on the ``ImageLayer``: there is no model document
to write to.

Storage, runner and queue are mocked; tippecanoe is never invoked here
(it only exists inside the training container the job is submitted to).
"""

import json
import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer, Model, TrainingJob

STATUSES = Config.get_status_types()
FOOTPRINTS_URL = "https://acct.blob/c/hash/building_footprints_p_l.gpkg?sas"


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": "layer-1",
        "projectId": "proj-1",
        "buildingFootprintsUrl": FOOTPRINTS_URL,
    }
    data.update(overrides)
    return ImageLayer(**data)


def _build_postprocessor(layer: ImageLayer):
    """Layer-only postprocessor: no model, mocked Azure dependencies."""
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

        return PredictionTilesPostprocessor(None, layer)


class TestLayerNeedsFootprintTiles(unittest.TestCase):
    def test_needed_once_footprints_exist(self):
        from hastegeo.core.processors.prediction_tiles import (
            layer_needs_footprint_tiles,
        )

        self.assertTrue(layer_needs_footprint_tiles(_layer()))

    def test_not_needed_without_footprints(self):
        from hastegeo.core.processors.prediction_tiles import (
            layer_needs_footprint_tiles,
        )

        layer = _layer(buildingFootprintsUrl=None)
        self.assertFalse(layer_needs_footprint_tiles(layer))

    def test_not_needed_when_tiles_already_exist(self):
        from hastegeo.core.processors.prediction_tiles import (
            layer_needs_footprint_tiles,
        )

        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        self.assertFalse(layer_needs_footprint_tiles(layer))


class TestLayerOnlyEnqueue(unittest.TestCase):
    def test_message_omits_the_model(self):
        from hastegeo.core.processors import prediction_tiles

        with patch.object(
            prediction_tiles, "AzureQueueHandler", autospec=True
        ) as handler:
            message = prediction_tiles.enqueue_prediction_tiles(
                project_id="proj-1",
                image_layer_id="layer-1",
                source_footprints_url=FOOTPRINTS_URL,
            )

        queue_name = Config().queue_config["prediction_edit_prep_queue_name"]
        self.assertEqual(handler.call_args.args[1], queue_name)
        handler.return_value.put_message.assert_called_once()
        # Same documented schema; an empty modelId selects layer-only.
        self.assertEqual(
            set(message),
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
        self.assertEqual(message["modelId"], "")
        self.assertEqual(message["sourceGpkgUrl"], "")
        self.assertEqual(message["imageLayerId"], "layer-1")
        self.assertEqual(message["sourceFootprintsUrl"], FOOTPRINTS_URL)


class TestLayerOnlySubmission(unittest.TestCase):
    def _submit(self, layer: ImageLayer):
        processor = _build_postprocessor(layer)
        processor.runner.add_task.return_value = ("job-1", "ptl-abc")
        processor.storage.get_file_remote_path.return_value = (
            "https://acct.blob/c/hash/prediction_tiles_config_l.json?sas"
        )
        return processor, processor.process()

    def test_state_lives_on_the_image_layer(self):
        layer = _layer(footprintTilesStatus=STATUSES.PENDING.value)
        processor, output = self._submit(layer)

        # The layer is the returned document — there is no model at all.
        self.assertIs(output, layer)
        self.assertIsNone(processor.model_data)
        self.assertEqual(
            output.footprintTilesStatus, STATUSES.IN_PROGRESS.value
        )
        self.assertEqual(output.footprintTilesJob.taskId, "ptl-abc")
        self.assertIsNone(output.footprintTilesJob.modelId)
        self.assertIn("ptl-abc", output.footprintTilesStatusMessage)

    def test_workflow_config_skips_the_sidecar(self):
        layer = _layer(footprintTilesStatus=STATUSES.PENDING.value)
        processor, _ = self._submit(layer)

        workflow_config = processor.storage.save.call_args.kwargs["data"]
        self.assertNotIn("model_id", workflow_config)
        self.assertTrue(workflow_config["tiles"]["build_pmtiles"])
        self.assertEqual(
            workflow_config["files"]["pmtiles"], "footprints_layer-1.pmtiles"
        )
        self.assertNotIn("attrs", workflow_config["files"])
        self.assertNotIn("predictions", workflow_config["files"])
        # The config is stored under the layer, not under some model.
        self.assertEqual(
            processor.storage.save.call_args.kwargs["identifier"], "layer-1"
        )

    def test_only_the_footprints_are_staged_for_the_task(self):
        layer = _layer(footprintTilesStatus=STATUSES.PENDING.value)
        processor, _ = self._submit(layer)

        kwargs = processor.runner.add_task.call_args.kwargs
        resource_files = kwargs["resource_files_for_upload"]
        self.assertEqual(set(resource_files), {"config", "footprints"})
        self.assertIn(
            "python -m hastegeo.workflows.prepare_prediction_tiles",
            kwargs["command"],
        )
        # tippecanoe only ships in the training image.
        self.assertEqual(
            kwargs["image_name"],
            Config().get_azure_batch_config()["docker_image"],
        )

    def test_poll_message_stays_layer_only(self):
        layer = _layer(footprintTilesStatus=STATUSES.PENDING.value)
        processor, _ = self._submit(layer)

        payload = json.loads(
            processor.queue_client.put_message.call_args.args[0]
        )
        self.assertEqual(payload["modelId"], "")
        self.assertEqual(payload["sourceGpkgUrl"], "")
        self.assertEqual(payload["imageLayerId"], "layer-1")

    def test_submission_failure_marks_the_layer_failed(self):
        layer = _layer(footprintTilesStatus=STATUSES.PENDING.value)
        processor = _build_postprocessor(layer)
        processor.storage.save.side_effect = RuntimeError("storage down")

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        self.assertIn("failed", output.footprintTilesStatusMessage.lower())

    def test_missing_footprints_fail_the_job(self):
        layer = _layer(
            buildingFootprintsUrl=None,
            footprintTilesStatus=STATUSES.PENDING.value,
        )
        processor = _build_postprocessor(layer)

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        processor.runner.add_task.assert_not_called()


class TestLayerOnlyCompletion(unittest.TestCase):
    def _completed_processor(self, manifest: dict):
        layer = _layer(
            footprintTilesStatus=STATUSES.IN_PROGRESS.value,
            footprintTilesJob=TrainingJob(
                jobId="job-1",
                taskId="ptl-abc",
                projectId="proj-1",
                status=STATUSES.IN_PROGRESS.value,
            ),
        )
        processor = _build_postprocessor(layer)
        processor.runner.get_task_status.return_value = (
            STATUSES.COMPLETED.value
        )

        def _file_content(job_id, task_id, filename):
            if filename.endswith(".json"):
                return json.dumps(manifest)
            return "2026-08-21T00:00:00+00:00|Building footprint vector tiles"

        processor.runner.get_filecontent_from_task.side_effect = _file_content
        return processor

    def test_tiles_url_lands_on_the_layer(self):
        processor = self._completed_processor(
            {
                "model_id": "",
                "pmtiles_built": True,
                "pmtiles_filename": "footprints_layer-1.pmtiles",
                "pmtiles_url": "https://acct/footprints_layer-1.pmtiles",
                "attrs_filename": "",
                "attrs_url": None,
                "building_count": 4242,
            }
        )

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.COMPLETED.value)
        self.assertEqual(
            output.footprintPmtilesUrl,
            "https://acct/footprints_layer-1.pmtiles",
        )
        self.assertIn("4242 buildings", output.footprintTilesStatusMessage)
        processor.runner.cleanup_task.assert_called_once()

    def test_no_model_document_is_touched(self):
        """A missing sidecar is expected here, not a failure."""
        processor = self._completed_processor(
            {
                "model_id": "",
                "pmtiles_built": True,
                "pmtiles_filename": "footprints_layer-1.pmtiles",
                "pmtiles_url": "https://acct/footprints_layer-1.pmtiles",
                "attrs_filename": "",
                "attrs_url": None,
                "building_count": 3,
            }
        )

        output = processor.process()

        self.assertIsNone(processor.model_data)
        self.assertIsInstance(output, ImageLayer)
        self.assertNotIsInstance(output, Model)

    def test_url_is_resolved_from_task_outputs_when_absent(self):
        processor = self._completed_processor(
            {
                "pmtiles_built": True,
                "pmtiles_filename": "footprints_layer-1.pmtiles",
                "pmtiles_url": None,
                "attrs_filename": "",
                "building_count": 9,
            }
        )
        processor.storage.get_file_remote_path.return_value = (
            "https://acct/hash/ptl-abc/footprints_layer-1.pmtiles?sas"
        )

        output = processor.process()

        self.assertEqual(
            output.footprintPmtilesUrl,
            "https://acct/hash/ptl-abc/footprints_layer-1.pmtiles?sas",
        )
        kwargs = processor.storage.get_file_remote_path.call_args.kwargs
        self.assertEqual(kwargs["extra_partition_keys"], "ptl-abc")

    def test_a_manifest_without_tiles_fails_the_job(self):
        """Tiles are the whole deliverable in layer-only mode."""
        processor = self._completed_processor(
            {
                "pmtiles_built": False,
                "pmtiles_filename": "",
                "pmtiles_url": None,
                "attrs_filename": "",
                "building_count": 0,
            }
        )

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        self.assertIsNone(output.footprintPmtilesUrl)

    def test_running_task_is_requeued(self):
        processor = self._completed_processor({})
        processor.runner.get_task_status.return_value = (
            STATUSES.IN_PROGRESS.value
        )

        output = processor.process()

        self.assertEqual(
            output.footprintTilesStatus, STATUSES.IN_PROGRESS.value
        )
        processor.queue_client.put_message.assert_called_once()
        processor.runner.cleanup_task.assert_not_called()

    def test_failed_task_is_reported_on_the_layer(self):
        processor = self._completed_processor({})
        processor.runner.get_task_status.return_value = STATUSES.FAILED.value

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        self.assertIn("failed", output.footprintTilesStatusMessage.lower())
        processor.runner.cleanup_task.assert_called_once()

    def test_missing_job_reference_fails_cleanly(self):
        layer = _layer(footprintTilesStatus=STATUSES.IN_PROGRESS.value)
        processor = _build_postprocessor(layer)

        output = processor.process()

        self.assertEqual(output.footprintTilesStatus, STATUSES.FAILED.value)
        processor.runner.get_task_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
