# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the prediction-tiles HTTP request seam.

``request_preparation`` is what ``PutPreparePredictionTilesQueueMessage``
delegates to: it decides whether the footprint PMTiles and/or the
attribute sidecar still have to be built, enqueues at most one job, and
reports the state the editor polls for. The queue is mocked — no Azure
and no tippecanoe are touched.
"""

import json
import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ImageLayer, Model

STATUSES = Config.get_status_types()

PMTILES_URL = "https://acct.blob/c/hash/footprints_layer-1.pmtiles?sas"
ATTRS_URL = "https://acct.blob/c/hash/prediction_attrs_model-1.json?sas"


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


def _request(model: Model, layer: ImageLayer, force: bool = False):
    """Call the seam with the prep queue mocked out.

    Returns ``(result, queue_handler_mock)`` so callers can assert both
    on the response payload and on what was (not) enqueued.
    """
    from hastegeo.core.processors import prediction_tiles

    with patch.object(
        prediction_tiles, "AzureQueueHandler", autospec=True
    ) as handler:
        result = prediction_tiles.request_preparation(
            model, layer, force=force
        )
    return result, handler


class TestRequestPreparation(unittest.TestCase):
    def test_queues_when_nothing_is_prepared(self):
        model = _model()

        result, handler = _request(model, _layer())

        self.assertTrue(result["queued"])
        self.assertFalse(result["tilesReady"])
        self.assertFalse(result["attrsReady"])
        self.assertEqual(result["modelId"], "model-1")
        self.assertEqual(result["status"], STATUSES.PENDING.value)
        self.assertIn(
            "Queued for prediction tile preparation", result["statusMessage"]
        )
        # The model is mutated in place for the caller to persist.
        self.assertEqual(model.predictionTilesStatus, STATUSES.PENDING.value)

        handler.return_value.put_message.assert_called_once()
        payload = json.loads(
            handler.return_value.put_message.call_args.args[0]
        )
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
        self.assertEqual(payload["projectId"], "proj-1")
        self.assertEqual(payload["imageLayerId"], "layer-1")
        self.assertEqual(payload["modelId"], "model-1")
        self.assertEqual(payload["sourceGpkgUrl"], _model().gpkgUrl)
        self.assertEqual(
            payload["sourceFootprintsUrl"], _layer().buildingFootprintsUrl
        )
        self.assertFalse(payload["force"])

    def test_uses_the_prediction_edit_prep_queue(self):
        _, handler = _request(_model(), _layer())

        queue_name = Config().queue_config["prediction_edit_prep_queue_name"]
        self.assertEqual(handler.call_args.args[1], queue_name)

    def test_skips_when_both_artifacts_exist(self):
        model = _model(predictionAttrsUrl=ATTRS_URL)
        layer = _layer(footprintPmtilesUrl=PMTILES_URL)

        result, handler = _request(model, layer)

        self.assertFalse(result["queued"])
        self.assertTrue(result["tilesReady"])
        self.assertTrue(result["attrsReady"])
        self.assertEqual(result["status"], STATUSES.COMPLETED.value)
        handler.return_value.put_message.assert_not_called()

    def test_repeat_request_on_a_ready_model_is_a_no_op(self):
        # The editor may ask on every open; the status message must not
        # grow a line per visit.
        model = _model(
            predictionAttrsUrl=ATTRS_URL,
            predictionTilesStatus=STATUSES.COMPLETED.value,
            predictionTilesStatusMessage=(
                "\n2026-01-01: Prediction tiles already available"
            ),
        )
        layer = _layer(footprintPmtilesUrl=PMTILES_URL)

        result, handler = _request(model, layer)

        self.assertFalse(result["queued"])
        self.assertEqual(
            model.predictionTilesStatusMessage,
            "\n2026-01-01: Prediction tiles already available",
        )
        handler.return_value.put_message.assert_not_called()

    def test_force_rebuilds_ready_artifacts(self):
        model = _model(predictionAttrsUrl=ATTRS_URL)
        layer = _layer(footprintPmtilesUrl=PMTILES_URL)

        result, handler = _request(model, layer, force=True)

        self.assertTrue(result["queued"])
        self.assertEqual(result["status"], STATUSES.PENDING.value)
        handler.return_value.put_message.assert_called_once()
        payload = json.loads(
            handler.return_value.put_message.call_args.args[0]
        )
        self.assertTrue(payload["force"])

    def test_queues_when_only_the_sidecar_is_missing(self):
        # Footprint tiles are shared by every model on a layer, so a
        # second model on a prepared layer still needs its own sidecar.
        layer = _layer(footprintPmtilesUrl=PMTILES_URL)

        result, handler = _request(_model(), layer)

        self.assertTrue(result["queued"])
        self.assertTrue(result["tilesReady"])
        self.assertFalse(result["attrsReady"])
        handler.return_value.put_message.assert_called_once()

    def test_does_not_requeue_an_in_flight_job(self):
        # A second PUT while the Batch task runs must not submit a
        # duplicate job; the caller just polls the status it gets back.
        model = _model(
            predictionTilesStatus=STATUSES.IN_PROGRESS.value,
            predictionTilesStatusMessage="\n2026-01-01: Submitted",
        )

        result, handler = _request(model, _layer())

        self.assertFalse(result["queued"])
        self.assertEqual(result["status"], STATUSES.IN_PROGRESS.value)
        self.assertIn("Submitted", result["statusMessage"])
        handler.return_value.put_message.assert_not_called()

    def test_does_not_requeue_a_pending_job(self):
        model = _model(predictionTilesStatus=STATUSES.PENDING.value)

        result, handler = _request(model, _layer())

        self.assertFalse(result["queued"])
        self.assertEqual(result["status"], STATUSES.PENDING.value)
        handler.return_value.put_message.assert_not_called()

    def test_force_overrides_an_in_flight_job(self):
        model = _model(predictionTilesStatus=STATUSES.IN_PROGRESS.value)

        result, handler = _request(model, _layer(), force=True)

        self.assertTrue(result["queued"])
        self.assertEqual(result["status"], STATUSES.PENDING.value)
        handler.return_value.put_message.assert_called_once()

    def test_retries_a_failed_job(self):
        model = _model(predictionTilesStatus=STATUSES.FAILED.value)

        result, handler = _request(model, _layer())

        self.assertTrue(result["queued"])
        self.assertEqual(result["status"], STATUSES.PENDING.value)
        handler.return_value.put_message.assert_called_once()

    def test_requires_predictions(self):
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesUnavailableError,
        )

        with self.assertRaises(PredictionTilesUnavailableError):
            _request(_model(gpkgUrl=None), _layer())

    def test_requires_building_footprints(self):
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesUnavailableError,
        )

        with self.assertRaises(PredictionTilesUnavailableError):
            _request(_model(), _layer(buildingFootprintsUrl=None))

    def test_unavailable_error_is_a_value_error(self):
        # The HTTP layer maps it to 404; keeping it a ValueError means an
        # older caller's `except ValueError` still behaves.
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesUnavailableError,
        )

        self.assertTrue(
            issubclass(PredictionTilesUnavailableError, ValueError)
        )


if __name__ == "__main__":
    unittest.main()
