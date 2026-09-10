# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hastegeo.core.models.projects import Model
from hastegeo.core.processors import inference
from hastegeo.core.utils.metadata import MetadataUtils

from .test_prediction_results import (
    MODEL_ID,
    PROJECT_ID,
    ResultsTestCase,
    attrs,
)


class TestInferenceResults(ResultsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.record.update(modelType="trained", checkpointPath="checkpoints")
        self.enterContext(
            patch.object(
                inference, "MetadataProcessor", return_value=self.metadata
            )
        )
        self.runner = self.enterContext(
            patch.object(inference, "UnifiedRunner")
        ).return_value
        self.runner.add_task.side_effect = lambda **kwargs: (
            kwargs["job_id"],
            kwargs["task_id"],
        )
        self.runner.get_filecontent_from_task.return_value = None
        self.queue = self.enterContext(
            patch.object(inference, "AzureQueueHandler")
        ).return_value
        self.layer.postEventProcessedImageryUrl = "https://storage/post.tif"
        self.layer.postEventMosaicCogImageryUrl = "https://storage/raw.tif"
        self.config.runner_type = "local"

    def submit(self) -> Model:
        inference.InferencePreprocessor(
            Model(**self.record), self.config
        ).send_to_queue()
        request = Model.model_validate_json(
            self.queue.put_message.call_args.args[0]
        )
        return inference.process_inference_request(request, self.config)

    def upload_pair(self, *, revision: str | None = None) -> None:
        namespace = [
            MetadataUtils.hash_string(PROJECT_ID),
            self.record["currentInferenceTaskId"],
        ]
        if self.config.runner_type == "local":
            namespace.append("inference")
        directory = Path(self.directory, *namespace)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / self.record["predictionGpkgFilename"]).write_bytes(
            b"GPKG transport"
        )
        (directory / f"prediction_attrs_{MODEL_ID}.json").write_text(
            json.dumps(
                attrs(
                    revision or self.record["currentInferenceTaskId"],
                    "inference",
                )
            )
        )

    def test_config_uses_task_revision_and_matching_safe_filenames(
        self,
    ) -> None:
        task = self.submit().currentInferenceTaskId
        path = Path(
            self.directory,
            MetadataUtils.hash_string(PROJECT_ID),
            f"experiment_config_{MODEL_ID}-{task}.yaml",
        )
        config = json.loads(path.read_text())["inference"]
        self.assertEqual(config["prediction_revision"], task)
        self.assertEqual(
            config["prediction_attrs_filename"], "prediction_attrs_0042.json"
        )
        self.assertEqual(
            config["predictions_gpkg_fileprefix"],
            "predicted_damage_Flood-Sao-1",
        )
        self.assertEqual(self.record["predictionRevision"], "old")

    def test_completed_pair_is_checked_in_local_and_batch_upload_paths(
        self,
    ) -> None:
        for runner in ("local", "azure_batch"):
            self.config.runner_type = runner
            request = self.submit()
            self.upload_pair()
            self.runner.get_task_status.return_value = "Processed"
            output = inference.process_inference_request(request, self.config)
            self.assertEqual(
                self.record["predictionRevision"],
                request.currentInferenceTaskId,
            )
            self.assertEqual(self.record["predictedBuildingCount"], 2)
            self.assertEqual(output.gpkgUrl, self.record["gpkgUrl"])

    def test_job_config_is_stored_before_its_download_url_is_resolved(
        self,
    ) -> None:
        original = inference.UnifiedDataLayer.get_file_remote_path

        def resolve(storage: Any, *args: Any, **kwargs: Any) -> str:
            path = original(storage, *args, **kwargs)
            self.assertTrue(Path(path).is_file())
            return path

        with patch.object(
            inference.UnifiedDataLayer, "get_file_remote_path", resolve
        ):
            self.submit()

    def test_missing_or_mismatched_upload_preserves_previous_pair(
        self,
    ) -> None:
        old_pair = {
            key: self.record[key]
            for key in ("gpkgUrl", "predictionAttrsUrl", "predictionRevision")
        }
        for mismatch in (False, True):
            request = self.submit()
            if mismatch:
                self.upload_pair(revision="wrong")
            self.runner.get_task_status.return_value = "Processed"
            output = inference.process_inference_request(request, self.config)
            self.assertEqual(output.inferenceStatus, "Failed")
            self.assertEqual(
                {key: self.record[key] for key in old_pair}, old_pair
            )

    def test_old_task_message_does_not_restore_snapshot_or_run(self) -> None:
        request = self.submit()
        self.record["currentInferenceTaskId"] = "another-task"
        self.assertIsNone(
            inference.process_inference_request(request, self.config)
        )
        self.runner.get_task_status.assert_not_called()
        self.assertEqual(self.record["predictionRevision"], "old")

    def test_superseded_completion_does_not_publish_old_pair(self) -> None:
        request = self.submit()
        self.upload_pair()

        def status(*args: Any) -> str:
            self.record["currentInferenceTaskId"] = "another-task"
            return "Processed"

        self.runner.get_task_status.side_effect = status
        self.assertIsNone(
            inference.process_inference_request(request, self.config)
        )
        self.assertEqual(self.record["predictionRevision"], "old")

    def test_cancel_call_preserves_retry_after_runner_failure(self) -> None:
        request = self.submit()
        inference.InferencePreprocessor(
            Model(**self.record), self.config
        ).send_to_queue(status="Cancelled")
        self.runner.cancel_task.side_effect = OSError("unavailable")
        with self.assertRaises(RuntimeError):
            inference.process_inference_request(request, self.config)
        self.assertEqual(
            self.record["inferenceJobs"][-1]["status"], "InProgress"
        )
