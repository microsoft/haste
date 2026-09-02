# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the ``ComputeRunner`` contract on ``LocalRunner``
(validate/submit/get_status/read_output/cancel/finalize/get_capacity).

``LocalRunner.__init__`` eagerly connects to the Docker daemon, so these
tests construct instances via ``LocalRunner.__new__`` (bypassing
``__init__``) and set only the attributes each test needs — the same
pattern used for `AzureBatchRunner` in
``test_azure_batch_compute_runner.py``. Where a test exercises a legacy
filesystem-based method (``get_task_status``/``cancel_task``/
``cleanup_task``), it runs against a real temporary directory rather than a
mock, so the translation is checked against the actual (unmodified) legacy
behavior it delegates to.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import docker.errors
from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    BackendConfigurationError,
    BackendUnavailableError,
    CapacityState,
    ComputeBackend,
    ComputeContainerRef,
    ComputeInput,
    ComputeJobHandle,
    ComputeJobSpec,
    ComputeJobState,
    ComputeOutput,
    ComputeProviderDetail,
    ComputeTags,
    ComputeWorkload,
    InputKind,
    LocalProviderDetail,
)
from hastegeo.core.runners.base import ComputeRunner
from hastegeo.core.runners.local import LocalRunner


def _runner(work_dir):
    runner = LocalRunner.__new__(LocalRunner)
    runner.docker_client = MagicMock()
    runner.work_dir = Path(work_dir)
    runner.logger = MagicMock()
    runner.pool_id = "local-pool"
    runner.config = Config()
    runner.verbose = False
    runner.fail_on_empty_logs = False
    runner.blob_client = None
    runner.queue_client = None
    runner.container_images = {
        "imageryprep": "haste-imageryprep",
        "training": "haste-training",
        "inference": "haste-training",
    }
    return runner


def _spec(**overrides):
    kwargs = dict(
        executionId="exec-1",
        workload=ComputeWorkload.TRAINING,
        backendPreference=ComputeBackend.LOCAL,
        container=ComputeContainerRef(
            imageReference="acr.example.io/train:v1"
        ),
        command="python run.py",
        inputs=[
            ComputeInput(
                sourceUri="https://a.blob.core.windows.net/c/f.tif",
                kind=InputKind.FILE,
                destinationRelativePath="in/f.tif",
            )
        ],
        outputs=[
            ComputeOutput(
                name="out",
                sourceRelativePattern="outputs/*.tif",
                destinationUri=(
                    "https://a.blob.core.windows.net/data/proj/task-1/"
                ),
            )
        ],
        tags=ComputeTags(project="p1", workload=ComputeWorkload.TRAINING),
    )
    kwargs.update(overrides)
    return ComputeJobSpec(**kwargs)


def _handle(**overrides):
    kwargs = dict(
        executionId="exec-1",
        requestedBackend=ComputeBackend.LOCAL,
        selectedBackend=ComputeBackend.LOCAL,
        backendProfile="default",
        providerJobId="job-exec-1",
        providerTaskId="exec-1",
        targetId="local-pool",
        outputUri="https://a.blob.core.windows.net/data/proj/task-1/",
        submittedAt="2026-01-01T00:00:00+00:00",
        routingReason="adapter-default",
        attempt=1,
        providerDetail=ComputeProviderDetail(
            discriminator="local",
            local=LocalProviderDetail(executionDirectory="/tmp/x"),
        ),
    )
    kwargs.update(overrides)
    return ComputeJobHandle(**kwargs)


def _write_status(work_dir, job_id, task_id, state, exit_code=0):
    task_dir = Path(work_dir) / job_id / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    with open(task_dir / "status.json", "w") as f:
        json.dump(
            {
                "state": state,
                "exit_code": exit_code,
                "job_id": job_id,
                "task_id": task_id,
            },
            f,
        )
    return task_dir


class TestLocalRunnerIsComputeRunner(unittest.TestCase):
    def test_is_instance_of_compute_runner(self):
        self.assertTrue(issubclass(LocalRunner, ComputeRunner))

    def test_legacy_baserunner_methods_still_present(self):
        for name in (
            "get_filecontent_from_task",
            "get_task_status",
            "add_task",
            "cleanup_task",
            "cancel_task",
        ):
            self.assertTrue(
                callable(getattr(LocalRunner, name, None)),
                f"{name} missing from LocalRunner",
            )


class TestValidate(unittest.TestCase):
    def test_raises_backend_unavailable_when_docker_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.docker_client.ping.side_effect = (
                docker.errors.DockerException("no daemon")
            )
            with self.assertRaises(BackendUnavailableError):
                runner.validate(_spec())

    def test_raises_when_docker_client_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.docker_client = None
            with self.assertRaises(BackendConfigurationError):
                runner.validate(_spec())

    def test_raises_when_no_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            with self.assertRaises(BackendConfigurationError):
                runner.validate(_spec(outputs=[]))

    def test_raises_when_outputs_share_container_but_differ_in_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            spec = _spec(
                outputs=[
                    ComputeOutput(
                        name="a",
                        sourceRelativePattern="a/*.tif",
                        destinationUri=(
                            "https://a.blob.core.windows.net/data/p/t1/"
                        ),
                    ),
                    ComputeOutput(
                        name="b",
                        sourceRelativePattern="b/*.tif",
                        destinationUri=(
                            "https://a.blob.core.windows.net/data/p/t2/"
                        ),
                    ),
                ]
            )
            with self.assertRaises(BackendConfigurationError):
                runner.validate(spec)

    def test_raises_on_unsupported_input_uri_scheme(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            spec = _spec(
                inputs=[
                    ComputeInput(
                        sourceUri="s3://bucket/key.tif",
                        kind=InputKind.FILE,
                        destinationRelativePath="in/f.tif",
                    )
                ]
            )
            with self.assertRaises(BackendConfigurationError):
                runner.validate(spec)

    def test_raises_on_unsupported_output_uri_scheme(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            spec = _spec(
                outputs=[
                    ComputeOutput(
                        name="out",
                        sourceRelativePattern="outputs/*.tif",
                        destinationUri=("azureml://datastores/x/paths/p/t/"),
                    )
                ]
            )
            with self.assertRaises(BackendConfigurationError):
                runner.validate(spec)

    def test_raises_on_duplicate_input_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            spec = _spec(
                inputs=[
                    ComputeInput(
                        sourceUri=("https://a.blob.core.windows.net/c/f1.tif"),
                        kind=InputKind.FILE,
                        destinationRelativePath="in/f.tif",
                    ),
                    ComputeInput(
                        sourceUri=("https://a.blob.core.windows.net/c/f2.tif"),
                        kind=InputKind.FILE,
                        destinationRelativePath="in/f.tif",
                    ),
                ]
            )
            with self.assertRaises(BackendConfigurationError):
                runner.validate(spec)

    def test_passes_with_reachable_docker_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.validate(_spec())  # must not raise


class TestSubmit(unittest.TestCase):
    def test_command_and_haste_job_workdir_env_var(self):
        """Local knows its resolved container working directory ahead of
        submission, so HASTE_JOB_WORKDIR is passed as a plain env var
        (not exported from another variable, unlike Batch); legacy
        AZ_BATCH_* vars remain add_task's own responsibility."""
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.add_task = MagicMock(return_value=("job-exec-1", "exec-1"))
            runner.submit(_spec(command="./run_workflow.py --config c.yaml"))

            kwargs = runner.add_task.call_args.kwargs
            self.assertEqual(
                kwargs["command"], "./run_workflow.py --config c.yaml"
            )
            # The exact value mirrors add_task's own container_working_dir
            # formula; assert it targets this task's directory rather than
            # re-deriving the "/shared/azurite" substitution here.
            workdir = kwargs["env_vars"]["HASTE_JOB_WORKDIR"]
            self.assertIn("job-exec-1", workdir)
            self.assertIn("exec-1", workdir)
            self.assertEqual(
                workdir,
                runner._resolved_container_working_dir("job-exec-1", "exec-1"),
            )

    def test_translates_spec_into_add_task_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.add_task = MagicMock(return_value=("job-exec-1", "exec-1"))
            handle = runner.submit(_spec())

            kwargs = runner.add_task.call_args.kwargs
            self.assertEqual(kwargs["job_id"], "job-exec-1")
            self.assertEqual(kwargs["task_id"], "exec-1")
            self.assertEqual(kwargs["image_name"], "acr.example.io/train:v1")
            self.assertEqual(kwargs["command"], "python run.py")
            self.assertIsNone(kwargs["arguments"])
            self.assertEqual(kwargs["output_container_url"], "data")
            self.assertEqual(kwargs["output_prefix"], "proj/task-1")
            self.assertEqual(
                kwargs["resource_files_for_upload"],
                {
                    "in/f.tif": {
                        "file_path": "in/f.tif",
                        "http_url": (
                            "https://a.blob.core.windows.net/c/f.tif"
                        ),
                    }
                },
            )
            expected_pattern = str(
                Path(tmp) / "job-exec-1" / "exec-1" / "outputs" / "*.tif"
            )
            self.assertEqual(kwargs["file_pattern"], [expected_pattern])

            self.assertEqual(handle.executionId, "exec-1")
            self.assertEqual(handle.selectedBackend, ComputeBackend.LOCAL)
            self.assertEqual(handle.providerJobId, "job-exec-1")
            self.assertEqual(handle.providerTaskId, "exec-1")
            self.assertEqual(handle.providerDetail.discriminator, "local")
            self.assertTrue(
                handle.providerDetail.local.executionDirectory.endswith(
                    str(Path("job-exec-1") / "exec-1")
                )
            )

    def test_folder_input_translates_to_storage_container_url_and_prefix(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.add_task = MagicMock(return_value=("job-exec-1", "exec-1"))
            spec = _spec(
                inputs=[
                    ComputeInput(
                        sourceUri=(
                            "https://a.blob.core.windows.net/c/models/v1/"
                        ),
                        kind=InputKind.FOLDER,
                        destinationRelativePath="model",
                    )
                ]
            )
            runner.submit(spec)
            resource_files = runner.add_task.call_args.kwargs[
                "resource_files_for_upload"
            ]
            entry = resource_files["model"]
            self.assertEqual(
                entry["storage_container_url"],
                "https://a.blob.core.windows.net/c",
            )
            self.assertEqual(entry["blob_prefix"], "models/v1")
            self.assertEqual(entry["file_path"], "model")

    def test_idempotent_when_task_already_ran(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(tmp, "job-exec-1", "exec-1", "completed")
            runner.add_task = MagicMock()

            handle = runner.submit(_spec())

            runner.add_task.assert_not_called()
            self.assertEqual(handle.providerJobId, "job-exec-1")
            self.assertEqual(handle.providerTaskId, "exec-1")


class TestGetStatus(unittest.TestCase):
    def test_maps_completed_to_succeeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(
                tmp, "job-exec-1", "exec-1", "completed", exit_code=0
            )
            self.assertEqual(
                runner.get_status(_handle()), ComputeJobState.SUCCEEDED
            )

    def test_maps_failed_to_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(tmp, "job-exec-1", "exec-1", "failed", exit_code=1)
            self.assertEqual(
                runner.get_status(_handle()), ComputeJobState.FAILED
            )

    def test_missing_task_dir_maps_to_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            self.assertEqual(
                runner.get_status(_handle()), ComputeJobState.RUNNING
            )

    def test_unmapped_status_logs_raw_status_before_raising(self):
        """F10: an unrecognized provider status must be logged
        server-side (raw status + correlation IDs) before the typed
        error is raised, matching the AML adapter's unmapped-status
        diagnostics — never silently reported as "running". The legacy
        get_task_status() only ever returns one of three known values,
        so this mocks it directly to model a value it could never
        actually produce."""
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.get_task_status = MagicMock(return_value="SomeWeirdState")

            with self.assertRaises(BackendUnavailableError):
                runner.get_status(_handle())

            runner.logger.error.assert_called_once()
            args = runner.logger.error.call_args.args
            self.assertIn("SomeWeirdState", args)
            self.assertIn("exec-1", args)  # providerTaskId from _handle()
            self.assertIn("job-exec-1", args)  # providerJobId from _handle()


class TestReadOutput(unittest.TestCase):
    def test_rejects_path_traversal_before_any_filesystem_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            with self.assertRaises(ValueError):
                runner.read_output(_handle(), "../../etc/passwd")

    def test_rejects_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            with self.assertRaises(ValueError):
                runner.read_output(_handle(), "/etc/passwd")

    def test_delegates_to_legacy_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            task_dir = Path(tmp) / "job-exec-1" / "exec-1"
            task_dir.mkdir(parents=True)
            with open(task_dir / "progress.log", "w") as f:
                f.write("hello")
            result = runner.read_output(_handle(), "progress.log")
            self.assertEqual(result, "hello")

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            self.assertIsNone(runner.read_output(_handle(), "missing.log"))


class TestCancel(unittest.TestCase):
    def test_cancels_a_still_running_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(tmp, "job-exec-1", "exec-1", "running")
            runner.cancel(_handle())
            status_file = Path(tmp) / "job-exec-1" / "exec-1" / "status.json"
            with open(status_file) as f:
                data = json.load(f)
            self.assertEqual(data["state"], "cancelled")

    def test_does_not_clobber_an_already_completed_status(self):
        """NEG-003: cancellation racing with completion must not
        overwrite a terminal succeeded/failed state."""
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(
                tmp, "job-exec-1", "exec-1", "completed", exit_code=0
            )
            runner.cancel(_handle())
            status_file = Path(tmp) / "job-exec-1" / "exec-1" / "status.json"
            with open(status_file) as f:
                data = json.load(f)
            self.assertEqual(data["state"], "completed")

    def test_does_not_clobber_an_already_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(tmp, "job-exec-1", "exec-1", "failed", exit_code=1)
            runner.cancel(_handle())
            status_file = Path(tmp) / "job-exec-1" / "exec-1" / "status.json"
            with open(status_file) as f:
                data = json.load(f)
            self.assertEqual(data["state"], "failed")


class TestFinalize(unittest.TestCase):
    def test_removes_task_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            task_dir = _write_status(tmp, "job-exec-1", "exec-1", "completed")
            self.assertTrue(task_dir.exists())
            runner.finalize(_handle())
            self.assertFalse(task_dir.exists())

    def test_idempotent_second_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            _write_status(tmp, "job-exec-1", "exec-1", "completed")
            runner.finalize(_handle())
            runner.finalize(_handle())  # must not raise


class TestGetCapacity(unittest.TestCase):
    def test_available_when_docker_reachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            snapshot = runner.get_capacity(
                ComputeWorkload.TRAINING, MagicMock()
            )
            self.assertEqual(snapshot.state, CapacityState.AVAILABLE)
            self.assertEqual(snapshot.backend, ComputeBackend.LOCAL)

    def test_unavailable_when_docker_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(tmp)
            runner.docker_client.ping.side_effect = (
                docker.errors.DockerException("no daemon")
            )
            snapshot = runner.get_capacity(
                ComputeWorkload.TRAINING, MagicMock()
            )
            self.assertEqual(snapshot.state, CapacityState.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
