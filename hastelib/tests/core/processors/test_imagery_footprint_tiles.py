# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for footprint-tile scheduling at image-layer creation.

Building footprints are cached by the imageryprep workflow; the vector
tiles the prediction editor renders are built from them by a queued job
in the *training* image (the only one carrying tippecanoe). Kicking that
job off as soon as the layer completes means the editor never has to
wait for tiling later.

The rule this pins down:

* enqueue exactly once when the layer completes with footprints and no
  tiles yet;
* never enqueue when the tiles already exist, when there are no
  footprints, or when the footprint step reported an error;
* a queue failure is logged and swallowed — tiling is an optimisation,
  and the editor's own prep path rebuilds tiles on demand.

Runner, storage and queue are mocked; nothing here touches Azure.
"""

import json
import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer, ImageryPreprocessJob

STATUSES = Config.get_status_types()
FOOTPRINTS_FN = "building_footprints_proj-1_layer-9.gpkg"
FOOTPRINTS_URL = f"https://acct.blob/c/hash/img-123/{FOOTPRINTS_FN}?sas"


def _manifest(**overrides) -> dict:
    manifest = {
        "preview_pre_event_filenames": [],
        "preview_post_event_filenames": [],
        "pre_event_mosaic_filename": "",
        "pre_event_processed_filename": "",
        "post_event_mosaic_filename": "",
        "post_event_processed_filename": "",
        "normalization_means": [1.0],
        "normalization_stds": [2.0],
        "building_footprints_filename": FOOTPRINTS_FN,
        "building_footprints_error": "",
        "valid_area_mask_filename": "",
        "valid_area_mask_error": "",
    }
    manifest.update(overrides)
    return manifest


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": "layer-9",
        "projectId": "proj-1",
        "status": STATUSES.IN_PROGRESS.value,
        "preEventImageryUrls": ["https://example/pre.tif"],
        "postEventImageryUrls": ["https://example/post.tif"],
        "sourceTypePreEvent": "url",
        "sourceTypePostEvent": "url",
        "totalSteps": 4,
        "preprocessJob": ImageryPreprocessJob(
            jobId="job-1",
            taskId="img-123",
            imageLayerId="layer-9",
            projectId="proj-1",
            status=STATUSES.IN_PROGRESS.value,
        ),
    }
    data.update(overrides)
    return ImageLayer(**data)


def _build_processor(image_data: ImageLayer):
    with patch(
        "hastegeo.core.processors.imagery.UnifiedDataLayer", autospec=True
    ), patch(
        "hastegeo.core.processors.imagery.UnifiedRunner", autospec=True
    ), patch(
        "hastegeo.core.processors.imagery.AzureQueueHandler", autospec=True
    ):
        from hastegeo.core.processors.imagery import ImageryPostProcessor

        processor = ImageryPostProcessor(image_data=image_data)

    processor.runner.get_task_status.return_value = STATUSES.COMPLETED.value
    processor.storage.get_file_remote_path.return_value = FOOTPRINTS_URL
    return processor


def _complete(processor, manifest: dict):
    """Run process() through the COMPLETED branch with ``manifest``."""

    def _file_content(job_id, task_id, filename):
        if filename.endswith(".json"):
            return json.dumps(manifest)
        return ""

    processor.runner.get_filecontent_from_task.side_effect = _file_content
    with patch(
        "hastegeo.core.processors.imagery.enqueue_prediction_tiles",
        autospec=True,
    ) as enqueue:
        output = processor.process()
    return output, enqueue


class TestFootprintTilesAreQueuedAtLayerCreation(unittest.TestCase):
    def test_enqueued_once_when_footprints_exist_and_tiles_do_not(self):
        processor = _build_processor(_layer())

        output, enqueue = _complete(processor, _manifest())

        self.assertEqual(output.status, STATUSES.COMPLETED.value)
        self.assertEqual(output.buildingFootprintsUrl, FOOTPRINTS_URL)
        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs["project_id"], "proj-1")
        self.assertEqual(kwargs["image_layer_id"], "layer-9")
        self.assertEqual(kwargs["source_footprints_url"], FOOTPRINTS_URL)
        # No model exists yet: this is a layer-only request.
        self.assertNotIn("model_id", kwargs)
        self.assertNotIn("source_gpkg_url", kwargs)
        self.assertIs(kwargs["config"], processor.config)

    def test_not_enqueued_when_the_layer_already_has_tiles(self):
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        processor = _build_processor(layer)

        _, enqueue = _complete(processor, _manifest())

        enqueue.assert_not_called()

    def test_not_enqueued_when_the_footprint_step_failed(self):
        processor = _build_processor(_layer())

        output, enqueue = _complete(
            processor,
            _manifest(
                building_footprints_filename="",
                building_footprints_error="Overture download failed",
            ),
        )

        enqueue.assert_not_called()
        self.assertEqual(output.status, STATUSES.FAILED.value)

    def test_not_enqueued_without_footprints(self):
        processor = _build_processor(_layer())

        _, enqueue = _complete(
            processor, _manifest(building_footprints_filename="")
        )

        enqueue.assert_not_called()

    def test_not_enqueued_when_the_preprocess_task_failed(self):
        processor = _build_processor(_layer())
        processor.runner.get_task_status.return_value = STATUSES.FAILED.value
        processor.runner.get_filecontent_from_task.return_value = ""

        with patch(
            "hastegeo.core.processors.imagery.enqueue_prediction_tiles",
            autospec=True,
        ) as enqueue:
            output = processor.process()

        enqueue.assert_not_called()
        self.assertEqual(output.status, STATUSES.FAILED.value)

    def test_enqueue_failure_does_not_fail_imagery_prep(self):
        """Tiles are an optimisation; the layer must still complete."""
        processor = _build_processor(_layer())

        def _file_content(job_id, task_id, filename):
            if filename.endswith(".json"):
                return json.dumps(_manifest())
            return ""

        processor.runner.get_filecontent_from_task.side_effect = _file_content
        with patch(
            "hastegeo.core.processors.imagery.enqueue_prediction_tiles",
            autospec=True,
            side_effect=RuntimeError("queue unreachable"),
        ) as enqueue:
            output = processor.process()

        enqueue.assert_called_once()
        self.assertEqual(output.status, STATUSES.COMPLETED.value)
        self.assertEqual(output.buildingFootprintsUrl, FOOTPRINTS_URL)
        # The task is still cleaned up: the failure is fully contained.
        processor.runner.cleanup_task.assert_called_once()


class TestEnqueueGuard(unittest.TestCase):
    """Direct tests of the guard, independent of the state machine."""

    def _enqueue(self, layer: ImageLayer):
        processor = _build_processor(layer)
        with patch(
            "hastegeo.core.processors.imagery.enqueue_prediction_tiles",
            autospec=True,
        ) as enqueue:
            processor._enqueue_footprint_tiles()
        return enqueue

    def test_queues_for_a_layer_with_fresh_footprints(self):
        layer = _layer(buildingFootprintsUrl=FOOTPRINTS_URL)
        self._enqueue(layer).assert_called_once()

    def test_skips_a_layer_without_footprints(self):
        self._enqueue(_layer()).assert_not_called()

    def test_skips_a_layer_that_is_already_tiled(self):
        layer = _layer(
            buildingFootprintsUrl=FOOTPRINTS_URL,
            footprintPmtilesUrl="https://acct/tiles.pmtiles",
        )
        self._enqueue(layer).assert_not_called()


if __name__ == "__main__":
    unittest.main()
