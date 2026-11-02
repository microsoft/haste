# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from azure.batch.models import TaskState
from hastegeo.core.models.projects import Model
from hastegeo.core.processors.job_queue import JobQueueProcessor
from hastegeo.core.processors.job_state import (
    WORKFLOWS,
    TaskIdentity,
    Workload,
    current_job,
)
from hastegeo.core.processors.metadata import MetadataProcessor
from hastegeo.core.processors.train import TrainPostprocessor
from hastegeo.core.runners import local
from hastegeo.core.runners.azure_batch import AzureBatchJob, AzureBatchRunner
from hastegeo.core.runners.base import TaskMissingError
from hastegeo.core.utils.metadata import (
    MAX_STATUS_MESSAGE_BYTES,
    STATUS_HISTORY_TRIMMED,
    MetadataUtils,
)

from hastelib.tests.core.processors.test_job_state import (
    accepted,
    load,
    output_for,
    record,
)
from hastelib.tests.core.runners.test_azure_batch_node_errors import (
    _batch_error,
)
from hastelib.tests.core.runners.test_local_lifecycle import (
    FakeBlobs,
    FakeDocker,
)


class RecordingPredictionLock:
    def __init__(
        self,
        calls: list[tuple[str, str, str]],
        source: str,
        project: str,
        model: str,
    ) -> None:
        self.calls = calls
        self.source = source
        self.project = project
        self.model = model

    def __enter__(self) -> "RecordingPredictionLock":
        self.calls.append((self.source, self.project, self.model))
        return self

    def __exit__(self, *args) -> None:
        return None

    def renew(self) -> None:
        pass


@pytest.fixture(autouse=True)
def prediction_locks(mocker) -> list[tuple[str, str, str]]:
    calls: list[tuple[str, str, str]] = []

    def lock(source: str):
        def acquire(config, project_id: str, model_id: str):
            return RecordingPredictionLock(calls, source, project_id, model_id)

        return acquire

    mocker.patch(
        "hastegeo.core.processors.inference.prediction_edit_lock",
        new=lock("start"),
    )
    mocker.patch(
        "hastegeo.core.processors.job_queue.prediction_edit_lock",
        new=lock("commit"),
    )
    return calls


def in_progress(state, workload: Workload) -> dict:
    """Persist an accepted execution whose compute task is running."""
    message = accepted(state, workload)
    if workload == Workload.ZIP:
        state.repository.processor(Workload.TRAINING, "project").save(
            "model", {"projectId": "project", "modelId": "model"}
        )
    baseline = state.repository.claim(workload, message)
    committed = state.repository.commit(
        workload, baseline, output_for(baseline, workload, "InProgress"), []
    )
    state.repository.release(workload, committed)
    return load(state, workload)


def save_training_inputs(state) -> None:
    for data_type, identifier, contents in [
        (
            state.config.get_metadata_types().IMAGELAYER.value,
            "layer",
            {
                "projectId": "project",
                "imageLayerId": "layer",
            },
        ),
        (
            state.config.get_metadata_types().LABELS.value,
            "labels",
            {
                "projectId": "project",
                "imageLayerId": "layer",
                "labelprojectId": "labels",
            },
        ),
        (
            state.config.get_metadata_types().PROJECT.value,
            "project",
            {"projectId": "project"},
        ),
    ]:
        MetadataProcessor(data_type, "project", config=state.config).save(
            identifier, contents
        )


@pytest.mark.parametrize("workload", list(Workload))
def test_queue_uses_current_metadata_not_the_message_snapshot(
    state,
    mocker,
    prediction_locks: list[tuple[str, str, str]],
    workload: Workload,
) -> None:
    message = accepted(state, workload)
    if workload == Workload.ZIP:
        state.repository.processor(Workload.TRAINING, "project").save(
            "model", {"projectId": "project", "modelId": "model"}
        )
    state.repository.processor(workload, "project").save(
        message[WORKFLOWS[workload].key], {"name": "New user edit"}
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)

    def run(current_workload: Workload, baseline: dict):
        assert baseline["name"] == "New user edit"
        return output_for(baseline, current_workload, "InProgress"), []

    mocker.patch.object(processor, "_process_current", side_effect=run)
    processor.process(workload, message)
    assert load(state, workload)["name"] == "New user edit"
    assert load(state, workload)[WORKFLOWS[workload].status] == "InProgress"
    state.queue.assert_called_once()
    if workload == Workload.INFERENCE:
        assert ("commit", "project", "model") in prediction_locks


def test_cleanup_only_runs_after_the_terminal_metadata_commit(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(
        processor,
        "_process_current",
        side_effect=lambda workload, data: (
            output_for(data, workload, "Processed"),
            [
                TaskIdentity(
                    job_id="job", task_id=message["trainingJob"]["taskId"]
                )
            ],
        ),
    )
    runner = mocker.Mock()

    def cleanup(job_id: str, task_id: str) -> None:
        assert load(state)["status"] == "Processed"
        assert load(state)["trainingJob"]["taskId"] == task_id

    runner.cleanup_task.side_effect = cleanup
    mocker.patch.object(processor, "_runner", return_value=runner)
    processor.process(Workload.TRAINING, message)
    runner.cleanup_task.assert_called_once()
    assert state.repository.turn(load(state), Workload.TRAINING).cleanup == []


def test_cancellation_during_a_poll_prevents_late_cleanup_and_completion(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)

    def racing_poll(workload: Workload, baseline: dict):
        state.repository.begin(
            workload, Model.model_validate(message), cancel=True
        )
        return output_for(baseline, workload, "Processed"), [
            TaskIdentity(
                job_id="job", task_id=message["trainingJob"]["taskId"]
            )
        ]

    mocker.patch.object(processor, "_process_current", side_effect=racing_poll)
    runner = mocker.patch.object(processor, "_runner")
    processor.process(Workload.TRAINING, message)
    runner.assert_not_called()
    assert load(state)["status"] == "Cancelled"


def test_lost_poll_delivery_recovers_from_persisted_runtime(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(
        processor,
        "_process_current",
        side_effect=lambda workload, data: (
            output_for(data, workload, "InProgress"),
            [],
        ),
    )
    state.queue.side_effect = OSError("queue unavailable")
    with pytest.raises(OSError):
        processor.process(Workload.TRAINING, message)
    current = load(state)
    assert current["status"] == "InProgress"
    assert (
        "interrupted"
        in state.repository.turn(current, Workload.TRAINING).error
    )
    state.queue.side_effect = None
    assert state.repository.reconcile_queues() == 1


def test_worker_error_is_durable_and_does_not_claim_compute_failed(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(
        processor,
        "_process_current",
        side_effect=ConnectionError("provider temporarily unavailable"),
    )
    # The failure is recorded with a backoff, so the delivery is not retried
    # by the Functions host or sent to the poison queue.
    processor.process(Workload.TRAINING, message)
    current = load(state)
    assert current["status"] == "Queued"
    assert "reconciliation pending" in current["statusMessage"]
    state.now.value += 31
    assert state.repository.reconcile_queues() == 1


def test_repeated_processing_errors_back_off_with_one_status_line(
    state, mocker
) -> None:
    message = in_progress(state, Workload.TRAINING)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    work = mocker.patch.object(
        processor,
        "_process_current",
        side_effect=FileNotFoundError("Training label project is missing"),
    )
    delays = []
    for attempt in range(1, 10):
        processor.process(Workload.TRAINING, message)
        assert work.call_count == attempt
        turn = state.repository.turn(load(state), Workload.TRAINING)
        delays.append(turn.next_poll - state.now.value)
        # A duplicate delivery during the backoff does not run the job again.
        processor.process(Workload.TRAINING, message)
        assert work.call_count == attempt
        assert state.repository.reconcile_queues() == 0
        state.now.value = turn.next_poll
        assert state.repository.reconcile_queues() == 1
    assert delays == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600]
    current = load(state)
    assert current["status"] == "InProgress"
    assert current["statusMessage"].count("Job processing interrupted") == 1

    work.side_effect = lambda workload, data: (
        output_for(data, workload, "InProgress"),
        [],
    )
    processor.process(Workload.TRAINING, message)
    turn = state.repository.turn(load(state), Workload.TRAINING)
    assert (turn.failures, turn.error) == (0, None)
    # Normal polling resumes on its usual 30-second visibility delay.
    state.now.value += 30
    processor.process(Workload.TRAINING, message)
    assert work.call_count == 11


def test_cancellation_is_not_delayed_by_an_error_backoff(
    state, mocker
) -> None:
    message = in_progress(state, Workload.TRAINING)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    real = processor._process_current

    def flaky(workload: Workload, baseline: dict):
        if baseline["status"] != "Cancelled":
            raise OSError("storage unavailable")
        return real(workload, baseline)

    mocker.patch.object(processor, "_process_current", side_effect=flaky)
    runner = mocker.Mock()
    runner.cancel_task.return_value = True
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")
    processor.process(Workload.TRAINING, message)
    assert state.repository.turn(load(state), Workload.TRAINING).failures == 1

    cancelled = state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor.process(Workload.TRAINING, cancelled.model_dump(mode="json"))

    runner.cancel_task.assert_called_once()
    assert load(state)["trainingJob"]["status"] == "Cancelled"


def test_failed_follow_on_delivery_retries_without_repeating_compute(
    state, mocker
) -> None:
    model = record(Workload.TRAINING)
    model.autoRunInference = True
    message = state.repository.begin(Workload.TRAINING, model).model_dump(
        mode="json"
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    compute = mocker.patch.object(
        processor,
        "_process_current",
        side_effect=lambda workload, data: (
            output_for(data, workload, "Processed"),
            [],
        ),
    )
    action = mocker.patch.object(
        processor, "_perform_action", side_effect=OSError("queue failed")
    )
    processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Processed"
    assert state.repository.turn(load(state), Workload.TRAINING).actions
    action.side_effect = None
    state.now.value += 31
    processor.process(Workload.TRAINING, message)
    assert compute.call_count == 1
    assert action.call_count == 2
    assert not state.repository.turn(load(state), Workload.TRAINING).actions


def test_duplicate_terminal_message_has_no_follow_on_side_effects(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    work = mocker.patch.object(
        processor,
        "_process_current",
        side_effect=lambda workload, data: (
            output_for(data, workload, "Processed"),
            [],
        ),
    )
    processor.process(Workload.TRAINING, message)
    processor.process(Workload.TRAINING, message)
    work.assert_called_once()


def test_malformed_queue_message_is_rejected_without_echoing_payload(
    state,
) -> None:
    processor = JobQueueProcessor(state.config, repository=state.repository)
    with pytest.raises(RuntimeError, match="JSONDecodeError") as error:
        processor.process_message(Workload.TRAINING, b"secret-content")
    assert "secret-content" not in str(error.value)


def test_cancel_invocation_stops_persisted_identity_not_stale_payload(
    state, mocker
) -> None:
    message = accepted(state)
    cancelled = state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")
    processor.process(Workload.TRAINING, cancelled.model_dump(mode="json"))
    runner.cancel_task.assert_called_once_with(
        message["trainingJob"]["jobId"], message["trainingJob"]["taskId"]
    )
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] == "Cancelled"


def test_cancel_failure_keeps_the_intent_and_retries_actual_stop(
    state, mocker
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    runner.cancel_task.side_effect = OSError("Docker unavailable")
    mocker.patch.object(processor, "_runner", return_value=runner)
    processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] != "Cancelled"
    state.now.value += 31
    assert state.repository.reconcile_queues() == 1


@pytest.mark.parametrize("stopped", [True, False])
def test_training_cancellation_commits_history_before_summary_and_cleanup(
    state, mocker, stopped: bool
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    runner.cancel_task.return_value = stopped
    runner.get_task_status.return_value = "Processed"
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")
    summary = (
        "Task cancelled"
        if stopped
        else "Task already reached Processed before cancellation"
    )

    def read_output(
        job_id: str,
        task_id: str,
        filename: str,
        as_chunk: bool = False,
    ) -> str:
        runner.cancel_task.assert_called_once()
        runner.cleanup_task.assert_not_called()
        assert filename == "workflow_progress.log"
        return (
            "2026-01-01T00:00:00+00:00|Starting create_masks.py\n"
            "2026-01-01T00:01:00+00:00|Completed create_masks.py\n"
        )

    def cleanup(job_id: str, task_id: str) -> None:
        persisted = load(state)
        assert persisted["status"] == "Cancelled"
        assert persisted["trainingJob"]["status"] == (
            "Cancelled" if stopped else "Processed"
        )
        history = persisted["statusMessage"]
        assert (
            history.index("Starting create_masks.py")
            < history.index("Completed create_masks.py")
            < history.index(summary)
        )

    runner.get_filecontent_from_task.side_effect = read_output
    runner.cleanup_task.side_effect = cleanup

    processor.process(Workload.TRAINING, message)

    runner.get_filecontent_from_task.assert_called_once_with(
        job_id=message["trainingJob"]["jobId"],
        task_id=message["trainingJob"]["taskId"],
        filename="workflow_progress.log",
        as_chunk=False,
    )
    runner.cleanup_task.assert_called_once_with(
        message["trainingJob"]["jobId"], message["trainingJob"]["taskId"]
    )
    assert state.repository.turn(load(state), Workload.TRAINING).cleanup == []


def test_training_cancellation_history_stays_within_the_status_budget(
    state, mocker
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    runner.cancel_task.return_value = True
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runner.get_filecontent_from_task.return_value = "".join(
        f"{(start + timedelta(seconds=index)).isoformat()}|"
        f"Completed workflow stage {index:04d}\n"
        for index in range(400)
    )
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")

    processor.process(Workload.TRAINING, message)

    history = load(state)["statusMessage"]
    assert len(history.encode("utf-8")) <= MAX_STATUS_MESSAGE_BYTES
    assert MetadataUtils.trim_status_message(history) == history
    assert STATUS_HISTORY_TRIMMED in history
    assert "Completed workflow stage 0000" not in history
    assert history.index("Completed workflow stage 0399") < history.index(
        "Task cancelled"
    )
    assert history.endswith("Task cancelled")


@pytest.mark.parametrize(
    "output", [RuntimeError("private provider detail"), b"not text"]
)
def test_unavailable_cancellation_history_preserves_terminal_commit(
    state, mocker, output: RuntimeError | bytes
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    processor.logger = mocker.Mock()
    runner = mocker.Mock()
    if isinstance(output, Exception):
        runner.get_filecontent_from_task.side_effect = output
    else:
        runner.get_filecontent_from_task.return_value = output
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")

    processor.process(Workload.TRAINING, message)

    persisted = load(state)
    assert persisted["status"] == "Cancelled"
    assert persisted["trainingJob"]["status"] == "Cancelled"
    assert "Task cancelled" in persisted["statusMessage"]
    assert "private provider detail" not in persisted["statusMessage"]
    processor.logger.warning.assert_called_once()
    runner.cleanup_task.assert_called_once()


def test_training_queue_and_local_lifecycle_publish_inflight_then_persisted_terminal_state(
    state, mocker
) -> None:
    engine, blobs = FakeDocker(), FakeBlobs()
    mocker.patch.object(local, "TASK_WORK_DIR", state.root / "tasks")
    mocker.patch.object(local.docker, "from_env", return_value=engine)
    mocker.patch.object(
        local.BlobServiceClient, "from_connection_string", return_value=blobs
    )
    mocker.patch.dict(
        "os.environ",
        {
            "HASTE_ENABLE_GPU": "0",
            "CLEANUP_CONTAINERS": "1",
            "PRESERVE_LOCAL_TASK_DIRS": "0",
        },
    )
    batch = state.config.get_azure_batch_config()
    mocker.patch.object(
        state.config,
        "get_azure_batch_config",
        return_value={
            **batch,
            "training_batch_job_id": "training-job",
        },
    )
    runner = local.LocalRunner(config=state.config)
    mocker.patch(
        "hastegeo.core.processors.train.UnifiedRunner", return_value=runner
    )
    blobs.inputs[("data", "config.yaml")] = b"training: {}"
    mocker.patch.object(
        TrainPostprocessor,
        "_create_experiment_config",
        return_value={
            "config": {
                "http_url": "https://account.blob.core.windows.net/data/config.yaml",
                "file_path": "inputs/config.yaml",
            }
        },
    )
    mocker.patch.object(
        TrainPostprocessor, "_get_training_logs", return_value=(None, None)
    )
    save_training_inputs(state)
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(processor, "_runner", return_value=runner)

    processor.process(Workload.TRAINING, message)
    identity = current_job(load(state), Workload.TRAINING)
    ids = identity["jobId"], identity["taskId"]
    assert load(state)["status"] == "InProgress"
    assert runner.get_task_receipt(*ids)["phase"] == "queued"
    assert engine.executions() == []

    runner.reconcile_tasks()
    assert engine.executions()[0].status == "running"
    processor.process(Workload.TRAINING, deepcopy(message))
    assert load(state)["status"] == "InProgress"
    assert engine.executions()[0].starts == 1

    engine.executions()[0].complete()
    runner.reconcile_tasks()
    processor.process(Workload.TRAINING, deepcopy(message))
    completed = load(state)
    assert completed["status"] == "Processed"
    assert completed["checkpointPath"] == (
        f"{MetadataUtils.hash_string('project')}/{ids[1]}/checkpoint"
    )
    assert runner.get_task_receipt(*ids)["outputs_persisted"]
    assert runner.get_task_receipt(*ids)["files_cleaned"]


def test_long_finalization_renews_only_the_persisted_claim(
    state, mocker
) -> None:
    message = accepted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    state.repository.renewal_interval_seconds = 0.01
    started, renewed, release = Event(), Event(), Event()
    original = state.repository.renew_claim

    def renew(workload: Workload, baseline: dict) -> bool:
        result = original(workload, baseline)
        if state.now.value >= 1250:
            renewed.set()
        return result

    def slow_work(workload: Workload, baseline: dict):
        started.set()
        assert release.wait(5)
        return output_for(baseline, workload, "InProgress"), []

    mocker.patch.object(state.repository, "renew_claim", side_effect=renew)
    mocker.patch.object(processor, "_process_current", side_effect=slow_work)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(processor.process, Workload.TRAINING, message)
        try:
            assert started.wait(5)
            state.now.value = 1250
            assert renewed.wait(5)
            state.now.value = 1350
        finally:
            release.set()
        future.result(timeout=5)
    assert load(state)["status"] == "InProgress"


def test_late_cancel_records_actual_terminal_provider_state(
    state, mocker
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    runner.cancel_task.return_value = False
    runner.get_task_status.return_value = "Processed"
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")
    processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] == "Processed"
    assert "before cancellation" in load(state)["statusMessage"]
    assert not state.repository.needs_cancellation(
        load(state), Workload.TRAINING
    )


def test_completed_batch_task_keeps_its_outcome_when_cancelled_late(
    state, mocker
) -> None:
    message = accepted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    cluster = AzureBatchJob.__new__(AzureBatchJob)
    cluster.batch_client = mocker.Mock()
    cluster.logger = mocker.Mock()
    cluster.batch_client.task.terminate.side_effect = _batch_error(
        "TaskCompleted"
    )
    cluster.batch_client.task.get.return_value = SimpleNamespace(
        state=TaskState.completed,
        execution_info=SimpleNamespace(failure_info=None),
    )
    runner = AzureBatchRunner.__new__(AzureBatchRunner)
    runner.batch_cluster = cluster
    runner.config = state.config
    mocker.patch.object(runner, "cleanup_task")
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")

    processor.process(Workload.TRAINING, message)

    completed = state.config.get_status_types().COMPLETED.value
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] == completed
    assert load(state)["statusMessage"].endswith(
        f"Task already reached {completed} before cancellation"
    )
    runner.cleanup_task.assert_called_once()


@pytest.mark.parametrize("workload", list(Workload))
def test_missing_compute_task_fails_the_job_in_one_turn(
    state, mocker, workload: Workload
) -> None:
    message = in_progress(state, workload)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(
        processor,
        "_process_current",
        side_effect=TaskMissingError("Batch task no longer exists"),
    )
    runner = mocker.patch.object(processor, "_runner")

    processor.process(workload, message)

    current = load(state, workload)
    workflow = WORKFLOWS[workload]
    job = current_job(current, workload)
    assert current[workflow.status] == "Failed"
    assert job["status"] == "Failed"
    assert job["completedDate"]
    assert "no longer exists" in current[workflow.message]
    assert not state.repository.needs_processing(current, workload)
    runner.assert_not_called()
    state.queue.assert_not_called()


def test_task_missing_during_a_late_cancellation_stays_cancelled(
    state, mocker
) -> None:
    message = in_progress(state, Workload.TRAINING)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    runner = mocker.Mock()
    runner.cancel_task.return_value = False
    runner.get_task_status.side_effect = TaskMissingError("gone")
    mocker.patch.object(processor, "_runner", return_value=runner)
    mocker.patch.object(processor, "_perform_action")

    processor.process(Workload.TRAINING, message)

    current = load(state)
    assert current["status"] == "Cancelled"
    assert current["trainingJob"]["status"] == "Cancelled"
    assert current["trainingJob"]["completedDate"]
    assert not state.repository.needs_processing(current, Workload.TRAINING)
    runner.cleanup_task.assert_not_called()


def test_training_whose_batch_task_was_deleted_fails_instead_of_retrying(
    state, mocker
) -> None:
    cluster = mocker.Mock()
    cluster.is_task_succeeded.side_effect = _batch_error(
        "TaskNotFound", status_code=404
    )
    batch = AzureBatchRunner.__new__(AzureBatchRunner)
    batch.batch_cluster = cluster
    batch.config = state.config
    batch.logger = mocker.Mock()
    mocker.patch(
        "hastegeo.core.processors.train.UnifiedRunner", return_value=batch
    )
    save_training_inputs(state)
    message = in_progress(state, Workload.TRAINING)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    cleanup = mocker.patch.object(processor, "_runner")

    processor.process(Workload.TRAINING, message)

    current = load(state)
    assert current["status"] == "Failed"
    assert current["trainingJob"]["status"] == "Failed"
    assert current["trainingJob"]["completedDate"]
    assert current["statusMessage"].count("no longer exists") == 1
    assert not state.repository.needs_processing(current, Workload.TRAINING)
    cleanup.assert_not_called()
    state.queue.assert_not_called()
