# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from hastegeo.core.models.compute import synthesize_legacy_batch_handle
from hastegeo.core.models.projects import ImageLayer, Model, ModelArtifacts
from hastegeo.core.processors.job_state import (
    RUNTIME_KEY,
    WORKFLOWS,
    JobStateRepository,
    Workload,
    attempt_id,
    current_job,
    persist_and_enqueue,
)


def record(workload: Workload):
    values = {
        "projectId": "project",
        "imageLayerId": "layer",
        "status": "Queued",
        "name": "Original",
        "totalSteps": 2,
    }
    if workload == Workload.IMAGERY:
        return ImageLayer(**values)
    if workload == Workload.ZIP:
        return ModelArtifacts(
            projectId="project", modelId="model", zipStatus="Queued"
        )
    return Model(
        **values,
        modelId="model",
        autoRunInference=False,
        maxEpochs="1",
        modelType="embedding" if workload == Workload.EMBEDDING else "trained",
        inferenceStatus="Queued" if workload == Workload.INFERENCE else None,
        inferenceTotalSteps=7,
    )


def accepted(state, workload: Workload = Workload.TRAINING) -> dict:
    saved = state.repository.begin(workload, record(workload))
    return saved.model_dump(mode="json")


def load(state, workload: Workload = Workload.TRAINING) -> dict:
    return state.repository.processor(workload, "project").load(
        "layer" if workload == Workload.IMAGERY else "model"
    )


def output_for(baseline: dict, workload: Workload, status: str):
    values = deepcopy(baseline)
    values[WORKFLOWS[workload].status] = status
    current_job(values, workload)["status"] = status
    return WORKFLOWS[workload].model.model_validate(values)


@pytest.mark.parametrize("workload", list(Workload))
def test_pending_identity_is_durable_and_replayed(
    state, workload: Workload
) -> None:
    first = accepted(state, workload)
    second = state.repository.begin(workload, record(workload)).model_dump(
        mode="json"
    )
    assert attempt_id(first, workload)
    assert current_job(first, workload)["jobId"] is None
    assert current_job(first, workload)["computeJob"] is None
    assert attempt_id(second, workload) == attempt_id(first, workload)
    assert attempt_id(load(state, workload), workload) == attempt_id(
        first, workload
    )


@pytest.mark.parametrize("workload", list(Workload))
def test_current_claim_serializes_duplicate_queue_messages(
    state, workload: Workload
) -> None:
    message = accepted(state, workload)
    assert state.repository.claim(workload, message) is not None
    assert state.repository.claim(workload, message) is None


def test_concurrent_first_submissions_replay_one_pending_identity(
    state,
) -> None:
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: state.repository.begin(
                    Workload.TRAINING, record(Workload.TRAINING)
                ),
                range(4),
            )
        )
    assert len({item.trainingJob.taskId for item in results}) == 1


@pytest.mark.parametrize("workload", list(Workload))
def test_stale_runtime_updates_preserve_user_edits(
    state, workload: Workload
) -> None:
    message = accepted(state, workload)
    baseline = state.repository.claim(workload, message)
    metadata = state.repository.processor(workload, "project")
    metadata.save(
        message[WORKFLOWS[workload].key],
        {
            "name": "User's new name",
            "description": "New description",
            "batchSize": "11",
            "autoRunInference": False,
        },
    )
    output = output_for(baseline, workload, "InProgress")
    committed = state.repository.commit(workload, baseline, output, [])
    assert committed["name"] == "User's new name"
    assert committed["description"] == "New description"
    assert committed["batchSize"] == "11"
    assert committed[WORKFLOWS[workload].status] == "InProgress"


@pytest.mark.parametrize("terminal", ["Processed", "Failed", "Cancelled"])
def test_terminal_metadata_cannot_be_overwritten_by_a_late_poll(
    state, terminal: str
) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.processor(Workload.TRAINING, "project").save(
        "model", {"status": terminal}
    )
    assert (
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "InProgress"),
            [],
        )
        is None
    )
    assert load(state)["status"] == terminal


@pytest.mark.parametrize("workload", list(Workload))
def test_cancellation_fences_inflight_submission_and_completion(
    state, workload: Workload
) -> None:
    message = accepted(state, workload)
    baseline = state.repository.claim(workload, message)
    state.repository.begin(
        workload,
        WORKFLOWS[workload].model.model_validate(message),
        cancel=True,
    )
    assert (
        state.repository.commit(
            workload, baseline, output_for(baseline, workload, "Processed"), []
        )
        is None
    )
    assert load(state, workload)[WORKFLOWS[workload].status] == "Cancelled"


def test_cancel_claim_cannot_publish_success(state) -> None:
    message = accepted(state)
    cancelled = state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    baseline = state.repository.claim(
        Workload.TRAINING, cancelled.model_dump(mode="json")
    )
    with pytest.raises(ValueError, match="terminal"):
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "Processed"),
            [],
        )


def test_old_attempt_and_old_cancel_cannot_touch_a_new_attempt(state) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    failed = output_for(baseline, Workload.TRAINING, "Failed")
    state.repository.processor(Workload.TRAINING, "project").save(
        "model", failed.model_dump(mode="json")
    )
    new = state.repository.begin(Workload.TRAINING, failed)
    assert new.trainingJob.taskId != message["trainingJob"]["taskId"]
    assert state.repository.claim(Workload.TRAINING, message) is None
    assert (
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "Processed"),
            [],
        )
        is None
    )
    with pytest.raises(ValueError, match="older execution"):
        state.repository.begin(
            Workload.TRAINING, Model.model_validate(message), cancel=True
        )
    assert load(state)["trainingJob"]["taskId"] == new.trainingJob.taskId


def test_expired_claim_recovers_after_restart_and_fences_old_worker(
    state,
) -> None:
    message = accepted(state)
    old = state.repository.claim(Workload.TRAINING, message)
    state.now.value += 301
    restarted = JobStateRepository(state.config, clock=lambda: state.now.value)
    new = restarted.claim(Workload.TRAINING, message)
    assert new is not None
    assert (
        state.repository.commit(
            Workload.TRAINING,
            old,
            output_for(old, Workload.TRAINING, "Processed"),
            [],
        )
        is None
    )
    assert (
        restarted.commit(
            Workload.TRAINING,
            new,
            output_for(new, Workload.TRAINING, "InProgress"),
            [],
        )["status"]
        == "InProgress"
    )


def test_lost_queue_send_leaves_a_recoverable_pending_record(
    state, mocker
) -> None:
    mocker.patch(
        "hastegeo.core.processors.job_state.JobStateRepository",
        return_value=state.repository,
    )
    queue = mocker.Mock()
    queue.put_message.side_effect = OSError("queue unavailable")
    with pytest.raises(OSError):
        persist_and_enqueue(
            record(Workload.TRAINING), Workload.TRAINING, state.config, queue
        )
    assert load(state)["trainingJob"]["taskId"]
    assert state.repository.reconcile_queues() == 1
    assert state.queue.call_args.args[0] == Workload.TRAINING


def test_first_queue_send_observes_already_persisted_identity(
    state, mocker
) -> None:
    mocker.patch(
        "hastegeo.core.processors.job_state.JobStateRepository",
        return_value=state.repository,
    )
    queue = mocker.Mock()

    def check_persistence(body: str, **kwargs) -> None:
        message = json.loads(body)
        assert message["trainingJob"] == load(state)["trainingJob"]
        assert message["status"] == load(state)["status"] == "Queued"

    queue.put_message.side_effect = check_persistence
    saved = persist_and_enqueue(
        record(Workload.TRAINING), Workload.TRAINING, state.config, queue
    )
    assert saved.trainingJob.taskId
    queue.put_message.assert_called_once()


def test_reconciliation_scans_partitioned_metadata_and_skips_active_claims(
    state,
) -> None:
    message = accepted(state)
    state.repository.claim(Workload.TRAINING, message)
    assert state.repository.reconcile_queues() == 0
    state.now.value += 301
    assert state.repository.reconcile_queues() == 1


def test_poison_delivery_does_not_fail_live_compute_or_a_newer_attempt(
    state,
) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.mark_delivery_interrupted(Workload.TRAINING, message)
    assert load(state)["status"] == "Queued"
    assert (
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "InProgress"),
            [],
        )["status"]
        == "InProgress"
    )
    stale = deepcopy(message)
    stale["trainingJob"]["taskId"] = "old-task"
    before = load(state)
    state.repository.mark_delivery_interrupted(Workload.TRAINING, stale)
    assert load(state) == before


def test_deleted_record_is_not_recreated_by_a_late_queue_write(state) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.processor(Workload.TRAINING, "project").delete("model")
    assert (
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "Processed"),
            [],
        )
        is None
    )
    with pytest.raises(FileNotFoundError):
        load(state)


def test_legacy_pending_record_gets_identity_before_processor_runs(
    state,
) -> None:
    message = record(Workload.TRAINING).model_dump(mode="json")
    state.repository.processor(Workload.TRAINING, "project").save(
        "model", message
    )
    claimed = state.repository.claim(Workload.TRAINING, message)
    assert claimed["trainingJob"]["taskId"]
    assert claimed["trainingJob"] == load(state)["trainingJob"]


def test_follow_on_request_is_idempotent_even_after_child_completion(
    state,
) -> None:
    message = accepted(state)
    model = Model.model_validate(message)
    model.status = "Processed"
    state.repository.processor(Workload.TRAINING, "project").save(
        "model", {"status": "Processed"}
    )
    first = state.repository.begin(
        Workload.INFERENCE, model, request_id="parent:inference"
    )
    finished = first.model_dump(mode="json")
    finished["inferenceStatus"] = "Processed"
    current_job(finished, Workload.INFERENCE)["status"] = "Processed"
    state.repository.processor(Workload.INFERENCE, "project").save(
        "model", finished
    )
    second = state.repository.begin(
        Workload.INFERENCE,
        Model.model_validate(finished),
        request_id="parent:inference",
    )
    assert second.currentInferenceTaskId == first.currentInferenceTaskId
    assert len(second.inferenceJobs) == 1
    assert (
        load(state)[RUNTIME_KEY]["inference"]["request_id"]
        == "parent:inference"
    )


def test_queue_recovery_survives_a_changed_default_backend(
    state, mocker
) -> None:
    mocker.patch.dict("os.environ", {"COMPUTE_BACKEND_DEFAULT": "azure_batch"})
    message = accepted(state)
    assert state.repository.reconcile_queues() == 1
    mocker.patch.dict("os.environ", {"COMPUTE_BACKEND_DEFAULT": "local"})
    assert state.repository.reconcile_queues() == 1
    claimed = state.repository.claim(Workload.TRAINING, message)
    assert (
        state.repository.turn(claimed, Workload.TRAINING).backend
        == "azure_batch"
    )


def submission_handle(message: dict):
    return synthesize_legacy_batch_handle(
        job_id="accepted-provider-job",
        task_id=message["trainingJob"]["taskId"],
        output_uri="https://account.blob.core.windows.net/data/project/task",
    )


def test_cancellation_during_submission_retains_the_handle_for_actual_stop(
    state,
) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    handle = submission_handle(message)

    assert state.repository.record_submission(
        Workload.TRAINING, baseline, handle
    )

    current = load(state)
    assert current["status"] == "Cancelled"
    assert current["trainingJob"]["computeJob"] == handle.model_dump(
        mode="json"
    )
    assert current["trainingJob"]["status"] == "InProgress"
    assert state.repository.needs_processing(current, Workload.TRAINING)
    assert (
        state.repository.commit(
            Workload.TRAINING,
            baseline,
            output_for(baseline, Workload.TRAINING, "InProgress"),
            [],
        )
        is None
    )


@pytest.mark.parametrize("status", ["Processed", "Failed", "Cancelled"])
def test_duplicate_submission_handle_does_not_regress_terminal_job(
    state, status: str
) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    handle = submission_handle(message)
    assert state.repository.record_submission(
        Workload.TRAINING, baseline, handle
    )
    current = load(state)
    final = output_for(current, Workload.TRAINING, status)
    state.repository.processor(Workload.TRAINING, "project").save(
        "model", final.model_dump(mode="json")
    )
    before = load(state)

    assert state.repository.record_submission(
        Workload.TRAINING, baseline, handle
    )
    assert load(state) == before


def test_renewed_claim_can_commit_after_its_original_deadline(state) -> None:
    baseline = state.repository.claim(Workload.TRAINING, accepted(state))
    state.now.value += 250
    assert state.repository.renew_claim(Workload.TRAINING, baseline)
    state.now.value += 100
    result = state.repository.commit(
        Workload.TRAINING,
        baseline,
        output_for(baseline, Workload.TRAINING, "InProgress"),
        [],
    )
    assert result is not None


def test_cancelled_claim_cannot_be_renewed_by_the_old_worker(state) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.begin(
        Workload.TRAINING, Model.model_validate(message), cancel=True
    )
    assert not state.repository.renew_claim(Workload.TRAINING, baseline)


def test_distinct_follow_on_waits_instead_of_acknowledging_busy_target(
    state,
) -> None:
    message = accepted(state)
    with pytest.raises(RuntimeError, match="follow-on work"):
        state.repository.begin(
            Workload.TRAINING,
            Model.model_validate(message),
            request_id="another-parent-request",
        )
    assert attempt_id(load(state), Workload.TRAINING) == attempt_id(
        message, Workload.TRAINING
    )


def test_submission_after_record_deletion_is_rejected_without_recreation(
    state,
) -> None:
    message = accepted(state)
    baseline = state.repository.claim(Workload.TRAINING, message)
    state.repository.processor(Workload.TRAINING, "project").delete("model")
    assert not state.repository.record_submission(
        Workload.TRAINING, baseline, submission_handle(message)
    )
    with pytest.raises(FileNotFoundError):
        load(state)
