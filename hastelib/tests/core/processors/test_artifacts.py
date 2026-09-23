# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import json

from hastegeo.core.config import Config
from hastegeo.core.models.projects import ModelArtifacts, ZipJob
from hastegeo.core.processors.artifacts import (
    ZIP_IN_PROGRESS_MESSAGE,
    ArtifactProcessor,
)
from hastegeo.core.utils.metadata import MetadataUtils, queued_message_size

STATUS = Config.get_status_types()
# Azure Storage rejects larger queue messages with RequestBodyTooLarge.
QUEUE_MESSAGE_LIMIT_BYTES = 64 * 1024


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

    def test_queueing_a_new_zip_drops_earlier_jobs_logs(self, mocker):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.config = mocker.Mock()
        processor.config.get_status_types.return_value = STATUS
        processor.queue_client = mocker.Mock()
        finished_run = MetadataUtils.append_status_message("", "x" * 16_400)
        processor.model_artifacts = ModelArtifacts(
            modelId="6283",
            projectId="project-1",
            zipStatus=STATUS.COMPLETED.value,
            zipJobs=[
                ZipJob(
                    taskId=f"zip-{run}", status="Completed", logs=finished_run
                )
                for run in range(1, 5)
            ],
        )
        # The stored record the API re-queues: four finished runs, each
        # carrying a full status history, exceed the queue limit as-is.
        stored = json.dumps(processor.model_artifacts.dict())
        assert len(stored.encode("utf-8")) > QUEUE_MESSAGE_LIMIT_BYTES

        processor.send_to_zip_queue()

        payload = processor.queue_client.put_message.call_args.args[0]
        assert len(payload.encode("utf-8")) < QUEUE_MESSAGE_LIMIT_BYTES
        queued = json.loads(payload)
        assert queued["zipStatus"] == STATUS.PENDING.value
        assert [job["taskId"] for job in queued["zipJobs"]] == [
            "zip-1",
            "zip-2",
            "zip-3",
            "zip-4",
        ]
        assert [job["status"] for job in queued["zipJobs"]] == [
            "Completed"
        ] * 4
        assert [job["logs"] for job in queued["zipJobs"]] == [""] * 4

    def test_in_progress_polls_leave_finished_logs_out_of_the_queue(
        self, mocker
    ):
        processor = ArtifactProcessor.__new__(ArtifactProcessor)
        processor.config = mocker.Mock()
        processor.config.get_status_types.return_value = STATUS
        processor.logger = mocker.Mock()
        processor.runner = mocker.Mock()
        processor.runner.get_task_status.return_value = (
            STATUS.IN_PROGRESS.value
        )
        processor.queue_client = mocker.Mock()
        finished_run = MetadataUtils.append_status_message("", "x" * 16_400)
        # A legacy record already in flight: finished runs still carry logs.
        processor.model_artifacts = ModelArtifacts(
            modelId="6283",
            projectId="project-1",
            zipStatus=STATUS.IN_PROGRESS.value,
            currentZipJobUid="zip-5",
            zipStatusMessage=MetadataUtils.append_status_message(
                "", "Submitting zip task"
            ),
            zipJobs=[
                ZipJob(
                    taskId=f"zip-{run}", status="Completed", logs=finished_run
                )
                for run in range(1, 5)
            ]
            + [ZipJob(taskId="zip-5", status=STATUS.IN_PROGRESS.value)],
        )

        processor.process_zip()

        payload = processor.queue_client.put_message.call_args.args[0]
        assert queued_message_size(payload) <= QUEUE_MESSAGE_LIMIT_BYTES
        queued = json.loads(payload)
        assert [job["logs"] for job in queued["zipJobs"][:4]] == [""] * 4
        assert queued["zipJobs"][4]["logs"] == queued["zipStatusMessage"]
        assert ZIP_IN_PROGRESS_MESSAGE in queued["zipStatusMessage"]

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
