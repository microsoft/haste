# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for Azure Batch node-loss handling.

The node-scoped file APIs (``file.list_from_task`` / ``get_from_task`` /
``delete_from_task``) are answered by the compute node that ran the task, so
they start failing the moment that node is deallocated or preempted — which on
an autoscale pool is exactly when the task completes. These tests pin the
resulting behavior: transient node errors are retried, terminal ones degrade to
"file unavailable" instead of failing the workload, and unrelated Batch errors
still propagate.
"""

import unittest
from unittest.mock import MagicMock

from azure.batch.models import BatchError, BatchErrorException, ErrorMessage
from hastegeo.core.runners.azure_batch import (
    AzureBatchRunner,
    batch_error_code,
    is_node_unavailable_error,
    is_retryable_batch_error,
    is_server_error,
    is_terminal_node_error,
    is_transient_node_error,
    retry_on_server_error,
)
from tenacity import wait_none


def _batch_error(code, status_code=409, value="node is busy"):
    """Build a BatchErrorException without going through the deserializer."""
    exc = BatchErrorException.__new__(BatchErrorException)
    exc.error = BatchError(code=code, message=ErrorMessage(value=value))
    exc.response = MagicMock(status_code=status_code)
    return exc


def _runner():
    """An AzureBatchRunner with only the collaborators these tests touch."""
    runner = AzureBatchRunner.__new__(AzureBatchRunner)
    runner.batch_cluster = MagicMock()
    runner.logger = MagicMock()
    return runner


class TestBatchErrorClassification(unittest.TestCase):
    def test_node_not_ready_is_transient_and_retryable(self):
        # The failure reported from dev1: a 409, not a 5xx.
        exc = _batch_error("NodeNotReady", status_code=409)
        self.assertTrue(is_transient_node_error(exc))
        self.assertFalse(is_terminal_node_error(exc))
        self.assertTrue(is_node_unavailable_error(exc))
        self.assertTrue(is_retryable_batch_error(exc))
        self.assertFalse(is_server_error(exc))

    def test_node_state_invalid_is_transient(self):
        exc = _batch_error("NodeStateInvalid", status_code=409)
        self.assertTrue(is_transient_node_error(exc))
        self.assertTrue(is_retryable_batch_error(exc))

    def test_node_not_found_is_terminal_but_unavailable(self):
        exc = _batch_error("NodeNotFound", status_code=404)
        self.assertTrue(is_terminal_node_error(exc))
        self.assertFalse(is_transient_node_error(exc))
        self.assertTrue(is_node_unavailable_error(exc))
        # Retrying cannot bring a deallocated node back.
        self.assertFalse(is_retryable_batch_error(exc))

    def test_server_errors_remain_retryable(self):
        exc = _batch_error("InternalServerError", status_code=500)
        self.assertTrue(is_server_error(exc))
        self.assertTrue(is_retryable_batch_error(exc))

    def test_unrelated_client_error_is_not_retryable(self):
        exc = _batch_error("TaskNotFound", status_code=404)
        self.assertFalse(is_retryable_batch_error(exc))
        self.assertFalse(is_node_unavailable_error(exc))

    def test_non_batch_exception_is_not_retryable(self):
        exc = ValueError("boom")
        self.assertIsNone(batch_error_code(exc))
        self.assertFalse(is_retryable_batch_error(exc))
        self.assertFalse(is_node_unavailable_error(exc))


class TestRetryOnServerError(unittest.TestCase):
    def _no_wait(self, func):
        # Keep the real predicate/stop policy, drop only the backoff sleep.
        return func.retry_with(wait=wait_none())

    def test_retries_node_not_ready_until_it_succeeds(self):
        calls = {"n": 0}

        @retry_on_server_error()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _batch_error("NodeNotReady")
            return "ok"

        self.assertEqual(self._no_wait(flaky)(), "ok")
        self.assertEqual(calls["n"], 3)

    def test_reraises_the_batch_error_not_a_retry_error(self):
        @retry_on_server_error()
        def always_failing():
            raise _batch_error("NodeNotReady")

        # reraise=True keeps the error classifiable by callers instead of
        # burying it in tenacity's RetryError.
        with self.assertRaises(BatchErrorException) as ctx:
            self._no_wait(always_failing)()
        self.assertEqual(ctx.exception.error.code, "NodeNotReady")

    def test_does_not_retry_unrelated_errors(self):
        calls = {"n": 0}

        @retry_on_server_error()
        def failing():
            calls["n"] += 1
            raise _batch_error("TaskNotFound", status_code=404)

        with self.assertRaises(BatchErrorException):
            self._no_wait(failing)()
        self.assertEqual(calls["n"], 1)


class TestGetFileContentFromTask(unittest.TestCase):
    def test_returns_none_when_node_is_gone(self):
        runner = _runner()
        runner.batch_cluster.get_file_by_match_from_task.side_effect = (
            _batch_error("NodeNotFound", status_code=404)
        )
        self.assertIsNone(
            runner.get_filecontent_from_task(
                "job-1", "task-1", "imagery_manifest.json"
            )
        )
        runner.logger.warning.assert_called_once()

    def test_returns_none_when_node_never_became_ready(self):
        runner = _runner()
        runner.batch_cluster.get_file_by_match_from_task.return_value = (
            "wd/logs/imagery_friendly.log"
        )
        runner.batch_cluster.get_file_from_task.side_effect = _batch_error(
            "NodeNotReady"
        )
        self.assertIsNone(
            runner.get_filecontent_from_task(
                "job-1", "task-1", "imagery_friendly.log"
            )
        )

    def test_propagates_unrelated_batch_errors(self):
        runner = _runner()
        runner.batch_cluster.get_file_by_match_from_task.side_effect = (
            _batch_error("JobNotFound", status_code=404)
        )
        with self.assertRaises(BatchErrorException):
            runner.get_filecontent_from_task("job-1", "task-1", "any.json")

    def test_reads_content_when_the_node_answers(self):
        runner = _runner()
        runner.batch_cluster.get_file_by_match_from_task.return_value = (
            "wd/outputs/imagery_manifest.json"
        )
        runner.batch_cluster.get_file_from_task.return_value = [
            b'{"a": ',
            b"1}",
        ]
        self.assertEqual(
            runner.get_filecontent_from_task(
                "job-1", "task-1", "imagery_manifest.json"
            ),
            '{"a": 1}',
        )


class TestCleanupTask(unittest.TestCase):
    def test_skips_working_directory_cleanup_when_node_is_gone(self):
        runner = _runner()
        runner.batch_cluster.delete_files_from_task.side_effect = _batch_error(
            "NodeNotReady"
        )
        runner.cleanup_task("job-1", "task-1")
        # The job still has to be disabled — cleanup of a dead node's disk is
        # handled by the task retention time.
        runner.batch_cluster.disable_job.assert_called_once_with("job-1")

    def test_propagates_unrelated_batch_errors(self):
        runner = _runner()
        runner.batch_cluster.delete_files_from_task.side_effect = _batch_error(
            "OperationTimedOut", status_code=408
        )
        with self.assertRaises(BatchErrorException):
            runner.cleanup_task("job-1", "task-1")
        runner.batch_cluster.disable_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
