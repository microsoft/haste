# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
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
from hastegeo.core.utils.metadata import MetadataUtils

from hastelib.tests.core.processors.test_job_state import (
    accepted,
    load,
    output_for,
    record,
)
from hastelib.tests.core.runners.test_local_lifecycle import (
    FakeBlobs,
    FakeDocker,
)


@pytest.mark.parametrize("workload", list(Workload))
def test_queue_uses_current_metadata_not_the_message_snapshot(
    state, mocker, workload: Workload
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
    with pytest.raises(ConnectionError):
        processor.process(Workload.TRAINING, message)
    current = load(state)
    assert current["status"] == "Queued"
    assert "reconciliation pending" in current["statusMessage"]
    state.now.value += 31
    assert state.repository.reconcile_queues() == 1


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
    with pytest.raises(OSError):
        processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Processed"
    assert state.repository.turn(load(state), Workload.TRAINING).actions
    action.side_effect = None
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
    with pytest.raises(OSError):
        processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] != "Cancelled"
    state.now.value += 31
    assert state.repository.reconcile_queues() == 1


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
