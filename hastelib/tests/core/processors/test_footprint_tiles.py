# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the layer footprint-tiles processor.

Covers the decisions that keep the job cheap and idempotent: whether a
layer needs tiling at all, and whether a request should actually reach
the queue. The container job itself is not exercised here — tippecanoe
runs only in the training image.
"""

import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer
from hastegeo.core.processors import footprint_tiles

STATUSES = Config.get_status_types()


def _layer(**overrides):
    data = {
        "projectId": "proj-1",
        "imageLayerId": "11111111-1111-1111-1111-111111111111",
        "buildingFootprintsUrl": "https://acct/footprints.gpkg?sas",
    }
    data.update(overrides)
    return ImageLayer(**data)


class TestLayerNeedsFootprintTiles(unittest.TestCase):
    def test_needs_tiles_once_footprints_are_cached(self):
        self.assertTrue(footprint_tiles.layer_needs_footprint_tiles(_layer()))

    def test_no_footprints_means_nothing_to_tile(self):
        self.assertFalse(
            footprint_tiles.layer_needs_footprint_tiles(
                _layer(buildingFootprintsUrl=None)
            )
        )

    def test_an_existing_archive_is_not_rebuilt(self):
        self.assertFalse(
            footprint_tiles.layer_needs_footprint_tiles(
                _layer(footprintPmtilesUrl="https://acct/footprints.pmtiles")
            )
        )


class TestArtifactName(unittest.TestCase):
    def test_archive_is_named_for_the_layer_not_a_model(self):
        # Keyed on the layer because every model on it shares the archive.
        self.assertEqual(
            footprint_tiles.pmtiles_artifact_name("layer-7"),
            "footprints_layer-7.pmtiles",
        )


class TestQueueMessage(unittest.TestCase):
    def test_message_carries_identifiers_only(self):
        message = footprint_tiles.build_tiles_message(
            project_id="p", image_layer_id="l", source_footprints_url="u"
        )
        self.assertEqual(
            message,
            {
                "projectId": "p",
                "imageLayerId": "l",
                "sourceFootprintsUrl": "u",
                "force": False,
            },
        )


class TestRequestPreparation(unittest.TestCase):
    """The HTTP/imagery-side seam: enqueue only when there is work."""

    def test_queues_when_the_layer_has_no_archive(self):
        layer = _layer()
        with patch.object(
            footprint_tiles, "enqueue_footprint_tiles"
        ) as enqueue:
            result = footprint_tiles.request_preparation(layer)

        enqueue.assert_called_once()
        self.assertTrue(result["queued"])
        self.assertFalse(result["tilesReady"])
        self.assertEqual(layer.footprintTilesStatus, STATUSES.PENDING.value)

    def test_is_a_no_op_when_the_archive_exists(self):
        layer = _layer(footprintPmtilesUrl="https://acct/f.pmtiles")
        with patch.object(
            footprint_tiles, "enqueue_footprint_tiles"
        ) as enqueue:
            result = footprint_tiles.request_preparation(layer)

        enqueue.assert_not_called()
        self.assertFalse(result["queued"])
        self.assertTrue(result["tilesReady"])
        self.assertEqual(layer.footprintTilesStatus, STATUSES.COMPLETED.value)

    def test_does_not_queue_a_second_job_while_one_is_in_flight(self):
        # Re-queueing would submit a duplicate container job for the same
        # archive.
        for status in (
            STATUSES.PENDING.value,
            STATUSES.IN_PROGRESS.value,
        ):
            layer = _layer(footprintTilesStatus=status)
            with patch.object(
                footprint_tiles, "enqueue_footprint_tiles"
            ) as enqueue:
                result = footprint_tiles.request_preparation(layer)

            enqueue.assert_not_called()
            self.assertFalse(result["queued"], status)

    def test_force_rebuilds_an_existing_archive(self):
        layer = _layer(footprintPmtilesUrl="https://acct/f.pmtiles")
        with patch.object(
            footprint_tiles, "enqueue_footprint_tiles"
        ) as enqueue:
            result = footprint_tiles.request_preparation(layer, force=True)

        enqueue.assert_called_once()
        self.assertTrue(result["queued"])

    def test_without_footprints_there_is_nothing_to_tile(self):
        layer = _layer(buildingFootprintsUrl=None)
        with patch.object(
            footprint_tiles, "enqueue_footprint_tiles"
        ) as enqueue:
            with self.assertRaises(ValueError):
                footprint_tiles.request_preparation(layer)

        enqueue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
