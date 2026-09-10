# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio

import azure.functions as func
import pytest
from hastegeo.core.processors.job_queue import reconcile_local_tasks
from hastegeo.core.processors.job_state import Workload

from api.hastefuncqueues import function_app


@pytest.mark.parametrize(
    "handler, workload, poison",
    [
        ("GetProcessImageLayerQueueMessage", Workload.IMAGERY, False),
        ("GetCreateModelRunQueueMessage", Workload.TRAINING, False),
        ("GetRunEmbeddingQueueMessage", Workload.EMBEDDING, False),
        ("GetRunInferenceQueueMessage", Workload.INFERENCE, False),
        ("GetArtifactsZipQueueMessage", Workload.ZIP, False),
        ("ImagePoisonQueueHandler", Workload.IMAGERY, True),
        ("TrainingPoisonQueueHandler", Workload.TRAINING, True),
        ("EmbeddingPoisonQueueHandler", Workload.EMBEDDING, True),
        ("InferencePoisonQueueHandler", Workload.INFERENCE, True),
        ("ArtifactsZipPoisonQueueHandler", Workload.ZIP, True),
    ],
)
def test_job_handler_delegates_without_saving_message_snapshot(
    mocker, handler: str, workload: Workload, poison: bool
) -> None:
    processor = mocker.Mock()
    mocker.patch.object(
        function_app, "JobQueueProcessor", return_value=processor
    )
    metadata = mocker.patch.object(function_app, "MetadataProcessor")
    message = func.QueueMessage(id="message-id", body="{}")
    asyncio.run(getattr(function_app, handler)(message))
    if poison:
        processor.process_message.assert_called_once_with(
            workload, b"{}", poison=True
        )
    else:
        processor.process_message.assert_called_once_with(workload, b"{}")
    metadata.assert_not_called()


def test_local_timer_drives_durable_receipts(mocker) -> None:
    reconcile = mocker.patch.object(function_app, "reconcile_local_tasks")
    asyncio.run(function_app.ReconcileLocalTasks(mocker.Mock()))
    reconcile.assert_called_once_with(function_app.config)


def test_queue_timer_runs_independently_of_local_staging(mocker) -> None:
    repository = mocker.Mock()
    mocker.patch.object(
        function_app, "JobStateRepository", return_value=repository
    )
    asyncio.run(function_app.ReconcileJobQueues(mocker.Mock()))
    repository.reconcile_queues.assert_called_once_with()


def test_runtime_without_local_receipts_never_constructs_docker_controller(
    mocker,
    tmp_path,
) -> None:
    mocker.patch("hastegeo.core.runners.local.TASK_WORK_DIR", tmp_path)
    config = mocker.Mock(runner_type="azure_batch")
    docker = mocker.patch(
        "docker.from_env",
        side_effect=AssertionError("Docker must not be used"),
    )
    assert reconcile_local_tasks(config) == 0
    docker.assert_not_called()


def test_receipts_still_reconcile_after_default_backend_changes(
    mocker, tmp_path
) -> None:
    mocker.patch("hastegeo.core.runners.local.TASK_WORK_DIR", tmp_path)
    (tmp_path / ".lifecycle").mkdir()
    runner = mocker.patch("hastegeo.core.runners.local.LocalRunner")
    runner.return_value.reconcile_tasks.return_value = 1
    config = mocker.Mock(runner_type="azure_batch")
    assert reconcile_local_tasks(config) == 1
    runner.assert_called_once_with(config=config)
