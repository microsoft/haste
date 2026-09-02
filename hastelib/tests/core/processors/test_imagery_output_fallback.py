# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

"""Unit tests for ImageryPostProcessor's tolerance of compute node loss.

The compute backend persists a task's ``outputs/`` and ``logs/`` to HASTE
storage, so results survive the node being deallocated or preempted. These
tests pin that the processor falls back to that copy instead of failing the
image layer, and that both directories are still submitted for persistence
in the first place (now as ``ComputeOutput`` patterns on the job spec).
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from hastegeo.core.models.compute import (
    BatchProviderDetail,
    ComputeBackend,
    ComputeJobHandle,
    ComputeProviderDetail,
)
from hastegeo.core.models.projects import ImageLayer


def _handle():
    return ComputeJobHandle(
        executionId="img-123",
        requestedBackend=ComputeBackend.AZURE_BATCH,
        selectedBackend=ComputeBackend.AZURE_BATCH,
        backendProfile="imageryprep",
        providerJobId="job-1",
        providerTaskId="img-123",
        targetId="imageryprep-pool",
        outputUri="https://acct.blob.core.windows.net/data/hash/img-123",
        submittedAt="2026-01-01T00:00:00+00:00",
        routingReason="explicit",
        providerDetail=ComputeProviderDetail(
            discriminator="batch",
            batch=BatchProviderDetail(jobId="job-1", taskId="img-123"),
        ),
    )


def _build_processor():
    image_data = MagicMock(spec=ImageLayer)
    image_data.dict.return_value = {}
    image_data.projectId = "proj-1"
    image_data.imageLayerId = "layer-9"
    image_data.preEventImageryUrls = ["https://example/pre.tif"]
    image_data.postEventImageryUrls = ["https://example/post.tif"]
    image_data.sourceTypePreEvent = "url"
    image_data.sourceTypePostEvent = "url"
    image_data.autoFineTune = False
    image_data.userBuildingFootprintsUrl = None
    image_data.clipBbox = None
    image_data.currentStep = 0
    image_data.totalSteps = 4
    image_data.progressPct = 0.0
    image_data.statusMessage = ""
    image_data.computeBackend = None
    image_data.preprocessJob = MagicMock(
        jobId="job-1",
        taskId="img-123",
        creationDate="2026-01-01T00:00:00+00:00",
    )

    with patch(
        "hastegeo.core.processors.imagery.UnifiedDataLayer", autospec=True
    ), patch(
        "hastegeo.core.processors.imagery.AzureQueueHandler", autospec=True
    ):
        from hastegeo.core.processors.imagery import ImageryPostProcessor

        return ImageryPostProcessor(
            image_data=image_data, execution_service=MagicMock()
        )


class TestReadTaskOutputFallback(unittest.TestCase):
    def test_prefers_the_copy_the_backend_still_has(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = "from-node"

        with patch("hastegeo.core.processors.imagery.fetch_url_text") as fetch:
            self.assertEqual(
                processor._read_task_output(
                    _handle(), "imagery_manifest.json"
                ),
                "from-node",
            )
        fetch.assert_not_called()

    def test_falls_back_to_the_uploaded_blob_copy(self):
        processor = _build_processor()
        # The node is gone, so the backend reports the file as unavailable.
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = (
            "https://acct.blob.core.windows.net/c/hash/img-123/"
            "imagery_manifest.json?sas"
        )

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value="from-blob",
        ) as fetch:
            self.assertEqual(
                processor._read_task_output(
                    _handle(), "imagery_manifest.json"
                ),
                "from-blob",
            )

        fetch.assert_called_once()
        # The blob copy lives under the task id, matching the output prefix.
        _, kwargs = processor.storage.get_file_remote_path.call_args
        self.assertEqual(kwargs["identifier"], "imagery_manifest.json")
        self.assertEqual(kwargs["extra_partition_keys"], "img-123")
        self.assertEqual(kwargs["data_format"], "json")

    def test_returns_none_when_neither_copy_is_available(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = None

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value=None,
        ):
            self.assertIsNone(
                processor._read_task_output(_handle(), "imagery_manifest.json")
            )

    def test_a_failing_fallback_does_not_raise(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.side_effect = RuntimeError(
            "storage down"
        )

        self.assertIsNone(
            processor._read_task_output(_handle(), "imagery_manifest.json")
        )


class TestPreprocessLogsAreBestEffort(unittest.TestCase):
    def test_unreachable_log_yields_no_records_instead_of_failing(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = None

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value=None,
        ):
            self.assertEqual(
                processor._get_image_preprocess_logs(_handle()), []
            )

    def test_log_is_parsed_from_the_blob_copy(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = "https://b/log"

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value="2026-08-12T20:00:00|Downloading imagery\n",
        ):
            logs = processor._get_image_preprocess_logs(_handle())

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].message, "Downloading imagery")


class TestUpdateResultsFromJob(unittest.TestCase):
    def test_uses_the_blob_manifest_when_the_node_is_gone(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = "https://b/m"
        manifest = {
            "preview_pre_event_filenames": [],
            "preview_post_event_filenames": [],
            "pre_event_mosaic_filename": "",
            "pre_event_processed_filename": "",
            "post_event_mosaic_filename": "",
            "post_event_processed_filename": "",
            "normalization_means": [1.0],
            "normalization_stds": [2.0],
            "building_footprints_filename": "",
            "building_footprints_error": "",
            "valid_area_mask_filename": "",
            "valid_area_mask_error": "",
        }

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value=json.dumps(manifest),
        ):
            processor._update_results_from_job(_handle())

        self.assertEqual(processor.image_data.normalizationMeans, [1.0])
        self.assertEqual(processor.image_data.normalizationStds, [2.0])

    def test_raises_when_the_manifest_is_lost_everywhere(self):
        processor = _build_processor()
        processor.execution_service.read_output.return_value = None
        processor.storage.get_file_remote_path.return_value = None

        with patch(
            "hastegeo.core.processors.imagery.fetch_url_text",
            return_value=None,
        ):
            with self.assertRaises(FileNotFoundError):
                processor._update_results_from_job(_handle())


class TestSubmittedOutputPatterns(unittest.TestCase):
    def test_persists_both_outputs_and_logs(self):
        processor = _build_processor()
        processor.storage.get_file_remote_path.return_value = (
            "https://acct/c/hash/config.yaml?sig=x"
        )
        processor.execution_service.submit.return_value = _handle()

        processor._execute_image_preprocess()

        spec = processor.execution_service.submit.call_args.args[0]
        patterns = [output.sourceRelativePattern for output in spec.outputs]
        self.assertIn("outputs/*.*", patterns)
        # Without this the progress log only ever exists on the node.
        self.assertIn("logs/*.*", patterns)
        # Every output still lands under the same HASTE task prefix.
        self.assertEqual(
            len({output.destinationUri for output in spec.outputs}), 1
        )


if __name__ == "__main__":
    unittest.main()
