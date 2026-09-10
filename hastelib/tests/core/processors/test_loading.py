# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import unittest
from time import sleep
from unittest.mock import Mock

from azure.core.exceptions import ResourceNotFoundError
from hastegeo.core.config import Config
from hastegeo.core.processors.loading import (
    ActiveJobsProcessor,
    assemble_active_jobs,
)


class ProcessorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.types = Config.get_metadata_types()
        self.config = Mock()
        self.config.get_metadata_types.return_value = self.types
        self.processors: dict[tuple[str, str | None], Mock] = {}

    def processor(self, data_type: str, partition: str | None) -> Mock:
        return self.processors.setdefault((data_type, partition), Mock())

    def factory(self, *, data_type, partition_key=None, config):
        self.assertIs(config, self.config)
        return self.processor(data_type, partition_key)


class TestAssembleActiveJobs(unittest.TestCase):
    def test_collects_active_imagery_training_and_inference(self) -> None:
        result = assemble_active_jobs(
            [{"projectId": "project-1", "name": "Project"}],
            {
                "project-1": (
                    [
                        {
                            "imageLayerId": "layer-1",
                            "name": "Layer",
                            "status": "InProgress",
                            "currentStep": 1,
                        }
                    ],
                    [
                        {
                            "modelId": "42",
                            "imageLayerId": "layer-1",
                            "name": "Model",
                            "status": "Queued",
                            "inferenceStatus": "InProgress",
                        }
                    ],
                )
            },
        )

        self.assertEqual(
            [job.kind for job in result.jobs],
            ["Imagery", "Inference", "Training"],
        )
        self.assertEqual(len({job.key for job in result.jobs}), 3)
        for job in result.jobs:
            self.assertIsInstance(job.indicator.currentStep, int)
            self.assertIsInstance(job.indicator.totalSteps, int)
            self.assertIsInstance(job.indicator.progressPct, float)

    def test_excludes_empty_and_terminal_statuses(self) -> None:
        result = assemble_active_jobs(
            [{"projectId": "project-1"}],
            {
                "project-1": (
                    [
                        {"imageLayerId": "one", "status": "Processed"},
                        {"imageLayerId": "two", "status": "Completed"},
                        {"imageLayerId": "three", "status": "Failed"},
                    ],
                    [
                        {
                            "modelId": "42",
                            "imageLayerId": "one",
                            "status": "Trained",
                            "inferenceStatus": None,
                        }
                    ],
                )
            },
        )

        self.assertEqual(result.jobs, [])

    def test_output_order_is_stable_across_storage_order(self) -> None:
        projects = [{"projectId": "project-1"}]
        first = assemble_active_jobs(
            projects,
            {
                "project-1": (
                    [
                        {"imageLayerId": "b", "status": "Queued"},
                        {"imageLayerId": "a", "status": "Queued"},
                    ],
                    [],
                )
            },
        )
        second = assemble_active_jobs(
            projects,
            {
                "project-1": (
                    [
                        {"imageLayerId": "a", "status": "Queued"},
                        {"imageLayerId": "b", "status": "Queued"},
                    ],
                    [],
                )
            },
        )

        self.assertEqual(first.model_dump_json(), second.model_dump_json())


class TestActiveJobsProcessor(ProcessorTestCase):
    async def test_load_reads_only_candidate_layer_and_model_partitions(
        self,
    ) -> None:
        self.processor(self.types.PROJECT.value, None).load.return_value = {
            "projects": [
                {
                    "projectId": "project-1",
                    "name": "One",
                    "imageLayerCount": 1,
                    "modelsCount": 0,
                },
                {
                    "projectId": "project-2",
                    "name": "Two",
                    "imageLayerCount": 0,
                    "modelsCount": 0,
                },
            ]
        }
        self.processor(
            self.types.IMAGELAYER.value, "project-1"
        ).load_all_from_partition.return_value = []

        result = await ActiveJobsProcessor(self.config, self.factory).load()

        self.assertEqual(result.jobs, [])
        self.processor(
            self.types.PROJECT.value, None
        ).load.assert_called_once_with("stats")
        self.assertNotIn(
            (self.types.IMAGELAYER.value, "project-2"), self.processors
        )
        self.assertNotIn(
            (self.types.MODEL.value, "project-1"), self.processors
        )
        self.assertNotIn(
            (self.types.LABELS.value, "project-1"), self.processors
        )
        self.assertNotIn(
            (self.types.VALIDATION.value, "project-1"), self.processors
        )

    async def test_load_normalizes_storage_missing_stats(self) -> None:
        self.processor(
            self.types.PROJECT.value, None
        ).load.side_effect = ResourceNotFoundError("missing")

        with self.assertRaises(FileNotFoundError):
            await ActiveJobsProcessor(self.config, self.factory).load()

    async def test_load_drains_partition_reads_before_raising(self) -> None:
        self.processor(self.types.PROJECT.value, None).load.return_value = {
            "projects": [
                {
                    "projectId": "project-1",
                    "imageLayerCount": 1,
                    "modelsCount": 1,
                }
            ]
        }
        completed = []
        self.processor(
            self.types.IMAGELAYER.value, "project-1"
        ).load_all_from_partition.side_effect = RuntimeError("layer failure")

        def finish_model_read():
            sleep(0.02)
            completed.append("models")
            return []

        self.processor(
            self.types.MODEL.value, "project-1"
        ).load_all_from_partition.side_effect = finish_model_read

        with self.assertRaisesRegex(RuntimeError, "layer failure"):
            await ActiveJobsProcessor(self.config, self.factory).load()

        self.assertEqual(completed, ["models"])

    async def test_load_uses_ids_when_summary_counts_lag(self) -> None:
        self.processor(self.types.PROJECT.value, None).load.return_value = {
            "projects": [
                {
                    "projectId": "project-1",
                    "imageLayerCount": 0,
                    "modelsCount": 0,
                    "modelIds": ["42"],
                }
            ]
        }
        self.processor(
            self.types.MODEL.value, "project-1"
        ).load_all_from_partition.return_value = []

        await ActiveJobsProcessor(self.config, self.factory).load()

        self.processor(
            self.types.MODEL.value, "project-1"
        ).load_all_from_partition.assert_called_once_with()
        self.assertNotIn(
            (self.types.IMAGELAYER.value, "project-1"), self.processors
        )


if __name__ == "__main__":
    unittest.main()
