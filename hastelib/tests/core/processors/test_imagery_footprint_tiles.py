# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""The imagery processor queues footprint tiling once footprints exist.

Footprint geometry belongs to the image layer, so the archive is built
when imagery prep caches the footprints rather than per model. These
tests pin the two things that matter: it happens for both workflow types,
and a queue failure never takes the image layer down with it.
"""

import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.processors import imagery

STATUSES = Config.get_status_types()


def _processor(image_data):
    """An ImageryPostProcessor with only the fields the hook reads."""
    processor = MagicMock(spec=imagery.ImageryPostProcessor)
    processor.image_data = image_data
    processor.config = Config()
    processor.logger = MagicMock()
    # Bind the real method so the mock exercises production logic.
    processor._enqueue_footprint_tiles = (
        imagery.ImageryPostProcessor._enqueue_footprint_tiles.__get__(
            processor
        )
    )
    return processor


def _layer(**overrides):
    data = {
        "projectId": "proj-1",
        "imageLayerId": "22222222-2222-2222-2222-222222222222",
        "buildingFootprintsUrl": "https://acct/footprints.gpkg?sas",
    }
    data.update(overrides)
    return ImageLayer(**data)


class TestEnqueueFootprintTiles(unittest.TestCase):
    def test_queues_for_the_standard_workflow(self):
        layer = _layer(workflowType="standard")
        processor = _processor(layer)
        with patch.object(imagery, "enqueue_footprint_tiles") as enqueue:
            processor._enqueue_footprint_tiles()

        enqueue.assert_called_once()
        self.assertEqual(
            enqueue.call_args.kwargs["image_layer_id"], layer.imageLayerId
        )
        self.assertEqual(layer.footprintTilesStatus, STATUSES.PENDING.value)

    def test_queues_for_the_building_workflow(self):
        # The embedding job no longer tiles, so this layer type depends on
        # the same archive as every other.
        layer = _layer(workflowType="building")
        processor = _processor(layer)
        with patch.object(imagery, "enqueue_footprint_tiles") as enqueue:
            processor._enqueue_footprint_tiles()

        enqueue.assert_called_once()
        self.assertEqual(layer.footprintTilesStatus, STATUSES.PENDING.value)

    def test_skips_when_the_layer_has_no_footprints(self):
        layer = _layer(buildingFootprintsUrl=None)
        processor = _processor(layer)
        with patch.object(imagery, "enqueue_footprint_tiles") as enqueue:
            processor._enqueue_footprint_tiles()

        enqueue.assert_not_called()
        self.assertIsNone(layer.footprintTilesStatus)

    def test_skips_when_the_archive_already_exists(self):
        layer = _layer(footprintPmtilesUrl="https://acct/f.pmtiles")
        processor = _processor(layer)
        with patch.object(imagery, "enqueue_footprint_tiles") as enqueue:
            processor._enqueue_footprint_tiles()

        enqueue.assert_not_called()

    def test_a_queue_failure_does_not_fail_the_layer(self):
        # The tiles are derived data. An unreachable queue must leave the
        # imagery perfectly usable.
        layer = _layer(status=STATUSES.COMPLETED.value)
        processor = _processor(layer)
        with patch.object(
            imagery,
            "enqueue_footprint_tiles",
            side_effect=RuntimeError("queue unreachable"),
        ):
            processor._enqueue_footprint_tiles()

        self.assertEqual(layer.status, STATUSES.COMPLETED.value)
        processor.logger.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
