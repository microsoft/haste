# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
from importlib import import_module

import pytest
from hastegeo.core.models.projects import Model
from hastegeo.core.processors.job_state import WORKFLOWS, Workload, current_job
from hastegeo.core.runners.submission import TaskSubmissionPendingError
from hastegeo.core.utils.metadata import MetadataUtils

from hastelib.tests.core.processors.test_job_state import (
    accepted,
    load,
    record,
)

PROCESSORS = [
    (
        Workload.TRAINING,
        "train",
        "TrainPostprocessor",
        "_execute_training",
        "_create_experiment_config",
    ),
    (
        Workload.INFERENCE,
        "inference",
        "InferencePostprocessor",
        "_execute_inference",
        "_create_inference_config",
    ),
    (
        Workload.EMBEDDING,
        "embedding",
        "EmbeddingPostprocessor",
        "_execute_embedding",
        "_create_embedding_config",
    ),
    (
        Workload.IMAGERY,
        "imagery",
        "ImageryPostProcessor",
        "_execute_image_preprocess",
        None,
    ),
    (
        Workload.ZIP,
        "artifacts",
        "ArtifactProcessor",
        "submit_zip_job",
        "prepare_zip_job",
    ),
]


@pytest.mark.parametrize(
    "workload,module_name,class_name,method,prepare", PROCESSORS
)
@pytest.mark.parametrize("submission_fails", [False, True])
def test_processors_reuse_pending_ids_and_accept_batch_routed_job_ids(
    state,
    mocker,
    workload: Workload,
    module_name: str,
    class_name: str,
    method: str,
    prepare: str | None,
    submission_fails: bool,
) -> None:
    message = accepted(state, workload)
    model = WORKFLOWS[workload].model.model_validate(message)
    if workload == Workload.INFERENCE:
        model.inferenceTotalSteps = 7
    pending = current_job(message, workload)
    module = import_module(f"hastegeo.core.processors.{module_name}")
    runner = mocker.Mock(config=state.config)
    runner.add_task.return_value = ("routed-job", pending["taskId"])
    if submission_fails:
        runner.add_task.side_effect = OSError("provider response lost")
    mocker.patch.object(module, "UnifiedRunner", return_value=runner)
    storage_type = (
        "UnifiedArtifactStorage"
        if workload == Workload.ZIP
        else "UnifiedDataLayer"
    )
    storage = mocker.patch.object(module, storage_type).return_value
    storage.get_file_remote_path.return_value = (
        "https://account.blob.core.windows.net/data/"
        f"{MetadataUtils.hash_string('project')}/config.yaml?unit-test"
    )
    if workload == Workload.ZIP:
        processor = module.ArtifactProcessor(
            config=state.config,
            partition_key="project",
            model_artifacts=model,
            model=Model(projectId="project", modelId="model", name="name"),
        )
    else:
        processor = getattr(module, class_name)(model, config=state.config)
    if prepare:
        mocker.patch.object(
            processor,
            prepare,
            return_value={"config": {"file_path": "inputs/config.yaml"}},
        )

    if submission_fails:
        with pytest.raises(TaskSubmissionPendingError):
            getattr(processor, method)()
        assert (
            current_job(model.model_dump(mode="json"), workload)["taskId"]
            == pending["taskId"]
        )
        assert (
            model.model_dump(mode="json")[WORKFLOWS[workload].status]
            == "Queued"
        )
        return
    output = getattr(processor, method)()

    assert runner.add_task.call_count == 1
    assert runner.add_task.call_args.kwargs["job_id"] == pending["jobId"]
    assert runner.add_task.call_args.kwargs["task_id"] == pending["taskId"]
    values = output.model_dump(mode="json")
    assert current_job(values, workload)["jobId"] == "routed-job"
    assert current_job(values, workload)["taskId"] == pending["taskId"]
    assert values[WORKFLOWS[workload].status] == "InProgress"
    if WORKFLOWS[workload].current_task:
        assert len(values[WORKFLOWS[workload].job]) == 1


@pytest.mark.parametrize(
    "workload,module_name,class_name,method",
    [
        (Workload.TRAINING, "train", "TrainPreprocessor", "send_to_queue"),
        (
            Workload.INFERENCE,
            "inference",
            "InferencePreprocessor",
            "send_to_queue",
        ),
        (
            Workload.EMBEDDING,
            "embedding",
            "EmbeddingPreprocessor",
            "send_to_queue",
        ),
        (
            Workload.IMAGERY,
            "imagery",
            "ImageryPreProcessor",
            "queue_for_processing",
        ),
        (Workload.ZIP, "artifacts", "ArtifactProcessor", "send_to_zip_queue"),
    ],
)
def test_every_preprocessor_persists_identity_before_sending_a_message(
    state,
    mocker,
    workload: Workload,
    module_name: str,
    class_name: str,
    method: str,
) -> None:
    module = import_module(f"hastegeo.core.processors.{module_name}")
    queue = mocker.patch.object(module, "AzureQueueHandler").return_value
    if workload == Workload.ZIP:
        mocker.patch.object(module, "UnifiedArtifactStorage")
        mocker.patch.object(module, "UnifiedRunner")
        processor = module.ArtifactProcessor(
            config=state.config,
            partition_key="project",
            model_artifacts=record(workload),
        )
    else:
        processor = getattr(module, class_name)(
            record(workload), config=state.config
        )

    def assert_durable(body: str, **kwargs) -> None:
        message = json.loads(body)
        assert current_job(message, workload)["taskId"]
        assert current_job(message, workload) == current_job(
            load(state, workload), workload
        )
        assert load(state, workload)[WORKFLOWS[workload].status] == "Queued"

    queue.put_message.side_effect = assert_durable
    getattr(processor, method)()
    queue.put_message.assert_called_once()
