# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import yaml
from hastegeo.core.artifact_storage.unified_artifact_storage import (
    UnifiedArtifactStorage,
)
from hastegeo.core.config import Config
from hastegeo.core.models.pretrained_inference import CatalogInferenceRequest
from hastegeo.core.models.projects import ImageLayer, Model, Project
from hastegeo.core.models.training import CatalogModel
from hastegeo.core.processors.catalog_inference import (
    CatalogInferenceProcessor,
)
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.model_catalog import (
    CatalogConflictError,
    ModelCatalogProcessor,
)
from hastegeo.core.utils.catalog_lock import catalog_task_id
from hastegeo.core.utils.metadata import MetadataUtils

PROJECT = "11111111-1111-4111-8111-111111111111"
SOURCE = "22222222-2222-4222-8222-222222222222"
LAYER = "33333333-3333-4333-8333-333333333333"


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.config = Config()
        self.config.storage_type = self.config.artifact_storage_type = "local"
        self.config.runner_type = "local"
        self.config.storage_config = {
            "directory": str(self.directory / "meta")
        }
        self.config.artifact_storage_config = {
            "directory": str(self.directory / "assets")
        }
        self.assets = UnifiedArtifactStorage(
            "local", **self.config.artifact_storage_config
        )
        for name in (
            "source/checkpoint/last.ckpt",
            "target/raw.tif",
            "target/rgb.tif",
            "target/footprints.gpkg",
        ):
            self.assets.store_artifact(name, data="fixture")
        self.source_model = Model(
            projectId=SOURCE,
            modelId="1001",
            status="Processed",
            checkpointPath="source/checkpoint",
            modelType="trained",
        )
        self.put("model", "1001", self.source_model.model_dump(), SOURCE)
        self.experiment = {
            "imagery": {
                "num_channels": 3,
                "normalization_means": [1, 2, 3],
                "normalization_stds": [4, 5, 6],
            },
            "labels": {
                "classes": [
                    "Background",
                    "Building",
                    "Damaged Building",
                    "Cloud",
                ],
                "fn": "unused-training-labels",
            },
            "training": {"checkpoint_subdir": "checkpoint"},
        }
        self.put("experiment_config", "1001", self.experiment, SOURCE, "yaml")
        self.layer = ImageLayer(
            projectId=PROJECT,
            imageLayerId=LAYER,
            status="Processed",
            workflowType="standard",
            normalizationMeans=[10, 20, 30],
            postEventMosaicCogImageryUrl=self.assets.get_download_url(
                identifier="target/raw.tif"
            ),
            postEventProcessedImageryUrl=self.assets.get_download_url(
                identifier="target/rgb.tif"
            ),
            buildingFootprintsUrl=self.assets.get_download_url(
                identifier="target/footprints.gpkg"
            ),
        )
        self.put("imagelayer", LAYER, self.layer.model_dump())
        self.put("project", PROJECT, Project(projectId=PROJECT).model_dump())
        self.catalog = ModelCatalogProcessor(self.config)
        self.entry = self.catalog.add(
            CatalogModel(
                baseModelName="Base model",
                modelId="1001",
                projectId=SOURCE,
                source="haste",
                cataloguedByUser="author",
            )
        )
        self.processor = CatalogInferenceProcessor(self.config)
        self.queue = self.enterContext(
            patch(
                "hastegeo.core.processors.catalog_inference.AzureQueueHandler"
            )
        ).return_value
        self.runner = self.enterContext(
            patch("hastegeo.core.processors.catalog_inference.UnifiedRunner")
        ).return_value
        self.runner.get_task_status.return_value = "InProgress"
        self.runner.get_filecontent_from_task.return_value = None
        self.archive = self.enterContext(
            patch(
                "hastegeo.core.processors.catalog_inference.CatalogArtifactProcessor"
            )
        ).return_value

    def put(self, kind, key, data, project=PROJECT, fmt="json"):
        MetadataProcessor(kind, project, self.config).save(key, data, fmt)

    def request(self, **changes):
        return CatalogInferenceRequest.model_validate(
            {
                "projectId": PROJECT,
                "imageLayerId": LAYER,
                "baseModelName": "Base model",
                "clientRequestId": str(uuid4()),
                **changes,
            }
        )

    def outputs(self, model):
        task = catalog_task_id(model.projectId, model.inferenceRequestId)
        prefix = f"{MetadataUtils.hash_string(PROJECT)}/{task}/inference"
        stem = (
            self.config.get_artifact_types()
            .VISUALIZER.value.substitute(projectId=PROJECT, imageLayerId=LAYER)
            .removesuffix("_visualizer")
        )
        for name in (
            stem + "_predictions.tif",
            stem + "_visualizer.tif",
            f"predicted_damage_{model.name}.gpkg",
        ):
            self.assets.store_artifact(name, data="output", namespace=prefix)


class TestCatalogRuns(CatalogTestCase):
    def test_persist_before_identifiers_only_queue_and_idempotent_retry(
        self,
    ) -> None:
        request = self.request()

        def queued(message, **kwargs):
            payload = json.loads(message)
            self.assertEqual(
                set(payload), {"projectId", "modelId", "inferenceRequestId"}
            )
            stored = self.processor.metadata(PROJECT).load(payload["modelId"])
            self.assertEqual(stored["inferenceStatus"], "Queued")
            self.assertNotIn("checkpoint", message)

        self.queue.put_message.side_effect = queued
        first = self.processor.start(request, "analyst")
        replay = self.processor.start(request, "analyst")
        self.assertEqual(first.modelId, replay.modelId)
        self.assertEqual(first.modelType, "pretrained")
        self.assertIsNone(first.status)
        self.assertIsNone(first.trainingJob)
        self.assertEqual(first.labelsCount, 0)
        self.assertEqual(
            first.pretrainedInference.normalizationMeans, [1, 2, 3]
        )
        second = self.processor.start(self.request(), "analyst")
        self.assertNotEqual(first.modelId, second.modelId)
        with self.assertRaises(CatalogConflictError):
            self.processor.start(
                request.model_copy(update={"name": "changed"}), "analyst"
            )

    def test_runs_use_staged_snapshot_without_training_or_source_mutation(
        self,
    ) -> None:
        model = self.processor.start(self.request(), "analyst")
        self.processor.process(PROJECT, model.modelId)
        submitted = self.runner.add_task.call_args.kwargs
        self.assertTrue(submitted["idempotent"])
        self.assertEqual(submitted["image_name"], model.inferenceImage)
        self.assertIn(
            "$AZ_BATCH_TASK_WORKING_DIR/logs/**/*", submitted["file_pattern"]
        )
        self.assertIn("--step inference", submitted["command"])
        self.assertIn(
            "TORCHINDUCTOR_CACHE_DIR=$AZ_BATCH_TASK_WORKING_DIR/",
            submitted["command"],
        )
        self.assertEqual(submitted["env_vars"]["USER"], "haste-inference")
        self.assertNotIn("fine_tune", submitted["command"])
        self.assertNotIn("labels", submitted["resource_files_for_upload"])
        config_url = submitted["resource_files_for_upload"]["config"][
            "http_url"
        ]
        config_path = self.assets.resolve_artifact_path(config_url)
        config = yaml.safe_load(
            Path(self.assets.get_file_path(config_path)).read_text()
        )
        self.assertEqual(config["imagery"]["normalization_means"], [1, 2, 3])
        self.assertEqual(config["inference"]["adapter"], "legacy_haste")
        self.assertTrue(config["inference"]["preserve_source_identity"])
        self.assertEqual(
            MetadataProcessor("model", SOURCE, self.config).load("1001"),
            self.source_model.model_dump(mode="json"),
        )
        self.assertEqual(
            self.processor.metadata(PROJECT).load(model.modelId)[
                "inferenceStatus"
            ],
            "InProgress",
        )
        self.outputs(model)
        self.runner.get_task_status.return_value = "Processed"

        def cleaned(*args):
            saved = self.processor.metadata(PROJECT).load(model.modelId)
            self.assertEqual(saved["inferenceStatus"], "Processed")
            self.assertTrue(saved["gpkgUrl"])

        self.runner.cleanup_task.side_effect = cleaned
        output = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(output.inferenceProgressPct, 100)
        self.archive.process.assert_called_once()
        calls = self.runner.add_task.call_count
        self.processor.process(PROJECT, model.modelId)
        self.assertEqual(self.runner.add_task.call_count, calls)

    def test_cancelled_queued_and_running_runs_do_not_publish_results(
        self,
    ) -> None:
        queued = self.processor.start(self.request(), "analyst")
        self.processor.cancel(PROJECT, queued.modelId)
        self.processor.process(PROJECT, queued.modelId)
        self.runner.add_task.assert_not_called()
        running = self.processor.start(self.request(), "analyst")
        self.outputs(running)
        self.runner.add_task.side_effect = (
            lambda **kwargs: self.processor.cancel(PROJECT, running.modelId)
        )
        self.runner.get_task_status.return_value = "Processed"
        output = self.processor.process(PROJECT, running.modelId)
        self.assertEqual(output.inferenceStatus, "Cancelled")
        self.assertEqual(output.inferenceJobs[-1].status, "Cancelled")
        self.runner.cleanup_task.assert_called_once()
        self.assertIsNone(output.gpkgUrl)
        self.runner.cancel_task.assert_called_with(
            catalog_task_id(running.projectId, running.inferenceRequestId),
            catalog_task_id(running.projectId, running.inferenceRequestId),
        )

    def test_retry_reuses_task_identity_and_missing_outputs_fail_visibly(
        self,
    ) -> None:
        model = self.processor.start(self.request(), "analyst")
        self.runner.add_task.side_effect = TimeoutError(
            "do not expose credential text"
        )
        first = self.processor.process(PROJECT, model.modelId)
        first_id = self.runner.add_task.call_args.kwargs["task_id"]
        self.assertEqual(first.inferenceFailures, 1)
        self.assertNotIn("credential text", first.inferenceStatusMessage)
        self.runner.add_task.side_effect = None
        self.runner.get_task_status.return_value = "Processed"
        failed = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(
            self.runner.add_task.call_args.kwargs["task_id"], first_id
        )
        self.assertEqual(failed.inferenceStatus, "Failed")
        self.assertIsNone(failed.gpkgUrl)

    def test_incompatible_layer_does_not_create_a_run(self) -> None:
        self.put("imagelayer", LAYER, {"workflowType": "building"})
        with self.assertRaises(ValueError):
            self.processor.start(self.request(), "analyst")
        self.assertEqual(
            self.processor.metadata(PROJECT).load_all_from_partition(), []
        )

    def test_queue_failure_can_retry_the_same_persisted_run(self) -> None:
        request = self.request()
        self.queue.put_message.side_effect = TimeoutError("offline")
        with self.assertRaises(TimeoutError):
            self.processor.start(request, "analyst")
        records = self.processor.metadata(PROJECT).load_all_from_partition()
        self.assertEqual(len(records), 1)
        self.queue.put_message.side_effect = None
        retry = self.processor.start(request, "analyst")
        self.assertEqual(retry.modelId, records[0]["modelId"])

    def test_workflow_progress_is_preserved_without_duplicate_poll_messages(
        self,
    ) -> None:
        model = self.processor.start(self.request(), "analyst")
        self.runner.get_filecontent_from_task.return_value = (
            "2026-09-09T00:00:00|Completed inference\n"
            "2026-09-09T00:00:01|Aggregating footprints\n"
        )
        first = self.processor.process(PROJECT, model.modelId)
        second = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(
            first.inferenceStatusMessage, second.inferenceStatusMessage
        )
        self.assertEqual(
            first.inferenceCurrentStep, second.inferenceCurrentStep
        )
        self.assertGreater(second.inferenceProgressPct, 0)

    def test_late_failure_does_not_downgrade_a_completed_run(self) -> None:
        model = self.processor.start(self.request(), "analyst")

        def accepted(**kwargs):
            self.put("model", model.modelId, {"inferenceStatus": "Processed"})
            raise TimeoutError("late timeout")

        self.runner.add_task.side_effect = accepted
        result = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(result.inferenceStatus, "Processed")
        self.assertEqual(result.inferenceFailures, 0)

    def test_transient_failures_are_bounded_and_terminal_replay_is_noop(
        self,
    ) -> None:
        model = self.processor.start(self.request(), "analyst")
        self.runner.add_task.side_effect = TimeoutError("offline")
        for _ in range(5):
            result = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(result.inferenceStatus, "Failed")
        self.assertEqual(result.inferenceFailures, 5)
        self.processor.process(PROJECT, model.modelId)
        self.assertEqual(self.runner.add_task.call_count, 5)

    def test_same_request_uuid_in_two_projects_has_distinct_runner_tasks(
        self,
    ) -> None:
        request = self.request()
        first = self.processor.start(request, "analyst")
        self.put(
            "project", SOURCE, Project(projectId=SOURCE).model_dump(), SOURCE
        )
        self.put(
            "imagelayer",
            LAYER,
            self.layer.model_copy(update={"projectId": SOURCE}).model_dump(),
            SOURCE,
        )
        second = self.processor.start(
            request.model_copy(update={"projectId": SOURCE}), "analyst"
        )
        self.processor.process(PROJECT, first.modelId)
        self.processor.process(SOURCE, second.modelId)
        task_ids = [
            call.kwargs["task_id"]
            for call in self.runner.add_task.call_args_list
        ]
        self.assertEqual(len(set(task_ids)), 2)
        self.assertTrue(all(len(task_id) <= 64 for task_id in task_ids))
        self.assertNotEqual(
            catalog_task_id(PROJECT, str(request.clientRequestId), "zip"),
            catalog_task_id(SOURCE, str(request.clientRequestId), "zip"),
        )


class TestCatalogRegistry(CatalogTestCase):
    def test_legacy_recipe_and_target_compatibility(self) -> None:
        rows = self.catalog.list(capability="inference", layer=self.layer)
        self.assertTrue(rows[0]["inferenceReady"])
        self.layer.normalizationMeans = [1, 2]
        self.assertFalse(
            self.catalog.list(capability="inference", layer=self.layer)[0][
                "inferenceReady"
            ]
        )

    def test_external_entries_can_be_removed_by_name_without_model_id(
        self,
    ) -> None:
        entry = CatalogModel(
            baseModelName="External",
            source="external",
            checkpointFilePath="https://example.test/model.ckpt",
            cataloguedByUser="author",
        )
        self.catalog.add(entry)
        removed = self.catalog.delete("External", None)
        self.assertEqual(removed["baseModelName"], "External")
        self.assertEqual(len(self.catalog.records()), 1)
        with self.assertRaises(CatalogConflictError):
            self.catalog.add(self.entry)

    def test_storage_failure_is_not_an_empty_catalog(self) -> None:
        error = FileNotFoundError("wrapped storage failure")
        error.__cause__ = TimeoutError("offline")
        with patch.object(
            self.catalog.metadata.storage, "load", side_effect=error
        ):
            with self.assertRaises(RuntimeError):
                self.catalog.records()

    def test_changed_checkpoint_is_not_silently_reused(self) -> None:
        self.assets.store_artifact(
            "source/checkpoint/last.ckpt", data="changed"
        )
        self.assertFalse(
            self.catalog.list(capability="inference")[0]["inferenceReady"]
        )

    def test_registered_recipe_rejects_changed_source_configuration(
        self,
    ) -> None:
        changed = {**self.experiment, "training": {"checkpoint_subdir": "new"}}
        self.put("experiment_config", "1001", changed, SOURCE, "yaml")
        self.assertFalse(
            self.catalog.list(capability="inference")[0]["inferenceReady"]
        )

    def test_registered_recipe_rejects_retrained_source_checkpoint(
        self,
    ) -> None:
        self.put(
            "model",
            "1001",
            {"checkpointPath": "source/new-checkpoint"},
            SOURCE,
        )
        self.assertFalse(
            self.catalog.list(capability="inference")[0]["inferenceReady"]
        )


class TestCatalogStorageFailures(CatalogTestCase):
    def test_wrapped_model_read_failure_is_not_deletion_or_state_reset(
        self,
    ) -> None:
        model = self.processor.start(self.request(), "analyst")
        error = FileNotFoundError("wrapped timeout")
        error.__cause__ = TimeoutError("offline")
        with patch(
            "hastegeo.core.processors.metadata.MetadataProcessor.load",
            side_effect=error,
        ):
            with self.assertRaises(RuntimeError):
                self.processor.process(PROJECT, model.modelId)
        current = self.processor.metadata(PROJECT).load(model.modelId)
        self.assertEqual(current["inferenceStatus"], "Queued")
        self.assertIsNotNone(current["pretrainedInference"])

    def test_wrapped_layer_read_failure_is_retryable_not_terminal(
        self,
    ) -> None:
        from hastegeo.core.processors.metadata import MetadataProcessor

        model = self.processor.start(self.request(), "analyst")
        original = MetadataProcessor.load
        error = FileNotFoundError("wrapped timeout")
        error.__cause__ = TimeoutError("offline")

        def load(metadata, key, data_format="json"):
            if metadata.data_type == "imagelayer":
                raise error
            return original(metadata, key, data_format)

        with patch.object(MetadataProcessor, "load", load):
            result = self.processor.process(PROJECT, model.modelId)
        self.assertEqual(result.inferenceStatus, "Queued")
        self.assertEqual(result.inferenceFailures, 1)

    def test_old_request_cannot_process_a_reused_short_model_id(self) -> None:
        model = self.processor.start(self.request(), "analyst")
        result = self.processor.process(PROJECT, model.modelId, str(uuid4()))
        self.assertIsNone(result)
        self.runner.add_task.assert_not_called()
