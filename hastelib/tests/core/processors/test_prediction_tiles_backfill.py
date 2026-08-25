# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Tests for backfilling per-version prediction attribute sidecars.

Versions saved before per-version sidecars existed have a GeoPackage but
no sidecar, so the map cannot draw them. The prediction-tiles job grew a
backfill mode that rebuilds those. The property that matters is
**idempotency**: the version list is derived from the model document at
submit time, never from the queue message, so a version that already has
a sidecar is never rebuilt and a re-run of a completed job is a no-op.
"""

import json
import unittest
from unittest.mock import patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import (
    EditedPredictionVersion,
    ImageLayer,
    Model,
    TrainingJob,
)
from hastegeo.core.utils.metadata import MetadataUtils

STATUSES = Config.get_status_types()
# Task input filenames are extracted from the blob path, which is
# partitioned by the project hash — so the fixtures use the real one.
PARTITION = MetadataUtils.hash_string("proj-1")
RAW_URL = f"https://acct.blob/c/{PARTITION}/predicted_damage_m.gpkg?sas"
FOOTPRINTS_URL = (
    f"https://acct.blob/c/{PARTITION}/building_footprints_p_l.gpkg?sas"
)


def _version(version: int, attrs: str = None) -> EditedPredictionVersion:
    return EditedPredictionVersion(
        version=version,
        gpkgUrl=(
            f"https://acct.blob/c/{PARTITION}/"
            f"edited_predictions_model-1_v{version}.gpkg?sas"
        ),
        createdAt="2026-08-21T05:10:48+00:00",
        createdBy="analyst@example.com",
        predictionAttrsUrl=attrs,
        threshold=0.5,
        unknownThreshold=0.0,
        editedCount=3,
        sourceGpkgUrl=RAW_URL,
    )


def _model(**overrides) -> Model:
    data = {
        "modelId": "model-1",
        "projectId": "proj-1",
        "imageLayerId": "layer-1",
        "name": "test model",
        "gpkgUrl": RAW_URL,
    }
    data.update(overrides)
    return Model(**data)


def _layer(**overrides) -> ImageLayer:
    data = {
        "imageLayerId": "layer-1",
        "projectId": "proj-1",
        "buildingFootprintsUrl": FOOTPRINTS_URL,
    }
    data.update(overrides)
    return ImageLayer(**data)


def _prepared_model(**overrides) -> Model:
    """A model whose model-level artifacts are already built."""
    data = {
        "predictionAttrsUrl": "https://acct/prediction_attrs_model-1.json",
    }
    data.update(overrides)
    return _model(**data)


def _build_preprocessor(model: Model, layer: ImageLayer):
    with patch(
        "hastegeo.core.processors.prediction_tiles.AzureQueueHandler",
        autospec=True,
    ):
        from hastegeo.core.processors.prediction_tiles import (
            PredictionTilesPreprocessor,
        )

        return PredictionTilesPreprocessor(model, layer)


def _build_postprocessor(model: Model, layer: ImageLayer, **kwargs):
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

        return PredictionTilesPostprocessor(model, layer, **kwargs)


class TestVersionsNeedingAttrs(unittest.TestCase):
    def test_empty_without_edited_versions(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        self.assertEqual(versions_needing_attrs(_model()), [])

    def test_reports_versions_without_a_sidecar(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _model(editedPredictions=[_version(1), _version(2)])

        pending = versions_needing_attrs(model)

        self.assertEqual([entry["version"] for entry in pending], [1, 2])
        self.assertTrue(
            pending[0]["gpkgUrl"].endswith(
                "edited_predictions_model-1_v1.gpkg?sas"
            )
        )

    def test_skips_versions_that_already_have_one(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _model(
            editedPredictions=[
                _version(1, attrs="https://acct/prediction_attrs_v1.json"),
                _version(2),
            ]
        )

        self.assertEqual(
            [entry["version"] for entry in versions_needing_attrs(model)],
            [2],
        )

    def test_nothing_pending_once_every_version_has_one(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _model(
            editedPredictions=[
                _version(1, attrs="https://acct/v1.json"),
                _version(2, attrs="https://acct/v2.json"),
            ]
        )

        self.assertEqual(versions_needing_attrs(model), [])

    def test_versions_without_a_gpkg_are_skipped(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        broken = _version(1)
        broken.gpkgUrl = ""
        model = _model(editedPredictions=[broken, _version(2)])

        self.assertEqual(
            [entry["version"] for entry in versions_needing_attrs(model)],
            [2],
        )

    def test_oldest_version_first(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _model(
            editedPredictions=[_version(3), _version(1), _version(2)]
        )

        self.assertEqual(
            [entry["version"] for entry in versions_needing_attrs(model)],
            [1, 2, 3],
        )


class TestBackfillTriggersAJob(unittest.TestCase):
    def test_pending_versions_are_outstanding_work(self):
        # Both model-level artifacts exist: without backfill this model
        # would report COMPLETED and never rebuild v1.
        model = _prepared_model(editedPredictions=[_version(1)])
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        preprocessor = _build_preprocessor(model, layer)

        output = preprocessor.queue_for_processing()

        self.assertEqual(output.predictionTilesStatus, STATUSES.PENDING.value)
        preprocessor.queue_client.put_message.assert_called_once()
        payload = json.loads(
            preprocessor.queue_client.put_message.call_args.args[0]
        )
        self.assertTrue(payload["backfillVersions"])

    def test_nothing_is_queued_when_every_version_has_a_sidecar(self):
        model = _prepared_model(
            editedPredictions=[_version(1, attrs="https://acct/v1.json")]
        )
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")
        preprocessor = _build_preprocessor(model, layer)

        output = preprocessor.queue_for_processing()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )
        preprocessor.queue_client.put_message.assert_not_called()

    def test_request_preparation_reports_pending_versions(self):
        from hastegeo.core.processors import prediction_tiles

        model = _prepared_model(editedPredictions=[_version(1), _version(2)])
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")

        with patch.object(
            prediction_tiles, "AzureQueueHandler", autospec=True
        ):
            result = prediction_tiles.request_preparation(model, layer)

        self.assertTrue(result["queued"])
        self.assertEqual(result["versionsPending"], 2)
        self.assertEqual(model.predictionTilesStatus, STATUSES.PENDING.value)

    def test_request_preparation_is_a_no_op_when_nothing_is_pending(self):
        from hastegeo.core.processors import prediction_tiles

        model = _prepared_model(
            editedPredictions=[_version(1, attrs="https://acct/v1.json")]
        )
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")

        with patch.object(
            prediction_tiles, "AzureQueueHandler", autospec=True
        ):
            result = prediction_tiles.request_preparation(model, layer)

        self.assertFalse(result["queued"])
        self.assertEqual(result["versionsPending"], 0)

    def test_backfill_can_be_switched_off(self):
        from hastegeo.core.processors import prediction_tiles

        model = _prepared_model(editedPredictions=[_version(1)])
        layer = _layer(footprintPmtilesUrl="https://acct/tiles.pmtiles")

        with patch.object(
            prediction_tiles, "AzureQueueHandler", autospec=True
        ):
            result = prediction_tiles.request_preparation(
                model, layer, backfill_versions=False
            )

        self.assertFalse(result["queued"])
        self.assertEqual(result["versionsPending"], 0)


class TestJobConfigCarriesVersions(unittest.TestCase):
    def _submit(self, model: Model, **kwargs):
        processor = _build_postprocessor(model, _layer(), **kwargs)
        processor.runner.add_task.return_value = ("job-1", "ptl-abc")
        processor.storage.get_file_remote_path.return_value = (
            "https://acct.blob/c/hash/prediction_tiles_config_m.json?sas"
        )
        processor.process()
        return processor

    def test_version_gpkgs_are_task_inputs(self):
        model = _prepared_model(
            predictionTilesStatus=STATUSES.PENDING.value,
            editedPredictions=[_version(1), _version(2)],
        )

        processor = self._submit(model)

        kwargs = processor.runner.add_task.call_args.kwargs
        uploads = kwargs["resource_files_for_upload"]
        self.assertIn("predictions_v1", uploads)
        self.assertIn("predictions_v2", uploads)
        self.assertTrue(
            uploads["predictions_v1"]["file_path"].startswith("inputs/")
        )

    def test_workflow_config_lists_version_outputs(self):
        model = _prepared_model(
            predictionTilesStatus=STATUSES.PENDING.value,
            editedPredictions=[_version(2)],
        )

        processor = self._submit(model)

        workflow_config = processor.storage.save.call_args.kwargs["data"]
        self.assertEqual(
            workflow_config["versions"],
            [
                {
                    "version": 2,
                    "predictions": (
                        "inputs/edited_predictions_model-1_v2.gpkg"
                    ),
                    "attrs": "prediction_attrs_model-1_v2.json",
                }
            ],
        )

    def test_versions_with_a_sidecar_are_not_resubmitted(self):
        model = _prepared_model(
            predictionTilesStatus=STATUSES.PENDING.value,
            editedPredictions=[
                _version(1, attrs="https://acct/v1.json"),
                _version(2),
            ],
        )

        processor = self._submit(model)

        workflow_config = processor.storage.save.call_args.kwargs["data"]
        self.assertEqual(
            [entry["version"] for entry in workflow_config["versions"]], [2]
        )
        uploads = processor.runner.add_task.call_args.kwargs[
            "resource_files_for_upload"
        ]
        self.assertNotIn("predictions_v1", uploads)

    def test_backfill_disabled_submits_no_versions(self):
        model = _prepared_model(
            predictionTilesStatus=STATUSES.PENDING.value,
            editedPredictions=[_version(1)],
        )

        processor = self._submit(model, backfill_versions=False)

        workflow_config = processor.storage.save.call_args.kwargs["data"]
        self.assertEqual(workflow_config["versions"], [])


class TestCompletionRecordsVersionUrls(unittest.TestCase):
    def _completed_processor(self, model: Model, manifest: dict):
        model.predictionTilesStatus = STATUSES.IN_PROGRESS.value
        model.predictionTilesJob = TrainingJob(
            jobId="job-1",
            taskId="ptl-abc",
            modelId="model-1",
            projectId="proj-1",
            status=STATUSES.IN_PROGRESS.value,
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

    def _manifest(self, version_attrs: list) -> dict:
        return {
            "pmtiles_built": False,
            "pmtiles_filename": "",
            "pmtiles_url": None,
            "attrs_filename": "prediction_attrs_model-1.json",
            "attrs_url": "https://acct/prediction_attrs_model-1.json",
            "building_count": 12,
            "version_attrs": version_attrs,
        }

    def test_urls_land_on_the_version_entries(self):
        model = _prepared_model(editedPredictions=[_version(1), _version(2)])
        processor = self._completed_processor(
            model,
            self._manifest(
                [
                    {
                        "version": 1,
                        "filename": "prediction_attrs_model-1_v1.json",
                        "url": "https://acct/prediction_attrs_v1.json",
                    },
                    {
                        "version": 2,
                        "filename": "prediction_attrs_model-1_v2.json",
                        "url": "https://acct/prediction_attrs_v2.json",
                    },
                ]
            ),
        )

        output = processor.process()

        self.assertEqual(
            [entry.predictionAttrsUrl for entry in output.editedPredictions],
            [
                "https://acct/prediction_attrs_v1.json",
                "https://acct/prediction_attrs_v2.json",
            ],
        )

    def test_a_second_run_has_nothing_left_to_do(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _prepared_model(editedPredictions=[_version(1)])
        processor = self._completed_processor(
            model,
            self._manifest(
                [
                    {
                        "version": 1,
                        "filename": "prediction_attrs_model-1_v1.json",
                        "url": "https://acct/prediction_attrs_v1.json",
                    }
                ]
            ),
        )

        output = processor.process()

        # Idempotency: the backfill is driven by this list, and the run
        # emptied it.
        self.assertEqual(versions_needing_attrs(output), [])

    def test_url_is_resolved_from_task_outputs_when_absent(self):
        model = _prepared_model(editedPredictions=[_version(1)])
        processor = self._completed_processor(
            model,
            self._manifest(
                [
                    {
                        "version": 1,
                        "filename": "prediction_attrs_model-1_v1.json",
                        "url": None,
                    }
                ]
            ),
        )
        processor.storage.get_file_remote_path.return_value = (
            "https://acct/hash/ptl-abc/prediction_attrs_model-1_v1.json?sas"
        )

        output = processor.process()

        self.assertEqual(
            output.editedPredictions[0].predictionAttrsUrl,
            "https://acct/hash/ptl-abc/prediction_attrs_model-1_v1.json?sas",
        )

    def test_a_failed_version_stays_pending(self):
        from hastegeo.core.processors.prediction_tiles import (
            versions_needing_attrs,
        )

        model = _prepared_model(editedPredictions=[_version(1)])
        processor = self._completed_processor(
            model,
            self._manifest(
                [
                    {
                        "version": 1,
                        "filename": "",
                        "url": None,
                        "error": "input GeoPackage missing",
                    }
                ]
            ),
        )
        processor.storage.get_file_remote_path.return_value = ""

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )
        self.assertIsNone(output.editedPredictions[0].predictionAttrsUrl)
        # Left in the pending list so the next request retries it.
        self.assertEqual(
            [entry["version"] for entry in versions_needing_attrs(output)],
            [1],
        )

    def test_unknown_version_in_the_manifest_is_ignored(self):
        model = _prepared_model(editedPredictions=[_version(1)])
        processor = self._completed_processor(
            model,
            self._manifest(
                [
                    {
                        "version": 9,
                        "filename": "prediction_attrs_model-1_v9.json",
                        "url": "https://acct/prediction_attrs_v9.json",
                    }
                ]
            ),
        )

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )
        self.assertIsNone(output.editedPredictions[0].predictionAttrsUrl)

    def test_a_manifest_without_versions_is_fine(self):
        model = _prepared_model(editedPredictions=[_version(1)])
        processor = self._completed_processor(model, self._manifest([]))

        output = processor.process()

        self.assertEqual(
            output.predictionTilesStatus, STATUSES.COMPLETED.value
        )


if __name__ == "__main__":
    unittest.main()
