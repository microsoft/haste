# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlparse

from hastegeo.core.artifact_storage import (
    local_file_system_artifact_storage as local_storage,
)
from hastegeo.core.models.projects import Model
from hastegeo.core.processors import (
    inference,
    job_queue,
    job_state,
    prediction_results,
)
from hastegeo.core.processors.job_state import Workload
from hastegeo.core.utils.metadata import MetadataUtils

from .test_prediction_results import (
    MODEL_ID,
    PROJECT_ID,
    ResultsTestCase,
    attrs,
)


def windows_safe_local_download_url(
    storage: local_storage.LocalFileSystemArtifactStorage,
    identifier: str | None = None,
    artifact_path: str | None = None,
    extra_partition_keys: list[str] | str | None = None,
) -> str:
    if artifact_path:
        return Path(artifact_path).resolve().as_uri()
    return (
        Path(storage.get_file_path(identifier, extra_partition_keys))
        .resolve()
        .as_uri()
    )


def windows_safe_resolve_artifact_path(
    storage: local_storage.LocalFileSystemArtifactStorage,
    location: str,
) -> str:
    parsed = urlparse(location)
    raw_path = unquote(parsed.path) if parsed.scheme == "file" else location
    if (
        parsed.scheme == "file"
        and len(raw_path) >= 3
        and raw_path[0] == "/"
        and raw_path[2] == ":"
    ):
        raw_path = raw_path[1:]
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = Path(storage.directory, candidate)
    resolved = candidate.resolve()
    root = Path(storage.directory).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Artifact path escapes the configured storage root")
    return str(resolved.relative_to(root))


@contextmanager
def no_prediction_edit_lock(
    config: Any, project_id: str, model_id: str
) -> Iterator[None]:
    yield None


class RecordingPredictionLock:
    def __init__(
        self,
        owner: "TestInferenceResults",
        source: str,
        project_id: str,
        model_id: str,
    ) -> None:
        self.owner = owner
        self.source = source
        self.project_id = project_id
        self.model_id = model_id

    def __enter__(self) -> None:
        self.owner.lock_events.append(
            (self.source, "enter", self.project_id, self.model_id)
        )
        self.owner.lock_depth += 1
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        self.owner.lock_depth -= 1
        self.owner.lock_events.append(
            (self.source, "exit", self.project_id, self.model_id)
        )


class TestInferenceResults(ResultsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.record.update(modelType="trained", checkpointPath="checkpoints")
        self.now = 1000.0
        self.repository_class = job_state.JobStateRepository
        self.lock_depth = 0
        self.lock_events: list[tuple[str, str, str, str]] = []
        self.completed_commit_lock_depths: list[int] = []
        self.metadata.mutate.side_effect = self.mutate
        if os.name == "nt":
            self.enterContext(
                patch.object(
                    local_storage.LocalFileSystemArtifactStorage,
                    "get_download_url",
                    windows_safe_local_download_url,
                )
            )
            self.enterContext(
                patch.object(
                    local_storage.LocalFileSystemArtifactStorage,
                    "resolve_artifact_path",
                    windows_safe_resolve_artifact_path,
                )
            )
        self.enterContext(
            patch.object(
                prediction_results,
                "prediction_edit_lock",
                no_prediction_edit_lock,
            )
        )
        self.enterContext(
            patch.object(
                inference, "MetadataProcessor", return_value=self.metadata
            )
        )
        self.enterContext(
            patch.object(
                job_queue, "MetadataProcessor", return_value=self.metadata
            )
        )
        self.repository = job_state.JobStateRepository(
            self.config,
            processor_factory=self.processor_factory,
            clock=self.clock,
        )
        self.repository.commit = self.recording_commit
        self.enterContext(
            patch.object(
                job_state,
                "JobStateRepository",
                side_effect=lambda config: self.repository,
            )
        )
        self.runner = self.enterContext(
            patch.object(inference, "UnifiedRunner")
        ).return_value
        self.enterContext(
            patch.object(job_queue, "UnifiedRunner", return_value=self.runner)
        )
        self.runner.add_task.side_effect = lambda *args, **kwargs: (
            args[0] if args else kwargs["job_id"],
            args[1] if len(args) > 1 else kwargs["task_id"],
        )
        self.runner.get_filecontent_from_task.return_value = None
        self.runner.cancel_task.return_value = True
        self.queue = self.enterContext(
            patch.object(inference, "AzureQueueHandler")
        ).return_value
        self.enterContext(
            patch.object(
                job_state, "AzureQueueHandler", return_value=self.queue
            )
        )
        self.enterContext(
            patch.object(
                inference,
                "prediction_edit_lock",
                side_effect=self.inference_lock,
            )
        )
        self.enterContext(
            patch.object(
                job_queue,
                "prediction_edit_lock",
                side_effect=self.job_queue_lock,
            )
        )
        self.artifacts = self.enterContext(
            patch.object(job_queue, "ArtifactProcessor")
        ).return_value
        self.layer.postEventProcessedImageryUrl = "https://storage/post.tif"
        self.layer.postEventMosaicCogImageryUrl = "https://storage/raw.tif"
        self.config.runner_type = "local"
        self.processor = job_queue.JobQueueProcessor(
            self.config, repository=self.repository
        )

    def clock(self) -> float:
        return self.now

    def processor_factory(self, **kwargs: Any) -> MagicMock:
        return self.metadata

    def mutate(self, key: str, change: Any) -> dict[str, Any]:
        if key != MODEL_ID:
            current = self.load(key)
            result = change(deepcopy(current))
            return deepcopy(current if result is None else result)
        result = change(deepcopy(self.record))
        if result is None:
            return deepcopy(self.record)
        self.record.clear()
        self.record.update(deepcopy(result))
        return deepcopy(self.record)

    def recording_commit(
        self,
        workload: Workload,
        baseline: dict[str, Any],
        output: Any,
        cleanup: list[job_state.TaskIdentity],
    ) -> dict[str, Any] | None:
        if (
            workload == Workload.INFERENCE
            and output.inferenceStatus
            == self.config.get_status_types().COMPLETED.value
        ):
            self.completed_commit_lock_depths.append(self.lock_depth)
        return self.repository_class.commit(
            self.repository, workload, baseline, output, cleanup
        )

    def inference_lock(
        self, config: Any, project_id: str, model_id: str
    ) -> RecordingPredictionLock:
        return RecordingPredictionLock(self, "inference", project_id, model_id)

    def job_queue_lock(
        self, config: Any, project_id: str, model_id: str
    ) -> RecordingPredictionLock:
        return RecordingPredictionLock(self, "job_queue", project_id, model_id)

    def start(self, **snapshot: Any) -> dict[str, Any]:
        inference.InferencePreprocessor(
            Model(**{**self.record, **snapshot}), self.config
        ).send_to_queue()
        self.assertIn(
            ("inference", "enter", PROJECT_ID, MODEL_ID),
            self.lock_events,
        )
        return json.loads(self.queue.put_message.call_args.args[0])

    def poll(self, message: dict[str, Any]) -> Model:
        self.now += 31
        self.processor.process(Workload.INFERENCE, message)
        return Model(**self.record)

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
        task = self.poll(self.start()).currentInferenceTaskId
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

    def test_submission_uses_stored_model_not_caller_snapshot(self) -> None:
        message = self.start(
            gpkgUrl="https://storage/snapshot.gpkg",
            predictionAttrsUrl="https://storage/snapshot.json",
            predictionRevision="snapshot",
        )

        self.assertEqual(self.record["gpkgUrl"], "https://storage/old.gpkg")
        self.assertEqual(self.record["predictionRevision"], "old")
        self.assertEqual(message["gpkgUrl"], "https://storage/old.gpkg")

    def test_completed_pair_is_checked_in_local_and_batch_upload_paths(
        self,
    ) -> None:
        for runner in ("local", "azure_batch"):
            self.config.runner_type = runner
            message = self.start()
            request = self.poll(message)
            self.upload_pair()
            self.runner.get_task_status.return_value = "Processed"
            output = self.poll(message)
            self.assertEqual(
                self.record["predictionRevision"],
                request.currentInferenceTaskId,
            )
            self.assertEqual(self.record["predictedBuildingCount"], 2)
            self.assertEqual(output.gpkgUrl, self.record["gpkgUrl"])
            self.assertIn(1, self.completed_commit_lock_depths)
            self.assertIn(
                ("job_queue", "enter", PROJECT_ID, MODEL_ID),
                self.lock_events,
            )

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
            self.poll(self.start())

    def test_missing_or_mismatched_upload_preserves_previous_pair(
        self,
    ) -> None:
        old_pair = {
            key: self.record[key]
            for key in ("gpkgUrl", "predictionAttrsUrl", "predictionRevision")
        }
        for mismatch in (False, True):
            message = self.start()
            self.poll(message)
            if mismatch:
                self.upload_pair(revision="wrong")
            self.runner.get_task_status.return_value = "Processed"
            output = self.poll(message)
            self.assertEqual(output.inferenceStatus, "Failed")
            self.assertEqual(
                {key: self.record[key] for key in old_pair}, old_pair
            )

    def test_old_task_message_does_not_restore_snapshot_or_run(self) -> None:
        message = self.start()
        self.record["currentInferenceTaskId"] = "another-task"
        self.poll(message)
        self.runner.get_task_status.assert_not_called()
        self.runner.add_task.assert_not_called()
        self.assertEqual(self.record["predictionRevision"], "old")

    def test_superseded_completion_does_not_publish_old_pair(self) -> None:
        message = self.start()
        self.poll(message)
        self.upload_pair()

        def status(*args: Any) -> str:
            self.record["currentInferenceTaskId"] = "another-task"
            return "Processed"

        self.runner.get_task_status.side_effect = status
        self.poll(message)
        self.assertEqual(self.record["predictionRevision"], "old")

    def test_cancel_call_preserves_retry_after_runner_failure(self) -> None:
        message = self.start()
        self.poll(message)
        inference.InferencePreprocessor(
            Model(**self.record), self.config
        ).send_to_queue(status="Cancelled")
        self.runner.cancel_task.side_effect = OSError("unavailable")
        body = self.queue.put_message.call_args.args[0].encode()
        self.now += 31
        with self.assertRaisesRegex(
            RuntimeError, "Job queue dispatch failed: OSError"
        ):
            self.processor.process_message(Workload.INFERENCE, body)
        self.assertEqual(
            self.record["inferenceJobs"][-1]["status"], "InProgress"
        )
