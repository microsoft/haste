# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for the ``ComputeRunner`` contract on ``AzureBatchRunner``
(validate/submit/get_status/read_output/cancel/finalize/get_capacity).

These are translation/contract tests against a mocked ``AzureBatchJob``
(``batch_cluster``) and mocked legacy ``BaseRunner`` methods — no live
Batch calls. They pin the new methods' behavior without duplicating the
existing pool-routing/SAS/node-loss unit tests in
``test_azure_batch_routing.py``/``test_azure_batch_node_errors.py``, which
continue to cover the legacy ``add_task``/``get_task_status``/etc methods
this file's new methods delegate to unchanged.
"""

import unittest
from unittest.mock import MagicMock

from azure.batch.models import (
    BatchError,
    BatchErrorException,
    ErrorMessage,
    TaskState,
)
from azure.core.exceptions import ServiceRequestError
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
    JobCancellationError,
    JobNotFoundError,
    OutputNotAvailableError,
    SubmissionIndeterminateError,
)
from hastegeo.core.runners.azure_batch import (
    AzureBatchRunner,
    _export_haste_job_workdir,
)
from hastegeo.core.runners.base import ComputeRunner
from tenacity import RetryError


def _batch_error(code, status_code=409, value="error"):
    exc = BatchErrorException.__new__(BatchErrorException)
    exc.error = BatchError(code=code, message=ErrorMessage(value=value))
    exc.response = MagicMock(status_code=status_code)
    return exc


def _retry_error(exc):
    attempt = MagicMock()
    attempt.failed = True
    attempt.exception.return_value = exc
    return RetryError(attempt)


def _runner(manage_pools=False, candidate_pool_ids=None):
    runner = AzureBatchRunner.__new__(AzureBatchRunner)
    runner.batch_cluster = MagicMock()
    runner.batch_cluster.pool_id = "pool-a"
    # Defaults matching a first-submission, single-candidate,
    # single-attempt path: no job exists yet (get_execution_job_pool ->
    # None), so submit() falls through to selection + creation. Tests
    # exercising the read-first-reconciles-existing-job path or
    # multi-pool/race behavior override these explicitly.
    runner.batch_cluster.get_execution_job_pool = MagicMock(return_value=None)
    runner.batch_cluster.select_pool = MagicMock(return_value="pool-a")
    runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
        return_value=("pool-a", True)
    )
    runner.batch_cluster.add_task = MagicMock(return_value=None)
    runner.logger = MagicMock()
    runner.pool_id = "pool-a"
    runner.candidate_pool_ids = candidate_pool_ids or ["pool-a"]
    runner.manage_pools = manage_pools
    runner.config = Config()
    runner.batch_config = {
        "account_name": "acct",  # pragma: allowlist secret
        "batch_url": "https://acct.batch.azure.com",
        "output_container_url": "https://acct.blob.core.windows.net/data",
        "manage_pools": manage_pools,
        "training_batch_job_id": "training-pool",
        "inference_batch_job_id": "training-pool",
        "imageryprep_batch_job_id": "imageryprep-pool",
        "artifact_batch_job_id": "imageryprep-pool",
        "task_retention_time": "P2D",
        "registry_image": "acr.example.io/train@sha256:" + ("a1" * 32),
        "imageprep_docker_image": "acr.example.io/prep@sha256:" + ("b2" * 32),
        "vm_size": "Standard_NC6S_V3",
        "vm_publisher": "microsoft-azure-batch",
        "vm_offer": "ubuntu-server-container",
        "vm_sku": "20-04-lts",
        "vm_version": "latest",
        "target_dedicated_nodes": 1,
        "target_low_priority_nodes": 0,
        "registry_server": "acr.example.io",
        "node_agent_sku_id": "batch.node.ubuntu 20.04",
    }
    return runner


def _spec(**overrides):
    kwargs = dict(
        executionId="exec-1",
        workload=ComputeWorkload.TRAINING,
        backendPreference=ComputeBackend.AZURE_BATCH,
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
    from hastegeo.core.models.compute import BatchProviderDetail

    kwargs = dict(
        executionId="exec-1",
        requestedBackend=ComputeBackend.AZURE_BATCH,
        selectedBackend=ComputeBackend.AZURE_BATCH,
        backendProfile="default",
        providerJobId="job-1",
        providerTaskId="exec-1",
        targetId="pool-a",
        outputUri="https://a.blob.core.windows.net/data/proj/task-1/",
        submittedAt="2026-01-01T00:00:00+00:00",
        routingReason="adapter-default",
        attempt=1,
        providerDetail=ComputeProviderDetail(
            discriminator="batch",
            batch=BatchProviderDetail(jobId="job-1", taskId="exec-1"),
        ),
    )
    kwargs.update(overrides)
    return ComputeJobHandle(**kwargs)


class TestAzureBatchRunnerIsComputeRunner(unittest.TestCase):
    def test_is_instance_of_compute_runner(self):
        self.assertTrue(issubclass(AzureBatchRunner, ComputeRunner))

    def test_legacy_baserunner_methods_still_present(self):
        # Characterization: the legacy (job_id, task_id) contract must
        # keep working during the compatibility window.
        for name in (
            "get_filecontent_from_task",
            "get_task_status",
            "add_task",
            "cleanup_task",
            "cancel_task",
        ):
            self.assertTrue(
                callable(getattr(AzureBatchRunner, name, None)),
                f"{name} missing from AzureBatchRunner",
            )


class TestValidate(unittest.TestCase):
    def test_raises_backend_configuration_error_when_batch_not_configured(
        self,
    ):
        runner = _runner()
        runner.batch_config = {}  # nothing resolved
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec())

    def test_raises_when_no_outputs(self):
        runner = _runner()
        with self.assertRaises(BackendConfigurationError):
            runner.validate(_spec(outputs=[]))

    def test_raises_when_outputs_span_multiple_containers(self):
        runner = _runner()
        spec = _spec(
            outputs=[
                ComputeOutput(
                    name="a",
                    sourceRelativePattern="a/*.tif",
                    destinationUri=(
                        "https://a.blob.core.windows.net/data/p/t/"
                    ),
                ),
                ComputeOutput(
                    name="b",
                    sourceRelativePattern="b/*.tif",
                    destinationUri=(
                        "https://a.blob.core.windows.net/other/p/t/"
                    ),
                ),
            ]
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(spec)

    def test_raises_when_outputs_share_container_but_differ_in_prefix(self):
        """UT: same container, different prefix must still be rejected —
        not silently accepted using only the first output's prefix."""
        runner = _runner()
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
        runner = _runner()
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
        runner = _runner()
        spec = _spec(
            outputs=[
                ComputeOutput(
                    name="out",
                    sourceRelativePattern="outputs/*.tif",
                    destinationUri="azureml://datastores/x/paths/p/t/",
                )
            ]
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(spec)

    def test_raises_on_adl_scheme(self):
        runner = _runner()
        spec = _spec(
            inputs=[
                ComputeInput(
                    sourceUri=("adl://acct.azuredatalakestore.net/f.tif"),
                    kind=InputKind.FILE,
                    destinationRelativePath="in/f.tif",
                )
            ]
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(spec)

    def test_raises_on_duplicate_input_destination(self):
        runner = _runner()
        spec = _spec(
            inputs=[
                ComputeInput(
                    sourceUri="https://a.blob.core.windows.net/c/f1.tif",
                    kind=InputKind.FILE,
                    destinationRelativePath="in/f.tif",
                ),
                ComputeInput(
                    sourceUri="https://a.blob.core.windows.net/c/f2.tif",
                    kind=InputKind.FILE,
                    destinationRelativePath="in/f.tif",
                ),
            ]
        )
        with self.assertRaises(BackendConfigurationError):
            runner.validate(spec)

    def test_passes_with_valid_config_and_outputs(self):
        runner = _runner()
        runner.validate(_spec())  # must not raise


class TestExportHasteJobWorkdir(unittest.TestCase):
    """Direct unit tests for the quoting-aware command helper (see
    _export_haste_job_workdir's docstring for the rationale)."""

    def test_unquoted_command_is_prefixed_normally(self):
        result = _export_haste_job_workdir("python run.py --overwrite")
        self.assertEqual(
            result,
            'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && '
            "python run.py --overwrite",
        )

    def test_double_quoted_train_style_command_keeps_one_quoted_chain(self):
        """Regression test for an actual train-style command shape: the
        whole '&&'-chained command wrapped in one leading/trailing double
        quote so the entrypoint receives a single shell chain. The export
        must land *inside* that same pair of quotes, not before it."""
        command = (
            '"cd /app/data && python train.py --config config.yaml '
            '--epochs 50"'
        )
        result = _export_haste_job_workdir(command)

        # Exactly one leading and one trailing double quote — the export
        # was not appended as a second, separate quoted/unquoted token.
        self.assertTrue(result.startswith('"'))
        self.assertTrue(result.endswith('"'))
        # 1 opening + 2 escaped (around $AZ_BATCH_TASK_WORKING_DIR) + 1
        # closing == 4 literal '"' characters total.
        self.assertEqual(result.count('"'), 4)

        inner = result[1:-1]
        self.assertEqual(
            inner,
            'export HASTE_JOB_WORKDIR=\\"$AZ_BATCH_TASK_WORKING_DIR\\" && '
            "cd /app/data && python train.py --config config.yaml "
            "--epochs 50",
        )

    def test_single_quoted_command_expands_workdir_in_one_command_token(self):
        command = "'cd /app && python run_workflow.py'"
        result = _export_haste_job_workdir(command)

        self.assertTrue(result.startswith("'"))
        self.assertTrue(result.endswith("'"))
        self.assertEqual(result.count("'"), 4)
        self.assertEqual(
            result,
            "'export HASTE_JOB_WORKDIR='"
            '"$AZ_BATCH_TASK_WORKING_DIR"'
            "' && cd /app && python run_workflow.py'",
        )

    def test_mismatched_quote_characters_are_not_treated_as_a_wrapper(self):
        # Starts with '"' but ends with "'": not a matching wrapper, so
        # this must fall back to the plain-prefix path rather than
        # guessing.
        command = "\"cd /app && python run.py'"
        result = _export_haste_job_workdir(command)
        self.assertTrue(
            result.startswith(
                'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && '
            )
        )
        self.assertTrue(result.endswith(command))

    def test_single_character_command_is_not_treated_as_a_wrapper(self):
        # A single '"' character matches command[0] == command[-1] but
        # is not a wrapper pair (there is no inner content) — must still
        # fall back to the plain-prefix path, not produce an empty inner
        # command.
        result = _export_haste_job_workdir('"')
        self.assertTrue(
            result.startswith(
                'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && '
            )
        )
        self.assertTrue(result.endswith('"'))


class TestSubmit(unittest.TestCase):
    def test_auto_terminate_transport_failure_still_returns_handle(self):
        runner = _runner()
        runner.batch_cluster.arm_job_auto_terminate.side_effect = (
            ServiceRequestError("connection reset")
        )

        handle = runner.submit(_spec())

        self.assertEqual(handle.providerJobId, "haste-exec-1")
        runner.batch_cluster.add_task.assert_called_once()
        runner.logger.warning.assert_called_once()

    def test_command_exports_haste_job_workdir_before_workload_command(self):
        """Processors migrating to HASTE_JOB_WORKDIR (embedding/imagery
        don't source set_dirs.sh at all) need it exported before the
        workload command runs; Batch only knows the real working
        directory via $AZ_BATCH_TASK_WORKING_DIR at container start, so
        it must be exported from that legacy variable in the command
        itself rather than passed as a static env var."""
        runner = _runner()
        runner.submit(_spec(command="./run_workflow.py --config c.yaml"))

        command = runner.batch_cluster.add_task.call_args.kwargs["command"]
        self.assertTrue(
            command.startswith(
                'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && '
            )
        )
        self.assertTrue(command.endswith("./run_workflow.py --config c.yaml"))
        # Legacy $AZ_BATCH_TASK_WORKING_DIR reference is preserved, not
        # replaced.
        self.assertIn("$AZ_BATCH_TASK_WORKING_DIR", command)

    def test_quoted_train_style_command_preserves_single_quoted_chain(self):
        """Integration-level regression test: submit() must delegate to
        _export_haste_job_workdir rather than a naive prefix, so a real
        quoted train-style command_line isn't split into two tokens."""
        runner = _runner()
        quoted_command = (
            '"cd /app/data && python train.py --config config.yaml"'
        )
        runner.submit(_spec(command=quoted_command))

        command = runner.batch_cluster.add_task.call_args.kwargs["command"]
        self.assertEqual(command.count('"'), 4)
        self.assertTrue(command.startswith('"'))
        self.assertTrue(command.endswith('"'))
        self.assertIn(
            'export HASTE_JOB_WORKDIR=\\"$AZ_BATCH_TASK_WORKING_DIR\\" && '
            "cd /app/data && python train.py --config config.yaml",
            command,
        )

    def test_translates_spec_into_add_task_call(self):
        runner = _runner()
        handle = runner.submit(_spec())

        kwargs = runner.batch_cluster.add_task.call_args.kwargs
        # Deterministic per-execution job id (f"haste-{executionId}",
        # bounded/hash-safe) — not a pool- or workload-scoped id.
        self.assertEqual(kwargs["job_id"], "haste-exec-1")
        self.assertEqual(kwargs["task_id"], "exec-1")
        self.assertEqual(kwargs["image_name"], "acr.example.io/train:v1")
        self.assertEqual(
            kwargs["command"],
            'export HASTE_JOB_WORKDIR="$AZ_BATCH_TASK_WORKING_DIR" && '
            "python run.py",
        )
        self.assertIsNone(kwargs["arguments"])
        self.assertEqual(
            kwargs["output_container_url"],
            "https://a.blob.core.windows.net/data",
        )
        self.assertEqual(kwargs["output_prefix"], "proj/task-1")
        self.assertEqual(
            kwargs["file_pattern"],
            ["$AZ_BATCH_TASK_WORKING_DIR/outputs/*.tif"],
        )
        self.assertEqual(kwargs["retention_time"], "P2D")
        runner.batch_cluster.arm_job_auto_terminate.assert_called_once_with(
            "haste-exec-1"
        )
        self.assertEqual(
            kwargs["resource_files_for_upload"],
            {
                "in/f.tif": {
                    "file_path": "in/f.tif",
                    "http_url": "https://a.blob.core.windows.net/c/f.tif",
                }
            },
        )

        self.assertEqual(handle.executionId, "exec-1")
        self.assertEqual(handle.selectedBackend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(handle.providerJobId, "haste-exec-1")
        self.assertEqual(handle.providerTaskId, "exec-1")
        self.assertEqual(handle.targetId, "pool-a")
        self.assertEqual(
            handle.outputUri,
            "https://a.blob.core.windows.net/data/proj/task-1/",
        )
        self.assertEqual(handle.providerDetail.discriminator, "batch")
        self.assertEqual(handle.providerDetail.batch.jobId, "haste-exec-1")
        self.assertEqual(handle.providerDetail.batch.taskId, "exec-1")

    def test_folder_input_translates_to_storage_container_url_and_prefix(
        self,
    ):
        runner = _runner()
        spec = _spec(
            inputs=[
                ComputeInput(
                    sourceUri=("https://a.blob.core.windows.net/c/models/v1/"),
                    kind=InputKind.FOLDER,
                    destinationRelativePath="model",
                )
            ]
        )
        runner.submit(spec)
        resource_files = runner.batch_cluster.add_task.call_args.kwargs[
            "resource_files_for_upload"
        ]
        entry = resource_files["model"]
        self.assertEqual(
            entry["storage_container_url"], "https://a.blob.core.windows.net/c"
        )
        self.assertEqual(entry["blob_prefix"], "models/v1")
        self.assertEqual(entry["file_path"], "model")

    def test_task_exists_reconciles_instead_of_raising(self):
        runner = _runner()
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("TaskExists", status_code=409)
        )
        handle = runner.submit(_spec())
        self.assertEqual(handle.providerTaskId, "exec-1")
        self.assertEqual(handle.providerJobId, "haste-exec-1")
        self.assertEqual(handle.targetId, "pool-a")

    def test_other_batch_error_raises_backend_configuration_error(self):
        runner = _runner()
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_exhausted_retry_raises_submission_indeterminate(self):
        runner = _runner()
        underlying = _batch_error("InternalServerError", status_code=500)
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_retry_error(underlying)
        )
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

    def test_deterministic_add_failure_terminates_the_job_it_just_created(
        self,
    ):
        """Quota-leak fix: if this attempt just created a (now-empty)
        job and the subsequent task submission fails deterministically
        (not TaskExists), the empty job must be cleaned up best-effort
        so it doesn't sit there consuming active-job quota."""
        runner = _runner()  # get_execution_job_pool -> None (first submit)
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )

        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

        runner.batch_cluster.terminate_job.assert_called_once_with(
            "haste-exec-1"
        )

    def test_deterministic_add_failure_does_not_terminate_a_job_we_did_not_create(
        self,
    ):
        """A job found via read-first reconciliation (this attempt is a
        retry against an already-existing job) must never be terminated
        on task-submission failure -- it may belong to another
        in-flight attempt/worker, or already have a live task in it."""
        runner = _runner()
        runner.batch_cluster.get_execution_job_pool = MagicMock(
            return_value="pool-a"
        )
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )

        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

        runner.batch_cluster.terminate_job.assert_not_called()

    def test_indeterminate_add_failure_never_terminates_the_job(self):
        """Indeterminate outcomes must never trigger cleanup, even for a
        job this attempt just created: the task may have actually been
        created server-side despite the client-visible failure, and
        terminating the job would destroy it."""
        runner = _runner()  # get_execution_job_pool -> None (we created it)
        underlying = _batch_error("InternalServerError", status_code=500)
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_retry_error(underlying)
        )

        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())

        runner.batch_cluster.terminate_job.assert_not_called()

    def test_cleanup_failure_does_not_mask_the_original_submission_error(
        self,
    ):
        """Best-effort cleanup: if terminate_job itself fails, the
        original deterministic submission error must still propagate,
        never a cleanup-internal error instead."""
        runner = _runner()
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )
        runner.batch_cluster.terminate_job = MagicMock(
            side_effect=RuntimeError("cleanup transport failure")
        )

        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())

    def test_task_exists_reconciliation_never_triggers_cleanup(self):
        """TaskExists is a successful reconciliation, not a submission
        failure -- it must never trigger job cleanup even when this
        attempt just created the job."""
        runner = _runner()  # get_execution_job_pool -> None (we created it)
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("TaskExists", status_code=409)
        )

        runner.submit(_spec())  # must not raise

        runner.batch_cluster.terminate_job.assert_not_called()

    def test_job_creation_rejected_raises_backend_configuration_error(self):
        runner = _runner()
        runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())
        # The task must never be attempted if job creation itself failed.
        runner.batch_cluster.add_task.assert_not_called()

    def test_job_creation_exhausted_retry_raises_submission_indeterminate(
        self,
    ):
        runner = _runner()
        underlying = _batch_error("InternalServerError", status_code=500)
        runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
            side_effect=_retry_error(underlying)
        )
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())
        runner.batch_cluster.add_task.assert_not_called()

    def test_submit_uses_length_safe_job_id_when_execution_id_is_long(self):
        """Regression test: job ids are now derived from executionId
        (not a configured workload/pool value), so a long executionId
        must still be bounded to MAX_JOB_ID_LENGTH before it reaches
        Batch."""
        runner = _runner()
        long_execution_id = "exec-" + "y" * 80
        spec = _spec(executionId=long_execution_id)

        handle = runner.submit(spec)

        self.assertLessEqual(len(handle.providerJobId), 64)
        call_kwargs = runner.batch_cluster.add_task.call_args.kwargs
        self.assertLessEqual(len(call_kwargs["job_id"]), 64)

    def test_task_exists_reconciliation_stays_length_safe_with_long_execution_id(
        self,
    ):
        runner = _runner()
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("TaskExists", status_code=409)
        )
        long_execution_id = "exec-" + "y" * 80
        spec = _spec(executionId=long_execution_id)

        handle = runner.submit(spec)

        self.assertLessEqual(len(handle.providerJobId), 64)

    def test_first_creator_uses_capacity_aware_pool_selection(self):
        """Preserve multi-pool capacity-aware routing (v2.1.0) for the
        first creator: the live-selected pool is what job creation is
        asked to prefer."""
        runner = _runner(candidate_pool_ids=["pool-a", "pool-b"])
        runner.batch_cluster.select_pool = MagicMock(return_value="pool-b")
        runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
            return_value=("pool-b", True)
        )

        handle = runner.submit(_spec())

        runner.batch_cluster.select_pool.assert_called_once_with(
            ["pool-a", "pool-b"]
        )
        runner.batch_cluster.get_or_create_job_for_execution.assert_called_once_with(
            "haste-exec-1", "pool-b"
        )
        self.assertEqual(handle.targetId, "pool-b")

    def test_sequential_retry_after_capacity_selection_changes_reconciles_to_first_pool(
        self,
    ):
        """Regression test for the atomic job-creation primitive's own
        race handling: even in the narrow window where two attempts'
        read-first ``get_execution_job_pool`` lookups *both* find
        nothing yet (a genuine concurrent creation race, not the common
        sequential-retry-with-existing-job case — see the dedicated test
        below for that), a live pool-selection change between them must
        still reconcile to the job/task the first attempt actually
        created — never a second, pool-scoped duplicate."""
        runner = _runner(candidate_pool_ids=["pool-a", "pool-b"])
        runner.batch_cluster.select_pool = MagicMock(
            side_effect=["pool-a", "pool-b"]
        )
        runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
            side_effect=[
                ("pool-a", True),  # first attempt: creator
                ("pool-a", False),  # second: capacity changed (prefers
                #                     pool-b) but the job already exists
                #                     on pool-a, so it reconciles there
            ]
        )
        runner.batch_cluster.add_task = MagicMock(
            side_effect=[None, _batch_error("TaskExists", status_code=409)]
        )

        spec = _spec()
        first_handle = runner.submit(spec)
        second_handle = runner.submit(spec)  # simulated retry

        calls = (
            runner.batch_cluster.get_or_create_job_for_execution.call_args_list
        )
        self.assertEqual(calls[0].args, ("haste-exec-1", "pool-a"))
        # The retry's own (changed) capacity selection is still passed
        # through as the *preferred* pool...
        self.assertEqual(calls[1].args, ("haste-exec-1", "pool-b"))
        # ...but must never leak into either handle: both reconcile to
        # the pool the first attempt actually created.
        self.assertEqual(first_handle.targetId, "pool-a")
        self.assertEqual(second_handle.targetId, "pool-a")
        self.assertEqual(
            first_handle.providerJobId, second_handle.providerJobId
        )
        self.assertEqual(
            first_handle.providerTaskId, second_handle.providerTaskId
        )

    def test_retry_with_existing_job_skips_pool_selection_and_creation(self):
        """Read-first fix: once ``get_execution_job_pool`` confirms this
        executionId's job already exists, a retry must never re-run
        ``select_pool``/``create_pool_if_not_exists``/
        ``get_or_create_job_for_execution`` at all — even if the pool
        that a fresh selection *would* return is unavailable/deleted —
        and must go straight to task reconciliation on the job's actual
        bound pool."""
        runner = _runner(
            manage_pools=True, candidate_pool_ids=["pool-a", "pool-b"]
        )
        runner.batch_config[
            "user_assigned_identity_resource_id"
        ] = "/subscriptions/x/umi"
        # The job already exists, bound to pool-a from the original
        # submission. A naive implementation would call select_pool()
        # again and could get back a pool that's since been
        # deleted/unavailable — that must never be consulted at all.
        runner.batch_cluster.get_execution_job_pool = MagicMock(
            return_value="pool-a"
        )
        runner.batch_cluster.select_pool = MagicMock(
            return_value="pool-deleted"
        )

        handle = runner.submit(_spec())

        runner.batch_cluster.select_pool.assert_not_called()
        runner.batch_cluster.create_pool_if_not_exists.assert_not_called()
        runner.batch_cluster.get_or_create_job_for_execution.assert_not_called()
        self.assertEqual(handle.targetId, "pool-a")
        self.assertEqual(handle.providerJobId, "haste-exec-1")
        add_task_kwargs = runner.batch_cluster.add_task.call_args.kwargs
        self.assertEqual(add_task_kwargs["job_id"], "haste-exec-1")

    def test_retry_with_existing_job_reconciles_task_exists_without_reselecting_pool(
        self,
    ):
        """Same as above, but the retry's own add_task call additionally
        loses a task-level race (TaskExists) — reconciliation must still
        never touch pool selection/creation."""
        runner = _runner(candidate_pool_ids=["pool-a", "pool-b"])
        runner.batch_cluster.get_execution_job_pool = MagicMock(
            return_value="pool-a"
        )
        runner.batch_cluster.select_pool = MagicMock(
            return_value="pool-deleted"
        )
        runner.batch_cluster.add_task = MagicMock(
            side_effect=_batch_error("TaskExists", status_code=409)
        )

        handle = runner.submit(_spec())

        runner.batch_cluster.select_pool.assert_not_called()
        runner.batch_cluster.get_or_create_job_for_execution.assert_not_called()
        self.assertEqual(handle.targetId, "pool-a")

    def test_job_lookup_rejected_raises_backend_configuration_error(self):
        runner = _runner()
        runner.batch_cluster.get_execution_job_pool = MagicMock(
            side_effect=_batch_error("InvalidPropertyValue", status_code=400)
        )
        with self.assertRaises(BackendConfigurationError):
            runner.submit(_spec())
        runner.batch_cluster.select_pool.assert_not_called()
        runner.batch_cluster.add_task.assert_not_called()

    def test_job_lookup_exhausted_retry_raises_submission_indeterminate(
        self,
    ):
        runner = _runner()
        underlying = _batch_error("InternalServerError", status_code=500)
        runner.batch_cluster.get_execution_job_pool = MagicMock(
            side_effect=_retry_error(underlying)
        )
        with self.assertRaises(SubmissionIndeterminateError):
            runner.submit(_spec())
        runner.batch_cluster.select_pool.assert_not_called()
        runner.batch_cluster.add_task.assert_not_called()

    def test_two_worker_job_exists_race_choosing_different_pools_reconciles_to_one_job(
        self,
    ):
        """Simulated two-worker concurrent not-found race: both
        'workers' independently find (via read-first
        ``get_execution_job_pool``) that no job exists yet for this
        executionId, then each selects a different candidate pool via
        live capacity selection at their own moment. Exactly one Batch
        job/task must result — never one per pool."""
        runner = _runner(candidate_pool_ids=["pool-a", "pool-b"])
        # Worker A's live capacity selection prefers pool-a and wins the
        # job-creation race; Worker B's prefers pool-b and loses it.
        runner.batch_cluster.select_pool = MagicMock(
            side_effect=["pool-a", "pool-b"]
        )
        runner.batch_cluster.get_or_create_job_for_execution = MagicMock(
            side_effect=[
                ("pool-a", True),  # Worker A wins the creation race
                ("pool-a", False),  # Worker B loses it, reconciles
            ]
        )
        # Worker A's task.add() succeeds; Worker B's loses that race too.
        runner.batch_cluster.add_task = MagicMock(
            side_effect=[None, _batch_error("TaskExists", status_code=409)]
        )

        spec = _spec()
        handle_a = runner.submit(spec)
        handle_b = runner.submit(spec)

        # Both "workers" genuinely found nothing on their read-first
        # lookup -- this is what makes it a real concurrent-creation
        # race rather than a sequential retry against an already-bound
        # job.
        self.assertEqual(
            runner.batch_cluster.get_execution_job_pool.call_count, 2
        )

        # Exactly one Batch job/task: same ids, same pool, for both
        # "workers".
        self.assertEqual(handle_a.providerJobId, handle_b.providerJobId)
        self.assertEqual(handle_a.providerTaskId, handle_b.providerTaskId)
        self.assertEqual(handle_a.targetId, "pool-a")
        self.assertEqual(handle_b.targetId, "pool-a")

        # Both workers' add_task calls agree on the same job id and the
        # same output writer (output_container_url/output_prefix) —
        # neither diverged onto its own preferred pool.
        call_a = runner.batch_cluster.add_task.call_args_list[0].kwargs
        call_b = runner.batch_cluster.add_task.call_args_list[1].kwargs
        self.assertEqual(call_a["job_id"], call_b["job_id"])
        self.assertEqual(
            call_a["output_container_url"], call_b["output_container_url"]
        )
        self.assertEqual(call_a["output_prefix"], call_b["output_prefix"])


class TestExecutionJobId(unittest.TestCase):
    """Direct unit tests for the deterministic per-execution job id
    helper (the fix for the cross-pool duplicate-task bug: a job id
    derived only from executionId never changes across retries, unlike
    the legacy pool-scoped ``resolve_job_id`` convention)."""

    def test_short_execution_id_is_prefixed_and_unchanged(self):
        runner = _runner()
        self.assertEqual(runner._execution_job_id("exec-1"), "haste-exec-1")

    def test_deterministic_for_the_same_execution_id(self):
        runner = _runner()
        first = runner._execution_job_id("exec-1")
        second = runner._execution_job_id("exec-1")
        self.assertEqual(first, second)

    def test_long_execution_id_is_truncated_and_bounded(self):
        runner = _runner()
        result = runner._execution_job_id("x" * 100)
        self.assertLessEqual(len(result), 64)

    def test_distinct_long_execution_ids_yield_distinct_job_ids(self):
        """Regression test: a plain slice would collide two long
        executionIds sharing the same prefix into the same job id."""
        runner = _runner()
        shared_prefix = "x" * 80
        id_a = runner._execution_job_id(shared_prefix + "-a")
        id_b = runner._execution_job_id(shared_prefix + "-b")
        self.assertNotEqual(id_a, id_b)


class TestGetStatus(unittest.TestCase):
    def test_maps_completed_to_succeeded(self):
        runner = _runner()
        runner.get_task_status = MagicMock(return_value="Processed")
        self.assertEqual(
            runner.get_status(_handle()), ComputeJobState.SUCCEEDED
        )

    def test_maps_failed_to_failed(self):
        runner = _runner()
        runner.get_task_status = MagicMock(return_value="Failed")
        self.assertEqual(runner.get_status(_handle()), ComputeJobState.FAILED)

    def test_maps_in_progress_to_running(self):
        runner = _runner()
        runner.get_task_status = MagicMock(return_value="InProgress")
        self.assertEqual(runner.get_status(_handle()), ComputeJobState.RUNNING)

    def test_unmapped_status_logs_raw_status_before_raising(self):
        """F10: an unrecognized provider status must be logged
        server-side (raw status + correlation IDs) before the typed
        error is raised, matching the AML adapter's unmapped-status
        diagnostics — never silently reported as "running"."""
        runner = _runner()
        runner.get_task_status = MagicMock(return_value="SomeWeirdState")

        with self.assertRaises(BackendUnavailableError):
            runner.get_status(_handle())

        runner.logger.error.assert_called_once()
        args = runner.logger.error.call_args.args
        self.assertIn("SomeWeirdState", args)
        self.assertIn("exec-1", args)  # providerTaskId from _handle()
        self.assertIn("job-1", args)  # providerJobId from _handle()

    def test_task_not_found_raises_job_not_found_error(self):
        runner = _runner()
        runner.get_task_status = MagicMock(
            side_effect=_batch_error("TaskNotFound", status_code=404)
        )
        with self.assertRaises(JobNotFoundError):
            runner.get_status(_handle())

    def test_other_error_raises_backend_unavailable(self):
        runner = _runner()
        runner.get_task_status = MagicMock(
            side_effect=_batch_error("InternalServerError", status_code=500)
        )
        with self.assertRaises(BackendUnavailableError):
            runner.get_status(_handle())


class TestReadOutput(unittest.TestCase):
    def test_rejects_path_traversal_before_any_provider_call(self):
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(return_value="hello")
        with self.assertRaises(ValueError):
            runner.read_output(_handle(), "../../etc/passwd")
        runner.get_filecontent_from_task.assert_not_called()

    def test_rejects_absolute_path(self):
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(return_value="hello")
        with self.assertRaises(ValueError):
            runner.read_output(_handle(), "/etc/passwd")
        runner.get_filecontent_from_task.assert_not_called()

    def test_delegates_to_legacy_method(self):
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(return_value="hello")
        result = runner.read_output(_handle(), "progress.log")
        self.assertEqual(result, "hello")
        runner.get_filecontent_from_task.assert_called_once_with(
            "job-1", "exec-1", "progress.log", as_chunk=False
        )

    def test_returns_none_when_legacy_method_returns_none(self):
        # Node-loss / not-yet-available handling already lives in
        # get_filecontent_from_task (see test_azure_batch_node_errors.py);
        # this only pins that read_output() passes that None straight
        # through rather than raising.
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(return_value=None)
        self.assertIsNone(runner.read_output(_handle(), "missing.log"))

    def test_task_not_found_raises_job_not_found_error(self):
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(
            side_effect=_batch_error("TaskNotFound", status_code=404)
        )
        with self.assertRaises(JobNotFoundError):
            runner.read_output(_handle(), "x.log")

    def test_other_error_raises_output_not_available(self):
        runner = _runner()
        runner.get_filecontent_from_task = MagicMock(
            side_effect=_batch_error("InternalServerError", status_code=500)
        )
        with self.assertRaises(OutputNotAvailableError):
            runner.read_output(_handle(), "x.log")


class TestCancel(unittest.TestCase):
    def test_delegates_to_legacy_method(self):
        runner = _runner()
        runner.cancel_task = MagicMock(return_value="cancelled")
        runner.cancel(_handle())
        runner.cancel_task.assert_called_once_with("job-1", "exec-1")

    def test_wraps_batch_error_as_job_cancellation_error(self):
        runner = _runner()
        runner.cancel_task = MagicMock(
            side_effect=_batch_error("InternalServerError", status_code=500)
        )
        with self.assertRaises(JobCancellationError):
            runner.cancel(_handle())


class TestFinalize(unittest.TestCase):
    def test_disables_job_when_no_other_active_tasks(self):
        runner = _runner()
        runner.batch_cluster.list_tasks.return_value = []
        runner.finalize(_handle())
        runner.batch_cluster.delete_files_from_task.assert_called_once_with(
            "job-1", "exec-1"
        )
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_does_not_disable_job_with_other_active_tasks(self):
        """Regression test for the shared-Batch-job finalize bug: a job
        with another still-active task must not be disabled."""
        runner = _runner()
        other_task = MagicMock()
        other_task.id = "other-task"
        other_task.state = TaskState.running
        runner.batch_cluster.list_tasks.return_value = [other_task]
        runner.finalize(_handle())
        runner.batch_cluster.disable_job.assert_not_called()

    def test_disables_job_when_other_tasks_are_all_completed(self):
        runner = _runner()
        other_task = MagicMock()
        other_task.id = "other-task"
        other_task.state = TaskState.completed
        runner.batch_cluster.list_tasks.return_value = [other_task]
        runner.finalize(_handle())
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_idempotent_second_call_with_files_already_removed(self):
        runner = _runner()
        runner.batch_cluster.list_tasks.return_value = []
        runner.batch_cluster.delete_files_from_task.side_effect = _batch_error(
            "FileNotFound", status_code=404
        )
        runner.finalize(_handle())  # must not raise
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_tolerates_node_unavailable_during_file_cleanup(self):
        runner = _runner()
        runner.batch_cluster.list_tasks.return_value = []
        runner.batch_cluster.delete_files_from_task.side_effect = _batch_error(
            "NodeNotFound", status_code=404
        )
        runner.finalize(_handle())  # must not raise
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_reraises_unclassified_file_cleanup_error(self):
        runner = _runner()
        runner.batch_cluster.list_tasks.return_value = []
        runner.batch_cluster.delete_files_from_task.side_effect = _batch_error(
            "SomeOtherError", status_code=400
        )
        with self.assertRaises(BatchErrorException):
            runner.finalize(_handle())

    def test_missing_job_during_active_task_check_treated_as_no_other_tasks(
        self,
    ):
        runner = _runner()
        runner.batch_cluster.list_tasks.side_effect = _batch_error(
            "JobNotFound", status_code=404
        )
        runner.finalize(_handle())  # must not raise
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_terminates_per_execution_job_instead_of_disabling(self):
        """Quota-leak fix: a per-execution job (deterministic
        haste-{executionId} job id) must be terminated, not merely
        disabled, so it releases its active-job quota slot."""
        runner = _runner()
        handle = _handle(providerJobId="haste-exec-1")

        runner.finalize(handle)

        runner.batch_cluster.terminate_job.assert_called_once_with(
            "haste-exec-1"
        )
        runner.batch_cluster.disable_job.assert_not_called()

    def test_per_execution_finalize_never_checks_for_other_active_tasks(
        self,
    ):
        """Active-job-quota safety: per-execution jobs hold exactly one
        task, so finalize must terminate unconditionally rather than
        running the shared-job "other active tasks" check at all -- a
        stale/misreported active task there must never block releasing
        the quota slot."""
        runner = _runner()
        handle = _handle(providerJobId="haste-exec-1")

        runner.finalize(handle)

        runner.batch_cluster.list_tasks.assert_not_called()

    def test_per_execution_finalize_is_idempotent(self):
        runner = _runner()
        handle = _handle(providerJobId="haste-exec-1")

        runner.finalize(handle)
        runner.finalize(handle)  # must not raise

        self.assertEqual(runner.batch_cluster.terminate_job.call_count, 2)

    def test_legacy_shared_job_is_still_only_disabled_not_terminated(self):
        """Preserve legacy cleanup_task/finalize behavior for old shared
        pool-scoped jobs (multiple tasks/executions per job, from before
        this per-execution design): those must never be terminated,
        since that would kill every other task still running in them."""
        runner = _runner()
        runner.batch_cluster.list_tasks.return_value = []
        handle = _handle(providerJobId="training-pool")  # legacy job id

        runner.finalize(handle)

        runner.batch_cluster.disable_job.assert_called_once_with(
            "training-pool"
        )
        runner.batch_cluster.terminate_job.assert_not_called()


class TestGetCapacity(unittest.TestCase):
    def test_available_when_a_candidate_pool_has_an_idle_node(self):
        runner = _runner(candidate_pool_ids=["pool-a", "pool-b"])
        runner.batch_cluster._pool_has_idle_node.side_effect = (
            lambda pid: pid == "pool-b"
        )
        snapshot = runner.get_capacity(ComputeWorkload.TRAINING, MagicMock())
        self.assertEqual(snapshot.state, CapacityState.AVAILABLE)

    def test_queueable_when_no_pool_has_an_idle_node(self):
        runner = _runner(candidate_pool_ids=["pool-a"])
        runner.batch_cluster._pool_has_idle_node.return_value = False
        snapshot = runner.get_capacity(ComputeWorkload.TRAINING, MagicMock())
        self.assertEqual(snapshot.state, CapacityState.QUEUEABLE)

    def test_unknown_when_capacity_check_fails(self):
        runner = _runner(candidate_pool_ids=["pool-a"])
        runner.batch_cluster._pool_has_idle_node.side_effect = _batch_error(
            "InternalServerError", status_code=500
        )
        snapshot = runner.get_capacity(ComputeWorkload.TRAINING, MagicMock())
        self.assertEqual(snapshot.state, CapacityState.UNKNOWN)

    def test_snapshot_backend_and_workload_are_set(self):
        runner = _runner(candidate_pool_ids=["pool-a"])
        runner.batch_cluster._pool_has_idle_node.return_value = True
        snapshot = runner.get_capacity(ComputeWorkload.INFERENCE, MagicMock())
        self.assertEqual(snapshot.backend, ComputeBackend.AZURE_BATCH)
        self.assertEqual(snapshot.workload, ComputeWorkload.INFERENCE)


if __name__ == "__main__":
    unittest.main()
