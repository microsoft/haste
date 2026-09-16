# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

from copy import deepcopy

import pytest
from hastegeo.core.models.compute import (
    ComputeJobHandle,
    ComputeJobState,
    synthesize_legacy_batch_handle,
)
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


def submitted(state) -> tuple[dict, ComputeJobHandle]:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    handle = synthesize_legacy_batch_handle(
        job_id="submitted-job",
        task_id=message["trainingJob"]["taskId"],
        output_uri="https://account.blob.core.windows.net/data/project/task",
    )
    assert state.repository.record_submission(
        Workload.TRAINING, baseline, handle
    )
    state.repository.release(Workload.TRAINING, baseline)
    return load(state), handle


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
    message, handle = submitted(state)
    processor = JobQueueProcessor(state.config, repository=state.repository)
    mocker.patch.object(
        processor,
        "_process_current",
        side_effect=lambda workload, data: (
            output_for(data, workload, "Processed"),
            [
                TaskIdentity(
                    job_id=handle.providerJobId,
                    task_id=handle.providerTaskId,
                    handle=handle,
                )
            ],
        ),
    )
    service = mocker.Mock()

    def cleanup(actual: ComputeJobHandle) -> None:
        assert load(state)["status"] == "Processed"
        assert load(state)["trainingJob"]["taskId"] == actual.providerTaskId

    service.finalize.side_effect = cleanup
    mocker.patch.object(processor, "execution_service", service)
    processor.process(Workload.TRAINING, message)
    service.finalize.assert_called_once_with(handle)
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
    service = mocker.patch.object(processor, "execution_service")
    processor.process(Workload.TRAINING, message)
    service.finalize.assert_not_called()
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
    assert state.repository.turn(load(state), Workload.TRAINING).error is None
    assert (
        "Deferred inference action completed" in load(state)["statusMessage"]
    )


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
    message, handle = submitted(state)
    cancelled = state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    service = mocker.patch.object(processor, "execution_service")
    service.get_status.side_effect = [
        ComputeJobState.RUNNING,
        ComputeJobState.CANCELLED,
    ]
    mocker.patch.object(processor, "_perform_action")
    processor.process(Workload.TRAINING, cancelled.model_dump(mode="json"))
    service.cancel.assert_called_once_with(handle)
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] == "Cancelled"


def test_cancel_failure_keeps_the_intent_and_retries_actual_stop(
    state, mocker
) -> None:
    message, _ = submitted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, repository=state.repository)
    service = mocker.patch.object(processor, "execution_service")
    service.get_status.return_value = ComputeJobState.RUNNING
    service.cancel.side_effect = OSError("Provider unavailable")
    with pytest.raises(OSError):
        processor.process(Workload.TRAINING, message)
    assert load(state)["status"] == "Cancelled"
    assert load(state)["trainingJob"]["status"] != "Cancelled"
    state.now.value += 31
    assert state.repository.reconcile_queues() == 1


def test_cancel_does_not_misreport_an_already_completed_provider_job(
    state, mocker
) -> None:
    message, handle = submitted(state)
    cancelled = state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, state.repository)
    service = mocker.patch.object(processor, "execution_service")
    service.get_status.return_value = ComputeJobState.SUCCEEDED
    mocker.patch.object(processor, "_perform_action")
    processor.process(Workload.TRAINING, cancelled.model_dump(mode="json"))
    service.cancel.assert_not_called()
    service.finalize.assert_called_once_with(handle)
    assert load(state)["trainingJob"]["status"] == "Processed"
    assert "already reached Processed" in load(state)["statusMessage"]
    assert not state.repository.needs_cancellation(
        load(state), Workload.TRAINING
    )


def test_cancel_waits_for_the_provider_to_become_terminal(
    state, mocker
) -> None:
    message, _ = submitted(state)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    processor = JobQueueProcessor(state.config, state.repository)
    service = mocker.patch.object(processor, "execution_service")
    service.get_status.return_value = ComputeJobState.RUNNING
    with pytest.raises(RuntimeError, match="waiting for provider"):
        processor.process(Workload.TRAINING, message)
    service.finalize.assert_not_called()
    assert state.repository.needs_cancellation(load(state), Workload.TRAINING)


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
    runner = local.LocalRunner(config=state.config)
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
