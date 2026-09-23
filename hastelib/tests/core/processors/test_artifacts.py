# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ModelArtifacts, ZipJob
from hastegeo.core.processors.artifacts import (
    ZIP_IN_PROGRESS_MESSAGE,
    ArtifactProcessor,
)
from hastegeo.core.utils.metadata import MetadataUtils

STATUS = Config.get_status_types()


class TestArtifactProcessor:
    def test_in_progress_polls_keep_one_progress_entry(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.config = mocker.Mock()
        processor.config.get_status_types.return_value = STATUS
        processor.logger = mocker.Mock()
        processor.runner = mocker.Mock()
        processor.runner.get_task_status.return_value = (
            STATUS.IN_PROGRESS.value
        )
        processor.queue_client = mocker.Mock()
        payload = json.dumps(
            ModelArtifacts(
                modelId="6283",
                projectId="project-1",
                zipStatus=STATUS.IN_PROGRESS.value,
                currentZipJobUid="zip-1",
                zipJobs=[ZipJob(jobId="job-1", taskId="zip-1")],
                zipStatusMessage=MetadataUtils.append_status_message(
                    "", "Submitting zip task"
                ),
            ).dict()
        )

        for _ in range(1000):
            # Each poll starts from the message the previous one queued.
            processor.model_artifacts = ModelArtifacts(**json.loads(payload))
            processor.process_zip()
            payload = processor.queue_client.put_message.call_args.args[0]

        queued = json.loads(payload)
        assert queued["zipStatusMessage"].count(ZIP_IN_PROGRESS_MESSAGE) == 1
        assert queued["zipJobs"][0]["logs"] == queued["zipStatusMessage"]
        assert "Submitting zip task" in queued["zipStatusMessage"]

    def test_fetch_artifact_delegates_to_storage(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.storage = mocker.Mock()
        processor.storage.fetch_artifact.return_value = "/tmp/output"

        result = processor.fetch_artifact(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )

        assert result == "/tmp/output"
        processor.storage.fetch_artifact.assert_called_once_with(
            identifier="artifact",
            extra_partition_keys=["model"],
            src_path="source",
            dst_path="/tmp/output",
        )
