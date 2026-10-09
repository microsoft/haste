# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import asyncio
import importlib
import os

import azure.functions as func
import pytest
from hastegeo.core.processors.job_queue import reconcile_local_tasks
from hastegeo.core.processors.job_state import Workload

from api.hastefuncqueues import function_app


@pytest.fixture
def queue_app_for():
    """Import the queue app again under a runner type, then restore it."""
    original = os.environ.get("RUNNER_TYPE")

    def load(runner_type: str):
        os.environ["RUNNER_TYPE"] = runner_type
        return importlib.reload(function_app)

    yield load
    if original is None:
        os.environ.pop("RUNNER_TYPE", None)
    else:
        os.environ["RUNNER_TYPE"] = original
    importlib.reload(function_app)


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


def test_local_timer_drives_durable_receipts(mocker, queue_app_for) -> None:
    app = queue_app_for("local")
    reconcile = mocker.patch.object(app, "reconcile_local_tasks")
    asyncio.run(app.ReconcileLocalTasks(mocker.Mock()))
    reconcile.assert_called_once_with(app.config)


def test_queue_timer_runs_independently_of_local_staging(mocker) -> None:
    repository = mocker.Mock()
    mocker.patch.object(
        function_app, "JobStateRepository", return_value=repository
    )
    asyncio.run(function_app.ReconcileJobQueues(mocker.Mock()))
    repository.reconcile_queues.assert_called_once_with()


def _functions(module) -> dict:
    # get_functions() remembers the names it validated, so a second call on
    # the same app would report every function as a duplicate.
    module.app.functions_bindings = {}
    return {
        item.get_function_name(): item for item in module.app.get_functions()
    }


def _timer_schedule(name: str, module=function_app) -> str:
    return _functions(module)[name].get_trigger().schedule


def test_lost_message_recovery_scans_every_five_minutes() -> None:
    # Monitors re-enqueue their own polls; this scan only backs up lost
    # messages, and each run reads every job record in the environment.
    assert _timer_schedule("ReconcileJobQueues") == "0 */5 * * * *"


def test_local_task_timer_exists_only_for_local_runs(queue_app_for) -> None:
    local = queue_app_for("local")
    assert _timer_schedule("ReconcileLocalTasks", local) == "*/15 * * * * *"
    batch = _functions(queue_app_for("azure_batch"))
    assert "ReconcileLocalTasks" not in batch
    assert "ReconcileJobQueues" in batch


def test_batch_runtime_never_constructs_local_docker_controller(
    mocker,
) -> None:
    config = mocker.Mock(runner_type="azure_batch")
    docker = mocker.patch(
        "docker.from_env",
        side_effect=AssertionError("Docker must not be used"),
    )
    assert reconcile_local_tasks(config) == 0
    docker.assert_not_called()
