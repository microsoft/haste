# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import pytest
from azure.batch.models import BatchErrorException
from hastegeo.core.runners.azure_batch import AzureBatchRunner

from hastelib.tests.core.runners.test_azure_batch_node_errors import (
    _batch_error,
)


@pytest.fixture
def runner(mocker) -> AzureBatchRunner:
    mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("Unit test attempted network access"),
    )
    instance = AzureBatchRunner.__new__(AzureBatchRunner)
    instance.batch_cluster = mocker.Mock()
    instance.logger = mocker.Mock()
    instance.candidate_pool_ids = ["pool-a", "pool-b"]
    instance.manage_pools = False
    instance.batch_config = {
        "docker_image": "image",
        "command": "run",
        "arguments": "",
        "output_container_url": "https://account.blob.core.windows.net/data",
        "docker_container_work_dir": "/app",
        "account_name": "account",
        "batch_url": "https://batch.example.invalid",
        "task_retention_time": 30,
    }
    instance.batch_cluster.create_job.side_effect = lambda job_id: job_id
    instance.batch_cluster.select_pool.return_value = "pool-a"
    return instance


def test_replay_recovers_an_existing_task_before_rerouting(runner) -> None:
    def lookup(job_id: str, task_id: str) -> object:
        if job_id == "training-pool-b":
            return object()
        raise _batch_error("TaskNotFound", 404)

    runner.batch_cluster.batch_client.task.get.side_effect = lookup
    assert runner.add_task("training", "task") == ("training-pool-b", "task")
    runner.batch_cluster.select_pool.assert_not_called()
    runner.batch_cluster.add_task.assert_not_called()


def test_missing_task_still_uses_existing_capacity_routing(runner) -> None:
    runner.batch_cluster.batch_client.task.get.side_effect = _batch_error(
        "JobNotFound", 404
    )
    assert runner.add_task("training", "task") == ("training-pool-a", "task")
    runner.batch_cluster.select_pool.assert_called_once_with(
        ["pool-a", "pool-b"]
    )
    runner.batch_cluster.add_task.assert_called_once()


def test_task_exists_race_replays_the_same_batch_identity(runner) -> None:
    runner.batch_cluster.batch_client.task.get.side_effect = [
        _batch_error("TaskNotFound", 404),
        _batch_error("TaskNotFound", 404),
        _batch_error("TaskNotFound", 404),
        object(),
    ]
    runner.batch_cluster.add_task.side_effect = _batch_error("TaskExists", 409)
    assert runner.add_task("training", "task") == ("training-pool-a", "task")
    runner.batch_cluster.batch_client.task.get.assert_called_with(
        "training-pool-a", "task"
    )


def test_batch_lookup_failure_is_not_treated_as_missing_work(runner) -> None:
    runner.batch_cluster.batch_client.task.get.side_effect = _batch_error(
        "AuthorizationFailure", 403
    )
    with pytest.raises(BatchErrorException):
        runner.add_task("training", "task")
    runner.batch_cluster.select_pool.assert_not_called()
    runner.batch_cluster.add_task.assert_not_called()
