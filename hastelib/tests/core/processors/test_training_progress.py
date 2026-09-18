# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.models.compute import (
    AzureMlProviderDetail,
    ComputeBackend,
    ComputeJobHandle,
    ComputeJobState,
    ComputeProviderDetail,
    OutputNotAvailableError,
)
from hastegeo.core.models.projects import Model, TrainingJob
from hastegeo.core.processors.train import TrainPostprocessor
from hastegeo.core.runners.execution_service import ComputeExecutionService


class TestTrainingProgress(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.processor = TrainPostprocessor.__new__(TrainPostprocessor)
        self.processor.config = Config()
        self.statuses = self.processor.config.get_status_types()
        self.handle = ComputeJobHandle(
            executionId="task-1",
            requestedBackend=ComputeBackend.AZURE_ML,
            selectedBackend=ComputeBackend.AZURE_ML,
            backendProfile="training",
            providerJobId="aml-training-task-1",
            targetId="training-gpu",
            outputUri="https://account.blob.core.windows.net/data/project-1/task-1",
            submittedAt="2026-01-01T00:00:00+00:00",
            routingReason="explicit",
            providerDetail=ComputeProviderDetail(
                discriminator="azure_ml",
                azureMl=AzureMlProviderDetail(
                    jobName="aml-training-task-1", workspace="workspace"
                ),
            ),
        )
        self.processor.model_data = Model(
            modelId="42",
            projectId="project-1",
            maxEpochs="1",
            status=self.statuses.IN_PROGRESS.value,
            currentStep=0,
            totalSteps=2,
            progressPct=0,
            trainingJob=TrainingJob(
                jobId="job-1",
                taskId="task-1",
                status=self.statuses.IN_PROGRESS.value,
                computeJob=self.handle,
            ),
        )
        self.processor.temp_dir = self.temporary.name
        self.processor.logger = MagicMock()
        self.processor.queue_client = MagicMock()
        self.processor.execution_service = MagicMock(
            spec=ComputeExecutionService
        )
        self.processor.execution_service.read_output.return_value = None
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.RUNNING
        )
        self.processor._training_output_uri = MagicMock(
            return_value=self.handle.outputUri
        )

    def test_completion_is_reported_without_tensorboard(self) -> None:
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.SUCCEEDED
        )

        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.COMPLETED.value)
        self.assertEqual(result.progressPct, 100)
        self.assertEqual(result.currentStep, result.totalSteps)
        self.assertIsNone(result.trainingJob.completedEpochs)
        self.assertIn("completed successfully", result.statusMessage)
        self.processor.execution_service.finalize.assert_called_once()
        self.processor.queue_client.put_message.assert_not_called()

    def test_running_without_metrics_does_not_crash_or_claim_completion(
        self,
    ) -> None:
        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertEqual(result.currentStep, 0)
        self.assertIn("metrics are not yet available", result.statusMessage)
        self.processor.queue_client.put_message.assert_not_called()
        self.processor.execution_service.finalize.assert_not_called()

    def test_empty_event_results_do_not_convert_unset_epoch_to_int(
        self,
    ) -> None:
        with patch.object(
            self.processor, "_get_training_logs", return_value=(None, "[]")
        ):
            result = self.processor.process()
        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertEqual(result.currentStep, 0)
        self.processor.queue_client.put_message.assert_not_called()

    def test_epoch_zero_and_zero_elapsed_are_retained(self) -> None:
        logs = json.dumps([{"epoch": 0, "elapsedDurationInMinutes": 0.0}])
        with patch.object(
            self.processor, "_get_training_logs", return_value=("start", logs)
        ):
            result = self.processor.process()
        self.assertEqual(result.trainingJob.completedEpochs, "0")
        self.assertEqual(result.trainingJob.totalElapsedTime, "0.0")
        self.assertEqual(result.trainingJob.approxMinutesToComplete, "n/a")
        self.assertEqual(result.currentStep, 1)
        self.assertEqual(result.progressPct, 50)
        self.assertIn("calculating...", result.statusMessage)

    def test_workflow_stage_is_visible_before_training_metrics(self) -> None:
        def output(handle, filename, *, as_chunks=False):
            if filename == "workflow_progress.log":
                return "2026-01-01T00:00:00+00:00|Starting fine_tune.py\n"
            return None

        self.processor.execution_service.read_output.side_effect = output
        result = self.processor.process()
        self.assertIn("Starting fine_tune.py", result.statusMessage)
        self.assertNotIn("metrics are not yet available", result.statusMessage)
        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertIsNone(self.handle.providerTaskId)
        self.processor.execution_service.read_output.assert_any_call(
            self.handle, "workflow_progress.log", as_chunks=False
        )
        self.processor.execution_service.get_status.assert_called_once_with(
            self.handle
        )

    def test_not_yet_available_output_remains_a_startup_delay(self) -> None:
        self.processor.execution_service.read_output.side_effect = (
            OutputNotAvailableError("not written yet")
        )

        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertIn("metrics are not yet available", result.statusMessage)
        self.assertNotIn("telemetry is unavailable", result.statusMessage)
        self.processor.logger.warning.assert_not_called()
        self.processor.execution_service.finalize.assert_not_called()

    def test_telemetry_failure_does_not_change_execution_outcome(self) -> None:
        self.processor.execution_service.read_output.side_effect = (
            RuntimeError("provider error with private diagnostics")
        )
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.SUCCEEDED
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.COMPLETED.value)
        self.assertEqual(result.progressPct, 100)
        self.assertNotIn("private diagnostics", result.statusMessage)
        self.assertTrue(self.processor.logger.warning.called)

    def test_running_telemetry_error_is_not_reported_as_startup_delay(
        self,
    ) -> None:
        self.processor.execution_service.read_output.side_effect = (
            RuntimeError("private provider detail")
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertIn("telemetry is unavailable", result.statusMessage)
        self.assertNotIn("private provider detail", result.statusMessage)

    def test_completion_with_legacy_missing_steps_is_safe(self) -> None:
        self.processor.model_data.totalSteps = None
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.SUCCEEDED
        )
        result = self.processor.process()
        self.assertEqual(result.progressPct, 100)
        self.assertEqual(result.totalSteps, 1)

    def test_failed_execution_does_not_become_completed(self) -> None:
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.FAILED
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.FAILED.value)
        self.assertNotIn("completed successfully", result.statusMessage)
        self.assertNotEqual(result.progressPct, 100)

    def _workflow_outputs(self) -> dict[str, str]:
        outputs = {
            "workflow_progress.log": (
                "2026-01-01T00:00:00+00:00|Starting create_masks.py\n"
                "2026-01-01T00:01:00+00:00|Completed create_masks.py\n"
                "2026-01-01T00:02:00+00:00|Starting fine_tune.py\n"
                "2026-01-01T00:03:00+00:00|Error running fine_tune.py\n"
            ),
            "stderr.txt": "private traceback: training failed",
        }

        def output(
            handle: ComputeJobHandle,
            filename: str,
            *,
            as_chunks: bool = False,
        ) -> str | None:
            self.assertEqual(handle, self.handle)
            self.processor.execution_service.finalize.assert_not_called()
            return outputs.get(filename)

        self.processor.execution_service.read_output.side_effect = output
        return outputs

    def _assert_terminal_history(self, status: str, summary: str) -> None:
        self._workflow_outputs()
        self.processor.execution_service.get_status.return_value = {
            self.statuses.FAILED.value: ComputeJobState.FAILED,
            self.statuses.CANCELLED.value: ComputeJobState.CANCELLED,
        }[status]

        result = self.processor.process()

        self.assertEqual(result.status, status)
        self.assertEqual(result.trainingJob.status, status)
        self.assertIsNotNone(result.trainingJob.completedDate)
        self.assertEqual(result.currentStep, 0)
        self.assertEqual(result.progressPct, 0)
        self.assertIsNone(result.checkpointPath)
        history = result.statusMessage
        summary_position = history.index(summary)
        previous_position = -1
        for message in (
            "Starting create_masks.py",
            "Completed create_masks.py",
            "Starting fine_tune.py",
        ):
            position = history.index(message)
            self.assertGreater(position, previous_position)
            self.assertLess(position, summary_position)
            self.assertEqual(history.count(message), 1)
            previous_position = position
        self.assertIn(
            "2026-01-01T00:01:00+00:00: Completed create_masks.py", history
        )
        self.assertIn("Error running fine_tune.py", history[summary_position:])
        self.assertNotIn("private traceback", history)
        self.assertNotIn("completed successfully", history)
        self.processor.logger.error.assert_called_once()
        self.processor.execution_service.finalize.assert_called_once_with(
            self.handle
        )
        self.processor.queue_client.put_message.assert_not_called()

    def test_failure_before_first_poll_keeps_all_stages_before_error(
        self,
    ) -> None:
        self._assert_terminal_history(
            self.statuses.FAILED.value, "Training job failed"
        )

    def test_cancellation_before_first_poll_keeps_all_stages_before_summary(
        self,
    ) -> None:
        self._assert_terminal_history(
            self.statuses.CANCELLED.value, "Training job cancelled"
        )
        self.assertNotIn(
            "Training job failed", self.processor.model_data.statusMessage
        )

    def test_terminal_history_does_not_duplicate_previously_polled_stages(
        self,
    ) -> None:
        self.processor.model_data.statusMessage = (
            "2026-01-01T00:00:00+00:00: Starting create_masks.py"
        )
        self._assert_terminal_history(
            self.statuses.FAILED.value, "Training job failed"
        )

    def test_repeated_stage_messages_keep_distinct_timestamps(self) -> None:
        outputs = self._workflow_outputs()
        outputs[
            "workflow_progress.log"
        ] += "2026-01-01T00:04:00+00:00|Starting fine_tune.py\n"

        self.assertTrue(self.processor._append_workflow_progress(self.handle))
        history = self.processor.model_data.statusMessage
        self.assertEqual(history.count("Starting fine_tune.py"), 2)
        self.assertTrue(self.processor._append_workflow_progress(self.handle))
        self.assertEqual(self.processor.model_data.statusMessage, history)

    def test_unavailable_terminal_history_does_not_prevent_cleanup(
        self,
    ) -> None:
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.FAILED
        )
        self.processor.execution_service.read_output.side_effect = (
            RuntimeError("private provider detail")
        )

        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.FAILED.value)
        self.assertIn("Training job failed", result.statusMessage)
        self.assertNotIn("private provider detail", result.statusMessage)
        self.assertEqual(result.progressPct, 0)
        self.assertTrue(self.processor.logger.warning.called)
        self.processor.execution_service.finalize.assert_called_once_with(
            self.handle
        )

    def test_malformed_stages_do_not_hide_terminal_failure(self) -> None:
        outputs = self._workflow_outputs()
        outputs["workflow_progress.log"] += (
            "unfinished\n"
            "invalid timestamp|Starting ignored.py\n"
            "2026-01-01T00:04:00+00:00| \n"
        )
        self.processor.execution_service.get_status.return_value = (
            ComputeJobState.FAILED
        )

        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.FAILED.value)
        self.assertIn("Completed create_masks.py", result.statusMessage)
        self.assertIn("Training job failed", result.statusMessage)
        self.assertNotIn("Starting ignored.py", result.statusMessage)
        self.assertEqual(self.processor.logger.warning.call_count, 3)
        self.processor.execution_service.finalize.assert_called_once_with(
            self.handle
        )

    def test_direct_cancellation_reads_final_history_before_cleanup(
        self,
    ) -> None:
        outputs = self._workflow_outputs()
        outputs[
            "workflow_progress.log"
        ] = "2026-01-01T00:00:00+00:00|Starting create_masks.py\n"

        def cancel(handle: ComputeJobHandle) -> None:
            self.assertEqual(handle, self.handle)
            outputs[
                "workflow_progress.log"
            ] += "2026-01-01T00:01:00+00:00|Completed create_masks.py\n"

        self.processor.execution_service.cancel.side_effect = cancel

        result = self.processor.cancel()

        self.assertEqual(result.status, self.statuses.CANCELLED.value)
        self.assertEqual(
            result.trainingJob.status, self.statuses.CANCELLED.value
        )
        self.assertEqual(result.progressPct, 0)
        history = result.statusMessage
        self.assertLess(
            history.index("Starting create_masks.py"),
            history.index("Completed create_masks.py"),
        )
        self.assertLess(
            history.index("Completed create_masks.py"),
            history.index("Task task-1 cancelled successfully."),
        )
        self.assertLess(
            history.index("Task task-1 cancelled successfully."),
            history.index("Training cancelled"),
        )
        self.processor.execution_service.cancel.assert_called_once_with(
            self.handle
        )
        self.processor.execution_service.finalize.assert_called_once_with(
            self.handle
        )

    def test_cancellation_before_submission_does_not_read_or_finalize(
        self,
    ) -> None:
        self.processor.model_data.trainingJob = TrainingJob(
            taskId="pending-task", status=self.statuses.PENDING.value
        )

        result = self.processor.cancel()

        self.assertEqual(result.status, self.statuses.CANCELLED.value)
        self.assertIn("cancelled before submission", result.statusMessage)
        self.processor.execution_service.cancel.assert_not_called()
        self.processor.execution_service.read_output.assert_not_called()
        self.processor.execution_service.finalize.assert_not_called()

    def test_completed_epochs_are_observed_not_fabricated_from_target(
        self,
    ) -> None:
        self.processor.model_data.maxEpochs = "20"
        self.processor.model_data.trainingJob.logs = json.dumps(
            [{"epoch": 0, "elapsedDurationInMinutes": 2.0}]
        )
        self.assertTrue(
            self.processor._calculate_upsert_training_metrics(
                job_completed=True
            )
        )
        self.assertEqual(
            self.processor.model_data.trainingJob.completedEpochs, "1"
        )
        self.assertEqual(
            self.processor.model_data.trainingJob.approxMinutesToComplete,
            "0.0",
        )
