# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.runners import local
from hastegeo.core.runners.azure_batch import AzureBatchRunner
from hastegeo.core.runners.local import LocalRunner

from .test_azure_batch_node_errors import _batch_error
from .test_local_lifecycle import FakeBlobs, FakeDocker


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

    def local_runner(self, directory: Path) -> tuple[LocalRunner, FakeDocker]:
        engine, blobs = FakeDocker(), FakeBlobs()
        self.enterContext(
            patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError(
                    "Unit test attempted network access"
                ),
            )
        )
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "RUNNER_TYPE": "local",
                    "DATA_PATH": str(directory / "metadata"),
                    "HASTE_LOCAL_MAX_ACTIVE_TASKS": "1",
                    "CLEANUP_CONTAINERS": "1",
                    "PRESERVE_LOCAL_TASK_DIRS": "0",
                    "HASTE_ENABLE_GPU": "0",
                },
            )
        )
        self.enterContext(
            patch.object(local, "TASK_WORK_DIR", directory / "tasks")
        )
        self.enterContext(
            patch.object(local.docker, "from_env", return_value=engine)
        )
        self.enterContext(
            patch.object(
                local.BlobServiceClient,
                "from_connection_string",
                return_value=blobs,
            )
        )
        return LocalRunner(config=Config()), engine

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
        attempted = False

        def get_task(job_id: str, task_id: str) -> SimpleNamespace:
            if not attempted:
                raise _batch_error("TaskNotFound")
            return SimpleNamespace(id=task_id, job_id=job_id)

        def add_task(**kwargs) -> None:
            nonlocal attempted
            attempted = True
            raise _batch_error("TaskExists")

        runner.batch_cluster.batch_client.task.get.side_effect = get_task
        runner.batch_cluster.batch_client.job.get.side_effect = _batch_error(
            "JobNotFound"
        )
        runner.batch_cluster._add_job.side_effect = _batch_error("JobExists")
        runner.batch_cluster.add_task.side_effect = add_task
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

    def test_local_idempotent_submission_reuses_running_receipt(self) -> None:
        with TemporaryDirectory() as directory:
            runner, engine = self.local_runner(Path(directory))
            identity = runner.add_task(
                "ftl-job",
                "ftl-task",
                image_name="training",
                command="python workflow.py",
                output_prefix="project/ftl-task",
                idempotent=True,
            )
            self.assertEqual(
                runner.add_task(
                    "ftl-job",
                    "ftl-task",
                    image_name="training",
                    command="python workflow.py",
                    output_prefix="project/ftl-task",
                    idempotent=True,
                ),
                identity,
            )
            runner.reconcile_tasks()
            self.assertEqual(identity, ("ftl-job", "ftl-task"))
            self.assertEqual(len(engine.executions()), 1)
            self.assertEqual(engine.executions()[0].starts, 1)
            self.assertEqual(engine.executions()[0].status, "running")
            runner.reconcile_tasks()
            self.assertEqual(len(engine.executions()), 1)
            self.assertEqual(engine.executions()[0].starts, 1)

    def test_local_idempotent_submission_reuses_exited_receipt(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            runner, engine = self.local_runner(Path(directory))
            identity = runner.add_task(
                "ftl-job",
                "ftl-task",
                image_name="training",
                command="python workflow.py",
                output_prefix="project/ftl-task",
                idempotent=True,
            )
            runner.reconcile_tasks()
            container = engine.executions()[0]
            container.complete()
            self.assertEqual(
                runner.add_task(
                    "ftl-job",
                    "ftl-task",
                    image_name="training",
                    command="python workflow.py",
                    output_prefix="project/ftl-task",
                    idempotent=True,
                ),
                identity,
            )
            runner.reconcile_tasks()
            self.assertEqual(len(engine.executions()), 1)
            self.assertEqual(container.starts, 1)
            self.assertEqual(runner.get_task_status(*identity), "Processed")

    def test_local_completed_task_does_not_rerun_after_metadata_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            runner, engine = self.local_runner(Path(directory))
            identity = runner.add_task(
                "job",
                "task",
                image_name="training",
                command="python workflow.py",
                output_prefix="project/task",
                idempotent=True,
            )
            runner.reconcile_tasks()
            container = engine.executions()[0]
            container.complete()
            runner.reconcile_tasks()
            self.assertEqual(
                runner.add_task(
                    "job",
                    "task",
                    image_name="training",
                    command="python workflow.py",
                    output_prefix="project/task",
                    idempotent=True,
                ),
                identity,
            )
            runner.reconcile_tasks()
            self.assertEqual(len(engine.executions()), 1)
            self.assertEqual(container.starts, 1)
