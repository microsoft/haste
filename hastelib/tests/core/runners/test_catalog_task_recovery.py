# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from azure.batch.models import BatchError, BatchErrorException
from hastegeo.core.config import Config
from hastegeo.core.runners.azure_batch import AzureBatchRunner
from hastegeo.core.runners.local import LocalRunner, LocalTaskCancelledError

import docker


def batch_error(code: str) -> BatchErrorException:
    error = BatchErrorException.__new__(BatchErrorException)
    error.error = BatchError(code=code)
    return error


class TestBatchRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = AzureBatchRunner.__new__(AzureBatchRunner)
        self.runner.batch_config = Config().get_azure_batch_config()
        self.runner.batch_cluster = MagicMock()
        self.runner.candidate_pool_ids = ["preferred", "secondary"]
        self.runner.manage_pools = False
        self.runner.logger = MagicMock()
        self.enterContext(
            patch("hastegeo.core.runners.azure_batch.validate_batch_config")
        )

    def test_existing_task_returns_before_capacity_selection(self) -> None:
        self.assertEqual(
            self.runner.add_task("job", "task", idempotent=True),
            ("job", "task"),
        )
        self.runner.batch_cluster.select_pool.assert_not_called()
        self.runner.batch_cluster.add_task.assert_not_called()

    def test_existing_job_keeps_its_pool_and_task_identity(self) -> None:
        client = self.runner.batch_cluster.batch_client
        client.task.get.side_effect = batch_error("TaskNotFound")
        client.job.get.return_value.pool_info.pool_id = "secondary"
        result = self.runner.add_task("job", "task", idempotent=True)
        self.assertEqual(result, ("job", "task"))
        self.assertEqual(self.runner.batch_cluster.pool_id, "secondary")
        self.runner.batch_cluster.select_pool.assert_not_called()
        self.runner.batch_cluster._add_job.assert_not_called()
        self.assertEqual(
            self.runner.batch_cluster.add_task.call_args.kwargs["job_id"],
            "job",
        )

    def test_submission_conflicts_recover_without_creating_new_ids(
        self,
    ) -> None:
        cluster = self.runner.batch_cluster
        cluster.batch_client.task.get.side_effect = batch_error("JobNotFound")
        cluster.batch_client.job.get.side_effect = batch_error("JobNotFound")
        cluster.select_pool.return_value = "preferred"
        cluster._add_job.side_effect = batch_error("JobExists")
        cluster.add_task.side_effect = batch_error("TaskExists")
        self.assertEqual(
            self.runner.add_task("job", "task", idempotent=True),
            ("job", "task"),
        )
        cluster._add_job.assert_called_once_with("job")
        cluster.create_job.assert_not_called()

    def test_unrelated_service_errors_are_not_submission_success(self) -> None:
        self.runner.batch_cluster.batch_client.task.get.side_effect = (
            batch_error("AuthenticationFailed")
        )
        with self.assertRaises(BatchErrorException):
            self.runner.add_task("job", "task", idempotent=True)


class TestLocalRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = LocalRunner.__new__(LocalRunner)
        self.runner.config = Config()
        self.runner.work_dir = Path(self.enterContext(TemporaryDirectory()))
        self.runner.docker_client = MagicMock()
        self.runner.logger = MagicMock()
        self.runner.verbose = self.runner.fail_on_empty_logs = False
        self.runner.container_images = {"training": "haste-training"}

    def test_completed_task_retries_upload_without_reexecuting(self) -> None:
        task = self.runner.work_dir / "job" / "task"
        task.mkdir(parents=True)
        (task / "status.json").write_text(
            json.dumps(
                {
                    "state": "completed",
                    "exit_code": 0,
                }
            )
        )
        with patch.object(self.runner, "_add_task") as execute, patch.object(
            self.runner, "_upload_all_task_files"
        ) as upload:
            self.runner.add_task("job", "task", idempotent=True)
            execute.assert_not_called()
            self.assertTrue(upload.call_args.kwargs["strict"])
            upload.side_effect = TimeoutError("offline")
            with self.assertRaises(TimeoutError):
                self.runner.add_task("job", "task", idempotent=True)
            execute.assert_not_called()

    def test_cleanup_keeps_native_task_status_to_block_delayed_submissions(
        self,
    ) -> None:
        task = self.runner.work_dir / "job" / "inf-catalog-cleanup"
        (task / "inputs").mkdir(parents=True)
        (task / "inputs" / "checkpoint.ckpt").write_bytes(b"large fixture")
        (task / "status.json").write_text(
            json.dumps(
                {
                    "state": "completed",
                    "exit_code": 0,
                }
            )
        )
        self.runner.cleanup_task("job", "inf-catalog-cleanup")
        self.assertTrue((task / "status.json").is_file())
        self.assertFalse((task / "inputs").exists())
        with patch.object(self.runner, "_add_task") as execute, patch.object(
            self.runner, "_upload_all_task_files"
        ):
            self.runner.add_task("job", "inf-catalog-cleanup", idempotent=True)
        execute.assert_not_called()

    def test_recovered_container_is_not_created_or_restarted(self) -> None:
        existing = self.runner.docker_client.containers.get.return_value
        existing.status = "exited"
        actual = self.runner._task_container(
            "job",
            "task",
            "image",
            idempotent=True,
        )
        self.assertIs(actual, existing)
        existing.start.assert_not_called()
        self.runner.docker_client.containers.create.assert_not_called()

    def test_unstarted_container_is_started_once(self) -> None:
        self.runner.docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        created = self.runner.docker_client.containers.create.return_value
        created.status = "created"
        self.runner._task_container("job", "task", "image", idempotent=True)
        created.start.assert_called_once()
        self.assertEqual(
            self.runner.docker_client.containers.create.call_args.kwargs[
                "name"
            ],
            "haste-job-task",
        )

    def test_legacy_submission_keeps_positional_arguments(self) -> None:
        with patch.object(self.runner, "_add_task") as execute:
            self.runner.add_task("job", "task", "image", "command")
        execute.assert_called_once_with("job", "task", "image", "command")

    def test_cancel_stops_catalog_container(self) -> None:
        container = self.runner.docker_client.containers.get.return_value
        container.status = "running"
        self.runner.cancel_task("job", "inf-catalog-request")
        container.stop.assert_called_once_with(timeout=5)

    def test_explicit_gpu_selection_uses_container_local_cuda_ordinals(
        self,
    ) -> None:
        container = MagicMock()
        container.logs.return_value = [b"task completed\n"]
        container.wait.return_value = {"StatusCode": 0}
        with patch.dict(
            "os.environ", {"HASTE_ENABLE_GPU": "1", "HASTE_GPU_DEVICES": "1"}
        ), patch.object(
            self.runner, "_task_container", return_value=container
        ) as create, patch.object(
            self.runner, "_upload_all_task_files"
        ):
            self.runner.add_task(
                "job",
                "inf-catalog-gpu",
                image_name="training",
                command="true",
                idempotent=True,
            )
        settings = create.call_args.kwargs
        self.assertEqual(settings["device_requests"][0]["DeviceIDs"], ["1"])
        self.assertEqual(settings["device_requests"][0]["Count"], 0)
        self.assertNotIn("CUDA_VISIBLE_DEVICES", settings["environment"])
        self.assertEqual(
            settings["environment"]["NVIDIA_VISIBLE_DEVICES"], "1"
        )

    def test_cancel_before_task_directory_prevents_any_submission(
        self,
    ) -> None:
        self.runner.docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        self.runner.cancel_task("job", "inf-catalog-request")
        with patch.object(self.runner, "_add_task") as execute:
            self.runner.add_task("job", "inf-catalog-request", idempotent=True)
        execute.assert_not_called()
        self.runner.docker_client.containers.create.assert_not_called()

    def test_cancel_during_staging_prevents_container_start(self) -> None:
        self.runner.docker_client.containers.get.side_effect = (
            docker.errors.NotFound("missing")
        )
        task = self.runner.work_dir / "job" / "inf-catalog-request"
        task.mkdir(parents=True)
        self.runner.cancel_task("job", "inf-catalog-request")
        with self.assertRaises(LocalTaskCancelledError):
            self.runner._task_container(
                "job", "inf-catalog-request", "image", idempotent=True
            )
        self.runner.docker_client.containers.create.assert_not_called()
