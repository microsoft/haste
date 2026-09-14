# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.runners.azure_batch import AzureBatchRunner
from hastegeo.core.runners.local import LocalRunner

import docker

from .test_azure_batch_node_errors import _batch_error


class TestIdempotentFootprintTasks(unittest.TestCase):
    def batch_runner(self) -> AzureBatchRunner:
        runner = AzureBatchRunner.__new__(AzureBatchRunner)
        runner.batch_config = Config().get_azure_batch_config()
        runner.manage_pools = False
        runner.candidate_pool_ids = ["first", "second"]
        runner.batch_cluster = MagicMock()
        runner.batch_cluster.select_pool.return_value = "second"
        runner.logger = MagicMock()
        return runner

    def test_batch_accepted_task_reattaches_without_capacity_selection(
        self,
    ) -> None:
        runner = self.batch_runner()
        with patch("hastegeo.core.runners.azure_batch.validate_batch_config"):
            self.assertEqual(
                runner.add_task(
                    job_id="ftl-job", task_id="ftl-task", idempotent=True
                ),
                ("ftl-job", "ftl-task"),
            )
        runner.batch_cluster.select_pool.assert_not_called()
        runner.batch_cluster.add_task.assert_not_called()

    def test_batch_submission_race_adopts_existing_job_and_task(self) -> None:
        runner = self.batch_runner()
        runner.batch_cluster.batch_client.task.get.side_effect = _batch_error(
            "TaskNotFound"
        )
        runner.batch_cluster.batch_client.job.get.side_effect = _batch_error(
            "JobNotFound"
        )
        runner.batch_cluster._add_job.side_effect = _batch_error("JobExists")
        runner.batch_cluster.add_task.side_effect = _batch_error("TaskExists")
        with patch("hastegeo.core.runners.azure_batch.validate_batch_config"):
            self.assertEqual(
                runner.add_task(
                    job_id="ftl-job", task_id="ftl-task", idempotent=True
                ),
                ("ftl-job", "ftl-task"),
            )
        runner.batch_cluster.add_task.assert_called_once()
        self.assertEqual(
            runner.batch_cluster.add_task.call_args.kwargs["job_id"], "ftl-job"
        )

    def test_local_reuses_named_running_or_exited_container(self) -> None:
        runner = LocalRunner.__new__(LocalRunner)
        runner.docker_client = MagicMock()
        for status in ("running", "exited", "created"):
            container = MagicMock(status=status)
            runner.docker_client.containers.get.return_value = container
            self.assertIs(
                runner._task_container("j", "t", "image", idempotent=True),
                container,
            )
            self.assertEqual(
                container.start.call_count, int(status == "created")
            )
        runner.docker_client.containers.create.assert_not_called()
        runner.docker_client.containers.run.assert_not_called()

    def test_local_missing_container_is_created_once_with_stable_name(
        self,
    ) -> None:
        runner = LocalRunner.__new__(LocalRunner)
        runner.docker_client = MagicMock()
        runner.docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        runner.docker_client.containers.create.return_value.status = "created"
        runner._task_container(
            "j", "t", "image", idempotent=True, detach=True, remove=False
        )
        self.assertEqual(
            runner.docker_client.containers.create.call_args.kwargs,
            {"name": "haste-j-t"},
        )
        runner.docker_client.containers.create.return_value.start.assert_called_once()

    def test_local_completed_task_does_not_rerun_after_metadata_failure(
        self,
    ) -> None:
        runner = LocalRunner.__new__(LocalRunner)
        runner._add_task = MagicMock()
        with TemporaryDirectory() as directory:
            runner.work_dir = Path(directory)
            task = runner.work_dir / "job" / "task"
            task.mkdir(parents=True)
            (task / "status.json").write_text(
                '{"state":"completed","exit_code":0}'
            )
            self.assertEqual(
                runner.add_task("job", "task", idempotent=True),
                ("job", "task"),
            )
        runner._add_task.assert_not_called()
