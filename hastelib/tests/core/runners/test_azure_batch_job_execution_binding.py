# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Direct unit tests for ``AzureBatchJob.get_or_create_job_for_execution``,
``get_execution_job_pool``, and ``terminate_job``: the atomic,
first-writer-wins job creation/binding primitives (fixing the
High-severity cross-pool duplicate-task bug) plus the quota-leak fix that
auto-terminates each per-execution job once its single task completes,
so it doesn't sit there consuming active-job quota.

Uses the same ``AzureBatchJob`` construction pattern as
``test_azure_batch_routing.py``, with a mocked ``batch_client`` — no live
Batch calls.
"""

import unittest
from unittest.mock import MagicMock

from azure.batch.models import (
    BatchError,
    BatchErrorException,
    ErrorMessage,
    JobState,
    OnAllTasksComplete,
)
from hastegeo.core.runners.azure_batch import AzureBatchJob


def _job():
    job = AzureBatchJob(
        account_name="acct",  # pragma: allowlist secret
        account_key="key",  # pragma: allowlist secret
        batch_url="https://acct.westus2.batch.azure.com",  # pragma: allowlist secret
        pool_id="default-pool",
        user_assigned_identity_resource_id="/subscriptions/x/umi",
        use_sas=False,
        manage_pools=True,
    )
    job.batch_client = MagicMock()
    return job


def _job_exists_error():
    exc = BatchErrorException.__new__(BatchErrorException)
    exc.error = BatchError(code="JobExists", message=ErrorMessage(value="x"))
    exc.response = MagicMock(status_code=409)
    return exc


def _job_not_found_error():
    exc = BatchErrorException.__new__(BatchErrorException)
    exc.error = BatchError(code="JobNotFound", message=ErrorMessage(value="x"))
    exc.response = MagicMock(status_code=404)
    return exc


def _other_batch_error(code="InvalidPropertyValue", status_code=400):
    exc = BatchErrorException.__new__(BatchErrorException)
    exc.error = BatchError(code=code, message=ErrorMessage(value="x"))
    exc.response = MagicMock(status_code=status_code)
    return exc


class TestGetOrCreateJobForExecution(unittest.TestCase):
    def test_first_creator_binds_job_to_preferred_pool(self):
        job = _job()
        result = job.get_or_create_job_for_execution("haste-exec-1", "pool-a")

        self.assertEqual(result, ("pool-a", True))
        job.batch_client.job.add.assert_called_once()
        added = job.batch_client.job.add.call_args.args[0]
        self.assertEqual(added.id, "haste-exec-1")
        self.assertEqual(added.pool_info.pool_id, "pool-a")
        job.batch_client.job.get.assert_not_called()

    def test_creates_job_with_no_action_until_the_task_is_added(self):
        """An empty job must not terminate before its task is added."""
        job = _job()
        job.get_or_create_job_for_execution("haste-exec-1", "pool-a")

        added = job.batch_client.job.add.call_args.args[0]
        self.assertEqual(
            added.on_all_tasks_complete, OnAllTasksComplete.no_action
        )

    def test_job_exists_reconciles_to_the_jobs_actual_bound_pool(self):
        """A losing attempt's own preferred pool must never win: the
        method must return the pool the job is *actually* bound to, even
        when that differs from what this call asked for -- and report
        created=False since this call didn't create the job."""
        job = _job()
        job.batch_client.job.add.side_effect = _job_exists_error()
        existing_job = MagicMock()
        existing_job.state = JobState.active
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_or_create_job_for_execution("haste-exec-1", "pool-b")

        self.assertEqual(result, ("pool-a", False))
        job.batch_client.job.enable.assert_not_called()

    def test_job_exists_reenables_a_disabled_job_before_returning(self):
        job = _job()
        job.batch_client.job.add.side_effect = _job_exists_error()
        existing_job = MagicMock()
        existing_job.state = JobState.disabled
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_or_create_job_for_execution("haste-exec-1", "pool-b")

        self.assertEqual(result, ("pool-a", False))
        job.batch_client.job.enable.assert_called_once_with("haste-exec-1")

    def test_job_exists_and_already_completed_is_not_reenabled(self):
        """Quota-leak fix regression: if the job already auto-terminated
        (completed) between our read-first check and this add() losing
        the race, it must be treated as already reconciled -- re-enabling
        it here would defeat the auto-terminate and leak the quota slot
        right back."""
        job = _job()
        job.batch_client.job.add.side_effect = _job_exists_error()
        existing_job = MagicMock()
        existing_job.state = JobState.completed
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_or_create_job_for_execution("haste-exec-1", "pool-b")

        self.assertEqual(result, ("pool-a", False))
        job.batch_client.job.enable.assert_not_called()

    def test_job_exists_with_unresolvable_pool_falls_back_to_preferred(self):
        job = _job()
        job.batch_client.job.add.side_effect = _job_exists_error()
        existing_job = MagicMock()
        existing_job.state = JobState.active
        existing_job.pool_info = None
        job.batch_client.job.get.return_value = existing_job

        result = job.get_or_create_job_for_execution("haste-exec-1", "pool-b")

        self.assertEqual(result, ("pool-b", False))

    def test_never_creates_a_second_job_when_one_already_exists(self):
        job = _job()
        job.batch_client.job.add.side_effect = _job_exists_error()
        existing_job = MagicMock()
        existing_job.state = JobState.active
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        job.get_or_create_job_for_execution("haste-exec-1", "pool-b")

        # Only the one (rejected) add() call — no retry with a different
        # job id/name and no second add() attempt.
        self.assertEqual(job.batch_client.job.add.call_count, 1)

    def test_unrelated_batch_error_on_add_is_not_swallowed(self):
        job = _job()
        job.batch_client.job.add.side_effect = _other_batch_error()

        with self.assertRaises(BatchErrorException):
            job.get_or_create_job_for_execution("haste-exec-1", "pool-a")
        job.batch_client.job.get.assert_not_called()


class TestGetExecutionJobPool(unittest.TestCase):
    """Direct unit tests for the read-first reconciliation lookup that
    must run before any pool selection/creation on every submit
    attempt."""

    def test_returns_none_when_job_does_not_exist(self):
        job = _job()
        job.batch_client.job.get.side_effect = _job_not_found_error()

        result = job.get_execution_job_pool("haste-exec-1")

        self.assertIsNone(result)
        job.batch_client.job.enable.assert_not_called()

    def test_returns_bound_pool_when_job_exists_and_is_active(self):
        job = _job()
        existing_job = MagicMock()
        existing_job.state = JobState.active
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_execution_job_pool("haste-exec-1")

        self.assertEqual(result, "pool-a")
        job.batch_client.job.enable.assert_not_called()

    def test_reenables_a_disabled_job_before_returning_its_pool(self):
        job = _job()
        existing_job = MagicMock()
        existing_job.state = JobState.disabled
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_execution_job_pool("haste-exec-1")

        self.assertEqual(result, "pool-a")
        job.batch_client.job.enable.assert_called_once_with("haste-exec-1")

    def test_completed_job_is_treated_as_already_reconciled_and_not_reenabled(
        self,
    ):
        """Quota-leak fix regression: a retry against an executionId
        whose single-task job already auto-terminated (completed) must
        return its bound pool without ever calling job.enable() --
        re-enabling it would defeat the auto-terminate and leak the
        active-job quota slot the whole design exists to release."""
        job = _job()
        existing_job = MagicMock()
        existing_job.state = JobState.completed
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        result = job.get_execution_job_pool("haste-exec-1")

        self.assertEqual(result, "pool-a")
        job.batch_client.job.enable.assert_not_called()

    def test_unrelated_batch_error_on_get_is_not_swallowed(self):
        job = _job()
        job.batch_client.job.get.side_effect = _other_batch_error()

        with self.assertRaises(BatchErrorException):
            job.get_execution_job_pool("haste-exec-1")

    def test_never_calls_job_add(self):
        """This is a read-only lookup: it must never itself create a
        job, regardless of whether one is found."""
        job = _job()
        existing_job = MagicMock()
        existing_job.state = JobState.active
        existing_job.pool_info.pool_id = "pool-a"
        job.batch_client.job.get.return_value = existing_job

        job.get_execution_job_pool("haste-exec-1")

        job.batch_client.job.add.assert_not_called()


class TestTerminateJob(unittest.TestCase):
    """Direct unit tests for the idempotent low-level termination
    primitive used both by ``AzureBatchRunner.finalize`` (per-execution
    jobs) and by best-effort cleanup of a job left empty by a
    deterministic task-submission failure."""

    def test_terminates_the_job(self):
        job = _job()
        job.terminate_job("haste-exec-1")
        job.batch_client.job.terminate.assert_called_once_with("haste-exec-1")

    def test_job_not_found_is_a_no_op(self):
        job = _job()
        job.batch_client.job.terminate.side_effect = _job_not_found_error()
        job.terminate_job("haste-exec-1")  # must not raise

    def test_job_already_completed_is_a_no_op(self):
        job = _job()
        job.batch_client.job.terminate.side_effect = _other_batch_error(
            code="JobCompleted", status_code=409
        )
        job.terminate_job("haste-exec-1")  # must not raise

    def test_unrelated_batch_error_is_not_swallowed(self):
        job = _job()
        job.batch_client.job.terminate.side_effect = _other_batch_error()

        with self.assertRaises(BatchErrorException):
            job.terminate_job("haste-exec-1")


class TestArmJobAutoTerminate(unittest.TestCase):
    def test_patches_job_after_task_creation(self):
        job = _job()

        job.arm_job_auto_terminate("haste-exec-1")

        job.batch_client.job.patch.assert_called_once()
        patched = job.batch_client.job.patch.call_args.args[1]
        self.assertEqual(
            patched.on_all_tasks_complete, OnAllTasksComplete.terminate_job
        )

    def test_completed_or_missing_job_is_a_no_op(self):
        for code in ("JobNotFound", "JobCompleted"):
            with self.subTest(code=code):
                job = _job()
                job.batch_client.job.patch.side_effect = _other_batch_error(
                    code=code, status_code=409
                )
                job.arm_job_auto_terminate("haste-exec-1")


if __name__ == "__main__":
    unittest.main()
