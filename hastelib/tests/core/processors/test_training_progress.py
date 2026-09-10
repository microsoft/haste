# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.config import Config
from hastegeo.core.models.projects import Model, TrainingJob
from hastegeo.core.processors.train import TrainPostprocessor


class TestTrainingProgress(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.processor = TrainPostprocessor.__new__(TrainPostprocessor)
        self.processor.config = Config()
        self.statuses = self.processor.config.get_status_types()
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
            ),
        )
        self.processor.temp_dir = self.temporary.name
        self.processor.logger = MagicMock()
        self.processor.queue_client = MagicMock()
        self.processor.runner = MagicMock()
        self.processor.runner.get_filecontent_from_task.return_value = None
        self.processor.runner.get_task_status.return_value = (
            self.statuses.IN_PROGRESS.value
        )

    def test_completion_is_reported_without_tensorboard(self) -> None:
        self.processor.runner.get_task_status.return_value = (
            self.statuses.COMPLETED.value
        )

        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.COMPLETED.value)
        self.assertEqual(result.progressPct, 100)
        self.assertEqual(result.currentStep, result.totalSteps)
        self.assertIsNone(result.trainingJob.completedEpochs)
        self.assertIn("completed successfully", result.statusMessage)
        self.processor.runner.cleanup_task.assert_called_once()
        self.processor.queue_client.put_message.assert_not_called()

    def test_running_without_metrics_does_not_crash_or_claim_completion(
        self,
    ) -> None:
        result = self.processor.process()

        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertEqual(result.currentStep, 0)
        self.assertIn("metrics are not yet available", result.statusMessage)
        self.processor.queue_client.put_message.assert_not_called()
        self.processor.runner.cleanup_task.assert_not_called()

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
        def output(**kwargs):
            if kwargs["filename"] == "workflow_progress.log":
                return "2026-01-01T00:00:00+00:00|Starting fine_tune.py\n"
            return None

        self.processor.runner.get_filecontent_from_task.side_effect = output
        result = self.processor.process()
        self.assertIn("Starting fine_tune.py", result.statusMessage)
        self.assertNotIn("metrics are not yet available", result.statusMessage)
        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)

    def test_telemetry_failure_does_not_change_execution_outcome(self) -> None:
        self.processor.runner.get_filecontent_from_task.side_effect = (
            RuntimeError("provider error with private diagnostics")
        )
        self.processor.runner.get_task_status.return_value = (
            self.statuses.COMPLETED.value
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.COMPLETED.value)
        self.assertEqual(result.progressPct, 100)
        self.assertNotIn("private diagnostics", result.statusMessage)
        self.assertTrue(self.processor.logger.warning.called)

    def test_running_telemetry_error_is_not_reported_as_startup_delay(
        self,
    ) -> None:
        self.processor.runner.get_filecontent_from_task.side_effect = (
            RuntimeError("private provider detail")
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.IN_PROGRESS.value)
        self.assertIn("telemetry is unavailable", result.statusMessage)
        self.assertNotIn("private provider detail", result.statusMessage)

    def test_completion_with_legacy_missing_steps_is_safe(self) -> None:
        self.processor.model_data.totalSteps = None
        self.processor.runner.get_task_status.return_value = (
            self.statuses.COMPLETED.value
        )
        result = self.processor.process()
        self.assertEqual(result.progressPct, 100)
        self.assertEqual(result.totalSteps, 1)

    def test_failed_execution_does_not_become_completed(self) -> None:
        self.processor.runner.get_task_status.return_value = (
            self.statuses.FAILED.value
        )
        result = self.processor.process()
        self.assertEqual(result.status, self.statuses.FAILED.value)
        self.assertNotIn("completed successfully", result.statusMessage)
        self.assertNotEqual(result.progressPct, 100)

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
